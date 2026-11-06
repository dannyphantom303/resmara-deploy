from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from app.api import api_router
from app.core.config import settings
import os

app = FastAPI(title="Resmara API", version="0.2.0",
              # relative so the spec resolves both at /docs (direct) and /resmara/docs (behind the router)
              swagger_ui_parameters={"url": "openapi.json"})

# create_all() makes missing tables but never adds columns to existing ones, so new
# fields (graph ids, publish target, asset tagging) need this idempotent ALTER pass.
from app.db.migrate import migrate, encrypt_stored_tokens


@app.on_event("startup")
def _startup_migrations() -> None:
    """Schema and data migrations belong to the running app, not to importing this module.

    They used to run at import time. Once tokens started being encrypted at rest that became
    actively dangerous: any script or test that imported app.main would migrate - and
    re-encrypt - whatever database the environment happened to point at, with whatever key
    that process happened to have. Importing a module must never write to data.
    """
    added = migrate()
    locked = encrypt_stored_tokens()
    print(f"[resmara] startup migrations: {len(added)} columns added, {locked} token(s) encrypted")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
# Serve whatever UPLOAD_DIR actually is — uploads are written there by app/api/content.py, and
# Instagram fetches post media back through this mount. Hard-coding "uploads" here meant a
# deployment that set UPLOAD_DIR (a mounted volume, say) wrote files to one directory and served
# them from another, so every published picture 404'd.


@app.get("/uploads/{filename}", include_in_schema=False)
def serve_upload(filename: str):
    """The file from disk, or the copy stored with the asset when the disk was reset.

    A hosted instance without a persistent volume starts empty, so an imported photo would
    otherwise be a 404 until someone re-uploaded it. Asset rows carry the bytes for exactly
    this case; this route is registered before the StaticFiles mount so it wins.
    """
    safe = os.path.basename(filename)
    on_disk = os.path.join(settings.UPLOAD_DIR, safe)
    if os.path.isfile(on_disk):
        return FileResponse(on_disk)
    from fastapi import HTTPException
    from fastapi.responses import Response
    from app.db.session import Asset, SessionLocal

    db = SessionLocal()
    try:
        asset = db.query(Asset).filter(Asset.filename == safe).first()
        if asset is not None and asset.data:
            return Response(content=bytes(asset.data), media_type=asset.content_type or "image/jpeg",
                            headers={"Cache-Control": "public, max-age=3600"})
    finally:
        db.close()
    raise HTTPException(status_code=404, detail="Not Found")


app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(api_router, prefix="/api")


@app.get("/robots.txt", include_in_schema=False)
def robots():
    """A testing site should not be indexed. Remove this once the beta gate comes off."""
    if settings.SIGNUP_EMAILS or settings.SIGNUP_CODE:
        return Response(content="User-agent: *\nDisallow: /\n", media_type="text/plain")
    return Response(content="User-agent: *\nAllow: /\n", media_type="text/plain")

# Serve static frontend at root (after API routes)
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
