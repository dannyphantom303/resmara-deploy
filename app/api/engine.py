"""Campaign engine endpoints: AI content build -> client approval -> real Meta launch.

The launch half mirrors the Creatify ad flow the dashboard was reverse-engineered from
(see app/services/credits.py and app/services/ad_platforms.py): a two-layer approval gate
(budget precheck + copy approval) in front of campaign -> adset -> creative -> ad, driven
by the same PENDING -> PENDING_APPROVAL -> APPROVED -> DEPLOYED -> LIVE state machine.

The gate itself lives in app/services/launch.py so /api/resmara/launch and
/api/boosts/{id}/launch cannot drift apart. Nothing here spends money: every campaign is
created PAUSED.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db, User, Boost, AdAccount, Post, Event
from app.core.security import get_current_user
from app.services.credits import check_credit, CampaignStage, CampaignAction

router = APIRouter()


def _owned_boost(boost_id: int, current_user: User, db: Session) -> Boost:
    """Fetch a boost the caller may act on (owner, or an admin)."""
    q = db.query(Boost).filter(Boost.id == boost_id)
    if not current_user.is_admin:
        q = q.filter(Boost.user_id == current_user.id)
    boost = q.first()
    if not boost:
        raise HTTPException(status_code=404, detail="Boost not found")
    return boost


def _log(db: Session, current_user: User, boost_id: int, event_type: str, payload: dict):
    db.add(Event(user_id=current_user.id, boost_id=boost_id, event_type=event_type, payload=payload))


class BuildRequest(BaseModel):
    force: bool = False
    # Manual facts win over the AI (the spec's AI Notes / team corrections rule).
    openings: Optional[dict] = None


@router.post("/boosts/{boost_id}/build")
async def build_campaign(boost_id: int, body: BuildRequest = BuildRequest(),
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run the content engine: research -> brand -> style recipe -> N-day plan -> posts."""
    from app.services.content_engine import build_campaign as run_engine
    boost = _owned_boost(boost_id, current_user, db)
    try:
        result = await run_engine(boost, db, force=body.force, openings=body.openings)
    except Exception as e:  # surface the engine failure instead of a bare 500
        _log(db, current_user, boost_id, "error", {"where": "build_campaign", "error": str(e)[:400]})
        db.commit()
        raise HTTPException(status_code=502, detail=f"Content engine failed: {e}")
    _log(db, current_user, boost_id, "campaign_built", {
        "source": result.get("source"), "posts": result.get("posts_created"),
        "violations": len(result.get("violations") or []),
    })
    db.commit()
    return result


@router.get("/boosts/{boost_id}/plan")
def get_plan(boost_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    boost = _owned_boost(boost_id, current_user, db)
    return {
        "boost_id": boost.id,
        "address": boost.address,
        "stage": boost.stage,
        "main_status": boost.main_status,
        "plan": boost.plan or {},
        "brand_profile": boost.brand_profile or {},
        "ad_brief": boost.ad_brief or {},
    }


@router.get("/boosts/{boost_id}/posts")
def list_posts(boost_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The campaign's posts with the engine's scheduling and publishing state."""
    boost = _owned_boost(boost_id, current_user, db)
    posts = db.query(Post).filter(Post.boost_id == boost.id).order_by(Post.day, Post.slot).all()
    return [{
        "id": p.id, "day": p.day, "slot": p.slot, "kind": p.kind, "caption": p.caption,
        "hashtags": p.hashtags, "cta": p.cta, "image_url": p.image_url,
        "client_status": p.client_status, "publish_status": p.publish_status,
        "publish_at": p.publish_at, "publish_target": p.publish_target,
        "fb_post_id": p.fb_post_id, "ig_media_id": p.ig_media_id, "last_error": p.last_error,
    } for p in posts]


@router.post("/boosts/{boost_id}/approve")
def approve_campaign(boost_id: int, body: dict = None,
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Client approval. Approving the posts is what unblocks the publisher, so this is the
    copy-approval half of the two-layer gate."""
    boost = _owned_boost(boost_id, current_user, db)
    body = body or {}
    only_ids = set(body.get("post_ids") or [])
    posts = db.query(Post).filter(Post.boost_id == boost.id).all()
    approved = 0
    for p in posts:
        if only_ids and p.id not in only_ids:
            continue
        p.client_status = "approved"
        approved += 1
    boost.main_status = "Approved"
    if CampaignStage.can_transition(boost.stage or CampaignStage.PENDING, CampaignStage.APPROVED):
        boost.stage = CampaignStage.APPROVED
    _log(db, current_user, boost.id, "campaign_approved", {"posts_approved": approved})
    db.commit()
    return {"status": "approved", "boost_id": boost.id, "posts_approved": approved, "stage": boost.stage}


@router.post("/boosts/{boost_id}/launch")
async def launch(boost_id: int, body: dict = None,
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Launch this boost's Meta campaign for real (created PAUSED).

    Gate: budget precheck (subscription + ad-account budget) AND copy approval (every post
    approved, or an explicit auto_approve for a trusted operator).
    """
    from app.services.launch import launch_boost
    boost = _owned_boost(boost_id, current_user, db)
    body = body or {}
    result = await launch_boost(
        boost, current_user, db,
        budget_usd=body.get("budget_usd"),
        auto_approve=bool(body.get("auto_approve")),
        action=body.get("action") or CampaignAction.LAUNCH_NEW_CAMPAIGN,
        custom_configs=body.get("meta_custom_configs") or {},
    )
    if result.get("status") == "failed":
        raise HTTPException(status_code=502, detail=result.get("detail"))
    return result


class PrecheckRequest(BaseModel):
    platform: str = "meta"
    advertiser_id: Optional[str] = None
    budget: float = 0.0


@router.post("/adflow/credits/precheck/")
def credits_precheck(body: PrecheckRequest = PrecheckRequest(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Creatify's /tools/adflow/credits/precheck/ gate, reimplemented against our own
    ad-account budget. The launch UI calls this before it offers the launch button."""
    q = db.query(AdAccount).filter(AdAccount.user_id == current_user.id, AdAccount.platform == body.platform)
    if body.advertiser_id:
        q = q.filter(AdAccount.advertiser_id == body.advertiser_id)
    ad_account = q.first()
    if not ad_account:
        raise HTTPException(status_code=400, detail=f"Ad account not found for platform {body.platform}")
    return check_credit(current_user, ad_account, body.budget)
