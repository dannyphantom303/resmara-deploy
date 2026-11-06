"""Photo upload + asset tagging, content generation, publishing and reports.

Every number this module returns is either read from the database or pulled from the
Meta Graph API. Where Meta has not shared data yet it says so (source='unavailable')
instead of inventing a figure - the old formula-based report numbers are gone.
"""
import os
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db, User, Boost, Post, Ad, Creative, Asset, Event, AdAccount
from app.core.security import get_current_user
from app.core.config import settings
from datetime import datetime, timedelta
import json

router = APIRouter()

UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

SAFE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".heic"}


class PhotoImportRequest(BaseModel):
    """Either a listing page to scrape, or the direct image URLs to pull."""
    boost_id: int
    listing_url: str | None = None
    urls: list[str] = []
    limit: int = 10


def _owned_boost(boost_id: int, current_user: User, db: Session) -> Boost:
    """Fetch a boost the caller may act on (owner, or an admin)."""
    q = db.query(Boost).filter(Boost.id == boost_id)
    if not current_user.is_admin:
        q = q.filter(Boost.user_id == current_user.id)
    boost = q.first()
    if not boost:
        raise HTTPException(status_code=404, detail="Boost not found")
    return boost


def _save_upload(file: UploadFile) -> tuple[str, str, int]:
    """Store an uploaded file and return (stored_name, url, size). Rejects traversal."""
    original = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(original)[1].lower()
    if ext not in SAFE_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type {ext or '(none)'}")
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return filename, f"/uploads/{filename}", os.path.getsize(filepath)


# --- Photo upload -------------------------------------------------------------

@router.post("/upload/photo", status_code=201)
async def upload_photo(file: UploadFile = File(...), boost_id: int = Form(None), kind: str = Form("photo"),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Upload one photo/video. Returns the stored url AND records an Asset row, so the
    content engine can build the campaign's PHOTO INDEX from what was actually uploaded."""
    if boost_id is not None:
        _owned_boost(boost_id, current_user, db)
    filename, url, size = _save_upload(file)
    # Keep the bytes with the row as well: uploads/ is lost on the next deploy of a
    # free-tier instance, and a photo post then renders a broken image.
    blob = None
    ctype = file.content_type if (file.content_type or "").startswith("image/") else None
    if ctype:
        try:
            with open(os.path.join(UPLOAD_DIR, filename), "rb") as fh:
                blob = fh.read()
        except OSError:
            blob = None
    asset = Asset(user_id=current_user.id, boost_id=boost_id, filename=filename, url=url,
                  original_name=os.path.basename(file.filename or ""), kind=kind,
                  data=blob, content_type=ctype)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"filename": filename, "url": url, "size": size, "asset_id": asset.id,
            "original_name": asset.original_name, "boost_id": boost_id, "kind": kind}


