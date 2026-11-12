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
import asyncio
import time
from datetime import datetime, timezone

from app.db.session import get_db, SessionLocal, User, Boost, AdAccount, Post, Event
from app.core.security import get_current_user
from app.services.credits import CampaignStage, CampaignAction
from app.api.billing import require_paid

router = APIRouter()

# A real build runs four model calls and takes minutes, which is longer than a hosted
# platform's request timeout (Render answers 502 at ~100s and the client hangs up, cancelling
# the request task mid-build). So /build starts the run in the background and answers 202 at
# once; the UI and the deploy checks follow it through /build-status.
_BUILDS: dict = {}

# The event loop only holds a WEAK reference to a task, so a build started with a bare
# asyncio.create_task() can be garbage-collected mid-run: the boost stays "In Progress" for
# ever, no post is written and no error is logged (that is what killed the 9 Nov build).
# Keep a strong reference for as long as the task is alive.
_BUILD_TASKS: set = set()

# A build that has not finished in this long is not running any more. Without a deadline the
# status endpoint reports a dead run as "running" until the process restarts.
BUILD_DEADLINE_SECONDS = 15 * 60

INTERRUPTED_ERROR = (
    "The build stopped before it finished - the server restarted while it was running. "
    "Nothing was lost: start the build again."
)



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


