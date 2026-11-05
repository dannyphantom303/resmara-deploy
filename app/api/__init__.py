from fastapi import APIRouter

api_router = APIRouter()

from app.api import auth
from app.api import resmara
from app.api import oauth
from app.api import content
from app.api import engine

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(resmara.router, prefix="", tags=["resmara"])
api_router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
api_router.include_router(content.router, prefix="/content", tags=["content"])
# Campaign engine: /api/boosts/{id}/build|approve|launch, /api/adflow/credits/precheck/
api_router.include_router(engine.router, prefix="", tags=["engine"])