@router.post("/uploads", status_code=201)
async def upload_many(boost_id: int = Form(None), kind: str = Form("photo"),
                      files: list[UploadFile] = File(...),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Bulk upload - one Asset row per file."""
    if boost_id is not None:
        _owned_boost(boost_id, current_user, db)
    out = []
    for f in files:
        filename, url, size = _save_upload(f)
        asset = Asset(user_id=current_user.id, boost_id=boost_id, filename=filename, url=url,
                      original_name=os.path.basename(f.filename or ""), kind=kind)
        db.add(asset)
        db.commit()
        db.refresh(asset)
        out.append({"asset_id": asset.id, "url": url, "original_name": asset.original_name, "size": size})
    return {"count": len(out), "assets": out}


@router.post("/import/photos", status_code=201)
async def import_photos_endpoint(payload: PhotoImportRequest, current_user: User = Depends(get_current_user),
                                db: Session = Depends(get_db)):
    """Pull a campaign's gallery in: from a listing page, or from direct image URLs.

    Posts only show a photo when the engine's plan names an Asset that exists, so an
    empty gallery means an all-text calendar. This is the way photos get in without a
    manual file picker per post.
    """
    from app.services import photos

    boost = _owned_boost(payload.boost_id, current_user, db)
    limit = max(1, min(int(payload.limit or photos.DEFAULT_LIMIT), 20))
    urls = [u.strip() for u in (payload.urls or []) if (u or "").strip()][:limit]
    source = "urls"
    listed = 0
    if not urls:
        if not (payload.listing_url or "").strip():
            raise HTTPException(status_code=400, detail="Give a listing URL or at least one image URL.")
        try:
            urls = await photos.discover(payload.listing_url.strip(), limit=limit)
        except Exception as exc:  # a bot wall or a dead page is the caller's problem to see
            raise HTTPException(status_code=400, detail=f"Could not read that listing page: {exc.__class__.__name__}")
        source = "listing_url"
        listed = len(urls)
        if not urls:
            return {"boost_id": boost.id, "source": source, "found": 0, "imported": 0,
                    "assets": [], "skipped": [],
                    "detail": "No image links on that page. Upload the photos directly, or paste direct image URLs."}

    result = await photos.import_from_urls(
        db, user_id=current_user.id, boost_id=boost.id, urls=urls,
        upload_dir=UPLOAD_DIR, limit=limit,
    )
    result.update({"boost_id": boost.id, "source": source, "found": listed or len(urls)})
    if not result["imported"]:
        result["detail"] = ("Nothing could be downloaded. Use direct image URLs "
                            "(right-click a photo → Copy image address) or upload files.")
    return result


@router.get("/assets/{boost_id}")
def list_assets(boost_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_boost(boost_id, current_user, db)
    assets = db.query(Asset).filter(Asset.boost_id == boost_id).order_by(Asset.id).all()
    return [{
        "id": a.id, "url": a.url, "original_name": a.original_name, "kind": a.kind,
        "room": a.room, "social_score": a.social_score, "shape": a.shape,
        "see": a.see, "story": a.story, "tags": a.tags or [], "tagged_by": a.tagged_by,
    } for a in assets]


@router.post("/assets/{boost_id}/tag")
async def tag_assets_endpoint(boost_id: int, current_user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """AI-tag the listing photos (room, shape, what is visible, the STORY detail the
    captions are built from) using the handoff spec's photo-tagging prompt."""
    from app.services.content_engine import tag_assets
    _owned_boost(boost_id, current_user, db)
    assets = db.query(Asset).filter(Asset.boost_id == boost_id, Asset.kind == "photo").all()
    if not assets:
        raise HTTPException(status_code=400, detail="No photos uploaded for this boost yet")
    result = await tag_assets(assets, base_url=settings.PUBLIC_BASE_URL, db=db)
    db.commit()
    return result


@router.get("/photo-index/{boost_id}")
def photo_index(boost_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The PHOTO INDEX text the campaign plan is written from, exactly as the engine sees it."""
    from app.services.content_engine import build_photo_index
    _owned_boost(boost_id, current_user, db)
    assets = db.query(Asset).filter(Asset.boost_id == boost_id).order_by(Asset.id).all()
    return {"boost_id": boost_id, "assets": len(assets), "photo_index": build_photo_index(assets)}


# --- Content generation -------------------------------------------------------

@router.post("/generate/content")
async def generate_content(
    boost_id: int = Form(...),
    agent_name: str = Form(""), phone: str = Form(""), license_no: str = Form(""),
    brokerage: str = Form(""), instagram: str = Form(""), website: str = Form(""),
    property_website: str = Form(""),
    beds: int = Form(0), baths: int = Form(0), sqft: int = Form(0), city: str = Form(""),
    feature: str = Form(""), cta: str = Form(""), notes: str = Form(""),
    force: bool = Form(False),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Run the real content engine for this boost (research -> brand -> style -> plan).

    The form fields are the agent card the spec's ticket would carry; they are saved on
    the boost so a rebuild does not need them typed in again.
    """
    from app.services.content_engine import build_campaign
    boost = _owned_boost(boost_id, current_user, db)

    agent_card = {
        "agent_name": agent_name or "", "phone": phone or "", "license": license_no or "",
        "brokerage": brokerage or "", "instagram": instagram or "",
        "website": website or "", "property_website": property_website or "",
    }
    facts = " · ".join(x for x in [
        f"{beds} bedrooms" if beds else "", f"{baths} bathrooms" if baths else "",
        f"{sqft} sqft" if sqft else "", city or "", feature or "", cta or "",
    ] if x)
    ad_brief = dict(boost.ad_brief or {})
    ad_brief["agent_card"] = agent_card
    boost.ad_brief = ad_brief
    if facts and not boost.property_facts:
        boost.property_facts = facts

    try:
        result = await build_campaign(boost, db, force=force,
                                      openings={**agent_card, "facts": boost.property_facts or "", "notes": notes})
    except Exception as e:
        db.add(Event(user_id=current_user.id, boost_id=boost.id, event_type="error",
                     payload={"where": "generate_content", "error": str(e)[:400]}))
        db.commit()
        raise HTTPException(status_code=502, detail=f"Content engine failed: {e}")

    return {
        "status": "generated",
        "boost_id": boost_id,
        "source": result.get("source"),
        "posts_created": result.get("posts_created"),
        "violations": result.get("violations") or [],
        "missing_info": result.get("missing_info") or [],
        "models": result.get("model"),
    }


# --- Publishing ---------------------------------------------------------------

def _require_system_token(x_resmara_token: str = Header(default="")):
    """The scheduler entrypoint is machine-called, so it uses a shared token rather than
    a user login. Refused outright when no token is configured."""
    if not settings.PUBLISH_TOKEN:
        raise HTTPException(status_code=503, detail="RESMARA_PUBLISH_TOKEN is not configured")
    if x_resmara_token != settings.PUBLISH_TOKEN:
        raise HTTPException(status_code=403, detail="Bad publish token")


@router.post("/publish/run")
async def publish_run(x_resmara_token: str = Depends(_require_system_token), db: Session = Depends(get_db)):
    """Publish every approved post whose publish_at has passed. Called by the scheduler."""
    from app.services.publisher import publish_due
    return await publish_due(db)


@router.post("/publish/boost/{boost_id}")
async def publish_boost(boost_id: int, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Publish this boost's due posts now (the button in the UI)."""
    from app.services.publisher import publish_due
    boost = _owned_boost(boost_id, current_user, db)
    return await publish_due(db, boost_id=boost.id)


@router.get("/publish/status/{boost_id}")
def publish_status(boost_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What is scheduled, what went out, and what failed (with the error)."""
    _owned_boost(boost_id, current_user, db)
    posts = db.query(Post).filter(Post.boost_id == boost_id).order_by(Post.day, Post.slot).all()
    now = datetime.utcnow().isoformat()
    counts = {}
    for p in posts:
        key = p.publish_status or "scheduled"
        counts[key] = counts.get(key, 0) + 1
    return {
        "boost_id": boost_id,
        "counts": counts,
        "next_due": next((p.publish_at for p in posts
                          if (p.publish_status or "scheduled") == "scheduled"
                          and p.publish_at and p.publish_at > now), None),
        "posts": [{"id": p.id, "day": p.day, "slot": p.slot, "kind": p.kind,
                   "client_status": p.client_status, "publish_status": p.publish_status,
                   "publish_at": p.publish_at, "publish_target": p.publish_target,
                   "fb_post_id": p.fb_post_id, "ig_media_id": p.ig_media_id,
                   "last_error": p.last_error} for p in posts],
    }


# --- Reports ------------------------------------------------------------------

@router.get("/reports/{boost_id}")
async def get_report(boost_id: int, day: int = 7, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Day-7 / day-14 report built from real Meta data.

    Organic post metrics and paid ad numbers come from the Graph API. If the ad account
    is not connected (or Meta has shared nothing yet) the sections carry
    source='unavailable' plus a reason - never an estimate.
    """
    from app.services.insights import organic_results, ad_numbers
    boost = _owned_boost(boost_id, current_user, db)

    posts = db.query(Post).filter(Post.boost_id == boost.id).all()
    ads = db.query(Ad).filter(Ad.boost_id == boost.id).all()

    # Period: go-live date + day-1 when we know it, otherwise a rolling window.
    try:
        gl = datetime.strptime(boost.go_live_date, "%Y-%m-%d") if boost.go_live_date else None
    except ValueError:
        gl = None
    frm = gl if gl else (datetime.utcnow() - timedelta(days=day))
    to = frm + timedelta(days=day - 1)
    from_iso, to_iso = frm.strftime("%Y-%m-%d"), to.strftime("%Y-%m-%d")

    ad_account = None
    if boost.ad_account_id:
        ad_account = db.query(AdAccount).filter(AdAccount.id == boost.ad_account_id).first()
    if not ad_account:
        ad_account = (db.query(AdAccount)
                      .filter(AdAccount.user_id == boost.user_id, AdAccount.platform == "meta",
                              AdAccount.is_active == True).first())

    organic = await organic_results(db, boost, ad_account, from_iso, to_iso)
    paid = await ad_numbers(db, boost, from_iso, to_iso)
    db.commit()
    summary = organic.get("summary") or {}
    measured = int(summary.get("measured") or 0)

    return {
        "boost_id": boost.id,
        "address": boost.address,
        "report_day": day,
        "period": {"from": from_iso, "to": to_iso, "label": f"Day 1 to Day {day}"},
        "posts": {"total": len(posts),
                  "published": len([p for p in posts if p.publish_status == "posted"]),
                  "approved": len([p for p in posts if p.client_status == "approved"])},
        "ads": {"total": len(ads),
                "live": len([a for a in ads if (a.status or "") in ("live", "submitted")])},
        "organic": organic,
        "paid": paid,
        # Kept so older clients do not break, but now sourced from real data. Null - not 0 -
        # when nothing was measured, so no screen can render a fake zero.
        "metrics": {
            "source": organic.get("source"),
            "reach": summary.get("reach") if measured else None,
            "interactions": summary.get("interactions") if measured else None,
            "ad_spend": paid.get("spend"),
            "ad_impressions": paid.get("impressions"),
            "ad_clicks": paid.get("clicks"),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/reports/{boost_id}/download")
async def download_report(boost_id: int, day: int = 7, current_user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Same payload as the report (JSON for now; the PDF step is a later delivery)."""
    return await get_report(boost_id, day, current_user, db)