async def _run_build(boost_id: int, user_id: int, force: bool, openings: Optional[dict]):
    """The actual engine run, on its own session so it outlives the request that started it."""
    from app.services.content_engine import build_campaign as run_engine

    state = _BUILDS.setdefault(boost_id, {})
    state.update({"status": "running", "started_at": time.time(), "error": None, "posts_created": 0})
    db = SessionLocal()
    try:
        boost = db.query(Boost).filter(Boost.id == boost_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not boost or not user:
            state.update({"status": "error", "error": "boost or user disappeared mid-build"})
            return
        # Persist the start: if this process dies mid-build, /build-status can still tell the
        # difference between "never started" and "started and was cut off".
        _log(db, user, boost_id, "build_started", {"force": bool(force)})
        db.commit()
        from app.services import llm

        def progress(stage, **extra):
            """Told where the engine has got to; a poll reads it back as build_progress."""
            state["stage"] = stage
            _progress(db, user_id, boost_id, stage, **extra)

        result = await run_engine(boost, db, force=force, openings=openings, progress=progress)
        spent = llm.take_usage()
        state.update({
            "status": "done",
            "posts_created": result.get("posts_created") or 0,
            "source": result.get("source"),
            "violations": len(result.get("violations") or []),
            "notes": (result.get("notes") or [])[:6],
            # What this one campaign cost, as the provider counted it.
            "tokens": spent,
        })
        _log(db, user, boost_id, "campaign_built", {
            "source": result.get("source"), "posts": result.get("posts_created"),
            "violations": len(result.get("violations") or []),
            "tokens": spent.get("total_tokens"), "calls": spent.get("calls"),
        })
        db.commit()
    except Exception as e:  # noqa: BLE001 - the build may fail for a dozen reasons; record it
        db.rollback()
        state.update({"status": "error", "error": str(e)[:400]})
        try:
            from app.services.llm import take_usage
            spent = take_usage()  # a failed run still burned tokens; say how many
            state["tokens"] = spent
            # A campaign that failed while still marked "In Progress" is the worst of both:
            # the customer waits for content that will never arrive. Say it failed.
            boost = db.query(Boost).filter(Boost.id == boost_id).first()
            if boost and (state.get("posts_created") or 0) == 0:
                boost.main_status = "Build failed"
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                _log(db, user, boost_id, "error", {
                    "where": "build_campaign", "error": str(e)[:400],
                    "tokens": spent.get("total_tokens"), "calls": spent.get("calls"),
                })
                db.commit()
        except Exception:
            db.rollback()
    finally:
        state["finished_at"] = time.time()
        db.close()


@router.post("/boosts/{boost_id}/build", status_code=202)
async def build_campaign(boost_id: int, body: BuildRequest = BuildRequest(),
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start the content engine: research -> brand -> style recipe -> N-day plan -> posts.

    Answers 202 immediately and runs the engine in the background; poll /build-status for the
    outcome. Four model calls take minutes, which no hosted proxy will hold open.
    """
    boost = _owned_boost(boost_id, current_user, db)
    require_paid(boost, current_user, db)
    running = _durable_build_state(db, boost)
    if running.get("status") == "running" and not body.force:
        return {"status": "running", "boost_id": boost.id,
                "started_at": running.get("started_at"), "stage": running.get("stage")}
    task = asyncio.create_task(_run_build(boost.id, current_user.id, body.force, body.openings))
    _BUILD_TASKS.add(task)          # strong reference: the loop's own reference is weak
    task.add_done_callback(_BUILD_TASKS.discard)
    _BUILDS[boost.id] = {"status": "running", "started_at": time.time(), "error": None}
    return {"status": "running", "boost_id": boost.id, "started_at": _BUILDS[boost.id]["started_at"]}


# The event types that tell a build's story, in order. Everything /build-status says is read
# back from these, not from a dict in memory: a free instance restarts, a deploy swaps the
# process, and an in-memory "running" flag then either lies for ever or — worse — makes a
# healthy build look dead the moment the poll lands in a process that never saw it start.
_LIFECYCLE_EVENTS = ("build_started", "build_progress", "campaign_built", "error")


def _as_utc(when):
    """A timestamp from the database, always comparable to now (UTC)."""
    if when is None:
        return None
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _last_build_event(db: Session, boost_id: int):
    """The most recent build-lifecycle event for this boost, if any."""
    return (db.query(Event)
            .filter(Event.boost_id == boost_id, Event.event_type.in_(_LIFECYCLE_EVENTS))
            .order_by(Event.id.desc())
            .first())


def _durable_build_state(db: Session, boost: Boost) -> dict:
    """What this boost's last build is doing, read from the events so every worker agrees."""
    last = _last_build_event(db, boost.id)
    posts = db.query(Post).filter(Post.boost_id == boost.id).count()
    if last is None:
        return {"status": "done" if posts else "idle", "posts_created": posts}
    payload = last.payload or {}
    if last.event_type == "campaign_built":
        return {"status": "done", "posts_created": posts,
                "source": payload.get("source"),
                "violations": payload.get("violations") or 0}
    if last.event_type == "error":
        return {"status": "error", "posts_created": posts,
                "error": payload.get("error") or INTERRUPTED_ERROR}
    started = _as_utc(last.created_at)
    age = (datetime.now(timezone.utc) - started).total_seconds() if started else 0
    if age <= BUILD_DEADLINE_SECONDS:
        return {"status": "running", "stage": payload.get("stage"),
                "started_at": started.timestamp() if started else None}
    return {"status": "error", "error": INTERRUPTED_ERROR, "interrupted": True,
            "posts_created": posts}


def _progress(db: Session, user_id: int, boost_id: int, stage: str, **extra):
    """Note where a long build has got to, so a poll can tell 'working' from 'gone'.

    Written on the build's own session. A second connection waits behind the build's open
    transaction (3.7s per note on SQLite, which held the 202 back by eleven seconds); the
    engine has committed its own work at every point this is called.
    """
    try:
        db.add(Event(user_id=user_id, boost_id=boost_id, event_type="build_progress",
                     payload=dict(stage=stage, **extra)))
        db.commit()
    except Exception:  # noqa: BLE001 - a lost progress note must never kill the build
        db.rollback()


def _mark_interrupted(db: Session, boost: Boost, reason: str, user_id: int | None = None):
    """Say out loud that a build died, once, so the next status read is honest."""
    boost.main_status = "Build failed"
    uid = user_id or boost.user_id
    if uid:
        _log(db, User(id=uid), boost.id, "error", {"where": "build_campaign", "error": reason})
    db.commit()


@router.get("/boosts/{boost_id}/build-status")
def build_status(boost_id: int, current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """How the last build for this boost is going (the UI polls this instead of holding a request)."""
    boost = _owned_boost(boost_id, current_user, db)
    state = _durable_build_state(db, boost)
    if state.get("interrupted"):
        # Started, never finished, and long past any real run: a dead run, not a slow one.
        _mark_interrupted(db, boost, "the build started but never finished (%d minute deadline)"
                          % (BUILD_DEADLINE_SECONDS // 60))
        _BUILDS[boost.id] = {"status": "error", "error": INTERRUPTED_ERROR, "interrupted": True}
    # The events carry the outcome; the in-memory run carries the detail nobody stores
    # (notes, token spend, which posts were repaired).
    run = _BUILDS.get(boost.id) or {}
    if run and run.get("status") == state.get("status") == "done":
        state.update({k: v for k, v in run.items() if k in ("notes", "tokens", "source", "violations")})
    state["boost_id"] = boost.id
    started = state.get("started_at")
    if started:
        state["seconds"] = round(time.time() - started, 1)
    return state


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
    require_paid(boost, current_user, db)
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


# The Creatify-style /adflow/credits/precheck/ endpoint is gone with the credit system: a
# campaign is bought outright, so there is no balance to pre-check. See app/api/billing.py.
