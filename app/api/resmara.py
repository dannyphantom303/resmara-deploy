from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db, User, AdAccount, Creative, Boost, Post, Ad, SupportTicket, Event
from app.core.testdata import is_test_email
from app.core.security import get_current_user, get_admin_user
from app.schemas.resmara import (
    AdAccountCreate, AdAccountOut, CreativeCreate, CreativeOut,
    BoostCreate, BoostOut, LaunchPayload, SupportTicketCreate, SupportTicketOut,
    AdminUserOut, SystemHealth, MetricsOut
)
# Every operator number comes from app/services/metrics.py: health answers "is the
# service well", metrics answers "what is the product doing", and neither repeats the other.
from app.services import metrics as metrics_service
# The launch gate (budget precheck + copy approval + state machine) and the Graph
# client live in app/services/launch.py and app/services/ad_platforms.py, so both launch
# entrypoints share one implementation.
from datetime import datetime
import json

router = APIRouter()

# --- Ad Accounts ---
@router.post("/ad-accounts", response_model=AdAccountOut, status_code=201)
def create_ad_account(acct: AdAccountCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Connect an ad account. Supply access_token (+ page_id/ig_user_id) to leave
    simulated mode; omit the token and the account stays a prototype that never
    touches the network."""
    new_acct = AdAccount(
        user_id=current_user.id, platform=acct.platform, advertiser_id=acct.advertiser_id,
        account_name=acct.account_name, budget=acct.budget, currency=acct.currency,
        access_token=acct.access_token or "sim_token_prototype",
        page_id=acct.page_id, ig_user_id=acct.ig_user_id,
    )
    db.add(new_acct)
    db.commit()
    db.refresh(new_acct)
    return new_acct

def _account_out(acct: AdAccount) -> AdAccountOut:
    """An ad account as the client should see it: connection health included.

    In a client-billed connection the account is the customer's and their card pays Meta,
    so "connected" on its own is not enough - the client needs to see whether our access is
    still good and whether Meta would actually let the account spend. A status we have never
    measured is reported as None (shown as "not checked yet"), never assumed to be fine.
    """
    from app.services import token_health
    status = acct.token_status
    if not status:
        status = token_health.STATUS_SIMULATED if token_health.is_simulated(acct) else None
    return AdAccountOut(
        id=acct.id, platform=acct.platform, advertiser_id=acct.advertiser_id,
        account_name=acct.account_name, currency=acct.currency, budget=acct.budget,
        is_active=bool(acct.is_active),
        token_status=status,
        token_expires_at=acct.token_expires_at,
        token_note=acct.token_note,
        token_refresh_note=acct.token_refresh_note,
        needs_reconnect=status == token_health.STATUS_NEEDS_RECONNECT,
        funding_status=acct.funding_status,
        funding_note=acct.funding_note,
        account_status=acct.account_status,
        account_status_label=token_health.account_status_label(acct.account_status),
        health_checked_at=acct.token_checked_at,
        page_id=acct.page_id, ig_user_id=acct.ig_user_id,
    )


@router.get("/ad-accounts", response_model=list[AdAccountOut])
def list_ad_accounts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(AdAccount).filter(AdAccount.user_id == current_user.id,
                                      AdAccount.is_active == True).all()
    return [_account_out(a) for a in rows]


@router.post("/ad-accounts/check-all")
async def check_all_ad_accounts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-check every connected account against Meta right now.

    This is what the Connect panel's button calls: it is also what a scheduled job calls, so
    a token that is about to expire is refreshed days early and the client is told to
    reconnect the moment Meta stops honouring the token.
    """
    from app.services import token_health
    rows = db.query(AdAccount).filter(AdAccount.user_id == current_user.id,
                                      AdAccount.is_active == True).all()
    checks = [await token_health.refresh_account(a, db) for a in rows]
    return {
        "checked": len(checks),
        "needs_reconnect": [c["account"] for c in checks if c.get("token_status") == token_health.STATUS_NEEDS_RECONNECT],
        "not_ready_to_spend": [c["account"] for c in checks if not c.get("spend_ok") and c.get("token_status") != token_health.STATUS_NEEDS_RECONNECT],
        "accounts": [_account_out(a) for a in rows],
        "checks": checks,
    }


@router.post("/ad-accounts/{account_id}/check")
async def check_ad_account(account_id: int, current_user=Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """Re-check one account: is our token still good, and can this account spend?"""
    from app.services import token_health
    acct = db.query(AdAccount).filter(AdAccount.id == account_id,
                                      AdAccount.user_id == current_user.id).first()
    if not acct:
        raise HTTPException(status_code=404, detail="Ad account not found")
    check = await token_health.refresh_account(acct, db)
    return {"account": _account_out(acct), "check": check}

# --- Creatives ---
@router.post("/creatives", response_model=CreativeOut, status_code=201)
def create_creative(creative: CreativeCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    new_c = Creative(user_id=current_user.id, **creative.model_dump())
    db.add(new_c)
    db.commit()
    db.refresh(new_c)
    return new_c

@router.get("/creatives", response_model=list[CreativeOut])
def list_creatives(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Creative).filter(Creative.user_id == current_user.id).all()

@router.patch("/creatives/{creative_id}/approve")
def approve_creative(creative_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Creative).filter(Creative.id == creative_id, Creative.user_id == current_user.id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Creative not found")
    c.render_status = "APPROVED"
    db.commit()
    return {"status": "approved", "creative_id": c.id}

# --- Boosts (Campaigns) ---
@router.post("/boosts", response_model=BoostOut, status_code=201)
def create_boost(boost: BoostCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    new_boost = Boost(user_id=current_user.id, **boost.model_dump())
    db.add(new_boost)
    db.flush()
    db.add(Event(user_id=current_user.id, boost_id=new_boost.id, event_type="campaign_drafted",
                 payload={"address": new_boost.address, "days": new_boost.campaign_days}))
    db.commit()
    db.refresh(new_boost)
    return new_boost

@router.get("/boosts", response_model=list[BoostOut])
def list_boosts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """This client's campaigns, each with its real post counts (no invented progress)."""
    from sqlalchemy import func
    boosts = db.query(Boost).filter(Boost.user_id == current_user.id).all()
    ids = [b.id for b in boosts]
    counted = {}
    if ids:
        total = dict(db.query(Post.boost_id, func.count(Post.id)).filter(Post.boost_id.in_(ids)).group_by(Post.boost_id).all())
        approved = dict(db.query(Post.boost_id, func.count(Post.id)).filter(
            Post.boost_id.in_(ids), Post.client_status == "approved").group_by(Post.boost_id).all())
        published = dict(db.query(Post.boost_id, func.count(Post.id)).filter(
            Post.boost_id.in_(ids), Post.publish_status == "published").group_by(Post.boost_id).all())
        counted = {bid: (total.get(bid, 0), approved.get(bid, 0), published.get(bid, 0)) for bid in ids}
    rows = []
    for b in boosts:
        row = BoostOut.model_validate(b)
        row.posts_total, row.posts_approved, row.posts_published = counted.get(b.id, (0, 0, 0))
        rows.append(row)
    return rows

@router.get("/boosts/{boost_id}", response_model=BoostOut)
def get_boost(boost_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.query(Boost).filter(Boost.id == boost_id, Boost.user_id == current_user.id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Boost not found")
    return b

# --- Launch Campaign ---
@router.post("/launch")
async def launch_campaign(payload: LaunchPayload, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Launch the Meta campaign for an already-built boost.

    Delegates to the one shared launch gate in app/services/launch.py. The previous
    version hard-coded budget_approved/copy_approved/can_auto_publish to True and
    created a throwaway boost row named "Campaign Launch" on every call.
    """
    from app.services.launch import launch_boost
    if not payload.boost_id:
        raise HTTPException(status_code=400, detail="boost_id is required - build the campaign first")

    boost = db.query(Boost).filter(Boost.id == payload.boost_id).first()
    if not boost or (boost.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(status_code=404, detail="Boost not found")

    # A hand-edited budget from the launch UI wins over the boost's stored budget.
    custom = payload.meta_custom_configs or {}
    daily = (custom.get("campaign") or {}).get("daily_budget")
    budget = (float(daily) / 100.0) if daily else None

    result = await launch_boost(boost, current_user, db, budget_usd=budget,
                                auto_approve=payload.auto_approve, custom_configs=custom)
    return result

# --- Posts ---
@router.post("/posts", status_code=201)
def create_post(boost_id: int, day: int, caption: str = "", image_url: str = "", current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    boost = db.query(Boost).filter(Boost.id == boost_id, Boost.user_id == current_user.id).first()
    if not boost:
        raise HTTPException(status_code=404, detail="Boost not found")
    post = Post(boost_id=boost_id, day=day, caption=caption, image_url=image_url)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post

@router.get("/posts/{boost_id}")
def get_posts(boost_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    # Ownership matters here: this used to return ANY boost's posts to ANY logged-in user.
    boost = db.query(Boost).filter(Boost.id == boost_id).first()
    if not boost or (boost.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(status_code=404, detail="Boost not found")
    return db.query(Post).filter(Post.boost_id == boost_id).order_by(Post.day, Post.slot).all()

@router.patch("/posts/{post_id}/approve")
def approve_post(post_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    # Same hole: approving was open to every logged-in user for any post id.
    boost = db.query(Boost).filter(Boost.id == post.boost_id).first()
    if not boost or (boost.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(status_code=404, detail="Post not found")
    post.client_status = "approved"
    db.commit()
    return {"status": "approved", "post_id": post.id}

# --- Support ---
@router.post("/support", response_model=SupportTicketOut, status_code=201)
def create_ticket(ticket: SupportTicketCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    new_ticket = SupportTicket(user_id=current_user.id, subject=ticket.subject, messages=[{"from": current_user.email, "text": ticket.message, "at": datetime.utcnow().isoformat()}])
    db.add(new_ticket)
    db.flush()
    db.add(Event(user_id=current_user.id, event_type="ticket_created",
                 payload={"ticket_id": new_ticket.id, "subject": ticket.subject[:120]}))
    db.commit()
    db.refresh(new_ticket)
    return new_ticket

@router.get("/support", response_model=list[SupportTicketOut])
def list_tickets(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(SupportTicket).filter(SupportTicket.user_id == current_user.id).all()

# --- Admin ---
@router.get("/admin/users", response_model=list[AdminUserOut])
def admin_users(current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    result = []
    for u in users:
        boost_count = db.query(Boost).filter(Boost.user_id == u.id).count()
        result.append(AdminUserOut(id=u.id, email=u.email, name=u.name, is_active=u.is_active, subscription_status=u.subscription_status, last_login=u.last_login, created_at=u.created_at, campaign_count=boost_count, is_test=is_test_email(u.email)))
    return result

@router.get("/admin/support", response_model=list[SupportTicketOut])
def admin_support(current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    """Every ticket, newest first, with the client's email so a reply has a name on it."""
    tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).all()
    emails = {u.id: u.email for u in db.query(User).all()}
    out = []
    for t in tickets:
        row = SupportTicketOut.model_validate(t)
        row.client_email = emails.get(t.user_id)
        row.is_test = is_test_email(row.client_email)
        out.append(row)
    return out

@router.patch("/admin/support/{ticket_id}")
def admin_update_ticket(ticket_id: int, status: str = None, reply: str = None, current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if status:
        ticket.status = status
    if reply:
        msgs = list(ticket.messages or [])
        msgs.append({"from": "admin", "text": reply, "at": datetime.utcnow().isoformat()})
        ticket.messages = msgs
        db.add(Event(user_id=ticket.user_id, event_type="ticket_replied",
                     payload={"ticket_id": ticket.id, "by": current_user.email}))
    db.add(Event(user_id=ticket.user_id, event_type="ticket_updated",
                 payload={"ticket_id": ticket.id, "status": ticket.status,
                          "by": current_user.email}))
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return {"status": "updated", "ticket_id": ticket.id, "ticket_status": ticket.status,
            "messages": ticket.messages or []}

@router.get("/admin/health", response_model=SystemHealth)
def admin_health(current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    """Is the service itself well? No product counts here - see /admin/metrics."""
    return SystemHealth(**metrics_service.system_health(db))

@router.get("/admin/metrics", response_model=MetricsOut)
def admin_metrics(current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    """What the product is doing, grouped by area and counted from real rows."""
    return MetricsOut(**metrics_service.activity(db))
