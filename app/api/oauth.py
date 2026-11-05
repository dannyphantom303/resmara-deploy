import os
import hmac
import hashlib
import urllib.parse
from fastapi import APIRouter, Depends, Header, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.db.session import get_db, User, AdAccount
from app.core.security import get_current_user
from app.core.config import settings
import httpx
from datetime import datetime, timedelta

router = APIRouter()

# Permissions asked for at consent time. Meta rejects the whole dialog with "Invalid Scopes"
# if any one of them is not enabled for this app's use cases, so keep the list in .env
# (META_SCOPES, comma separated) and trim it as products are added to the Meta app.
_DEFAULT_SCOPES = [
    "ads_management", "business_management", "pages_read_engagement", "pages_show_list",
    # Publishing: granted once the "Manage everything on your Page" and "Manage messaging &
    # content on Instagram" use cases exist on the app (added 2026-11-05). Ask for nothing
    # the app is not entitled to - one unknown scope fails the entire dialog.
    "pages_manage_posts", "instagram_basic", "instagram_content_publish",
]
META_SCOPES = [s.strip() for s in os.getenv("META_SCOPES", ",".join(_DEFAULT_SCOPES)).split(",") if s.strip()]

def _state_mac(user_id: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{user_id}:meta".encode(), hashlib.sha256).hexdigest()


def _make_state(user_id: int) -> str:
    """Signed state that names the user it was issued for.

    Meta sends the browser back to /meta/callback with no Authorization header, so the
    callback cannot use the bearer dependency. The state carries the user id and is
    HMAC'd with SECRET_KEY; anything not signed here is refused.
    """
    return f"{user_id}:{_state_mac(user_id)}"


def _user_from_state(state: str, db: Session) -> User:
    try:
        uid_s, mac = (state or "").split(":", 1)
        user_id = int(uid_s)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Bad OAuth state")
    if not hmac.compare_digest(_state_mac(user_id), mac):
        raise HTTPException(status_code=400, detail="OAuth state does not match this app")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=400, detail="OAuth state names an unknown account")
    return user


def _back(payload: dict, fmt: str = ""):
    """Return JSON when asked (?format=json), else bounce the browser back to the app."""
    if fmt == "json":
        return payload
    query = urllib.parse.urlencode({k: v for k, v in payload.items() if v is not None})
    return RedirectResponse(f"{settings.PUBLIC_BASE_URL}/?{query}", status_code=302)


@router.get("/meta/connect")
async def meta_connect(current_user: User = Depends(get_current_user)):
    """Initiate Meta OAuth flow. Returns the URL the browser should visit."""
    if not settings.META_CLIENT_ID:
        # Demo mode: simulate OAuth
        return {"demo_mode": True, "message": "Meta credentials not configured. Use /api/oauth/meta/demo-connect to simulate."}

    state = _make_state(current_user.id)
    params = {
        "client_id": settings.META_CLIENT_ID,
        "redirect_uri": settings.META_REDIRECT_URI,
        "scope": ",".join(META_SCOPES),
        "state": state,
        "response_type": "code",
    }
    redirect_url = f"https://www.facebook.com/v19.0/dialog/oauth?{urllib.parse.urlencode(params)}"
    return {"redirect_url": redirect_url, "state": state}

@router.get("/meta/callback")
async def meta_callback(code: str = "", state: str = "", error: str = "",
                        error_description: str = "", format: str = "",
                        db: Session = Depends(get_db)):
    """Handle Meta's redirect back and store the ad account(s).

    Public by design: Meta redirects the browser here, which carries no bearer token, so the
    signed `state` issued by /meta/connect is what identifies the account. Every failure is
    reported to the caller instead of raising a raw 400 mid-redirect.
    """
    if error:
        return _back({"meta": "error", "reason": error_description or error}, format)
    if not settings.META_CLIENT_ID or not settings.META_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Meta credentials not configured")

    current_user = _user_from_state(state, db)

    async with httpx.AsyncClient() as client:
        token_resp = await client.get(
            f"{settings.graph_base}/oauth/access_token",
            params={
                "client_id": settings.META_CLIENT_ID,
                "client_secret": settings.META_CLIENT_SECRET,
                "redirect_uri": settings.META_REDIRECT_URI,
                "code": code,
            },
            timeout=30,
        )
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return _back({"meta": "error", "reason": str(token_data.get("error", token_data))[:180]}, format)

    # The code exchange returns a ~1-2 hour token. Swap it for the long-lived one, or the
    # campaign dies the same afternoon it was connected.
    async with httpx.AsyncClient() as client:
        long_resp = await client.get(
            f"{settings.graph_base}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_CLIENT_ID,
                "client_secret": settings.META_CLIENT_SECRET,
                "fb_exchange_token": access_token,
            },
            timeout=30,
        )
        long_data = long_resp.json()
    if long_data.get("access_token"):
        access_token = long_data["access_token"]
    # Persist the expiry the long-lived swap reports, otherwise nothing downstream can
    # tell a live connection from an expired one (and debug_token is the only witness).
    token_expires_at = None
    if long_data.get("expires_in"):
        token_expires_at = datetime.utcnow() + timedelta(seconds=int(long_data["expires_in"]))

    # Fetch ad accounts
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.graph_base}/me/adaccounts",
            params={"access_token": access_token, "fields": "id,name,currency,account_status"},
            timeout=30,
        )
        accounts_data = resp.json()

    # Page + linked Instagram account, so the Instagram half of a campaign can publish.
    async with httpx.AsyncClient() as client:
        pages_resp = await client.get(
            f"{settings.graph_base}/me/accounts",
            params={"access_token": access_token,
                    "fields": "id,name,instagram_business_account{id,username}"},
            timeout=30,
        )
        pages_data = pages_resp.json()

    pages_raw = [p for p in pages_data.get("data", []) if p.get("id")]

    def _pick_page(account_name: str):
        """Best Page for an ad account: name match, else the first Page with Instagram.

        The ad creative must name a Page (object_story_spec.page_id) and the Instagram
        publisher needs the linked professional account id, so both are resolved once at
        connect time instead of being left empty for the first launch to discover.
        """
        needle = (account_name or "").strip().lower()
        if needle:
            for p in pages_raw:
                pname = (p.get("name") or "").strip().lower()
                if pname and (pname in needle or needle in pname):
                    return p
            # No containment ("Dan D Photography" vs "Daniel Daymude Photography"): score
            # shared significant words and take the best, so the obvious Page still wins.
            words = {w for w in needle.replace("|", " ").split() if len(w) > 2}
            best, best_key = None, (0, 0)
            for p in pages_raw:
                score = len(words & set((p.get("name") or "").lower().split()))
                # Tie-break on a linked Instagram account: that Page can publish, an
                # unlinked one cannot, so it is the better default.
                key = (score, 1 if p.get("instagram_business_account") else 0)
                if key > best_key:
                    best, best_key = p, key
            if best is not None and best_key[0] > 0:
                return best
        for p in pages_raw:
            if p.get("instagram_business_account"):
                return p
        return pages_raw[0] if pages_raw else None

    created = []
    for acct in accounts_data.get("data", []):
        existing = db.query(AdAccount).filter(
            AdAccount.user_id == current_user.id,
            AdAccount.platform == "meta",
            AdAccount.advertiser_id == acct["id"],
        ).first()
        page = _pick_page(acct.get("name", ""))
        page_id_val = page.get("id") if page else None
        ig_id_val = ((page or {}).get("instagram_business_account") or {}).get("id")
        # Meta just accepted this token to list the account and told us its status, so both
        # of those are measured facts we can store now. Spend readiness (payment method) is
        # NOT checked here - it needs a per-account call, so it is left unmeasured and the
        # client's check reports it rather than this silently claiming the account is ready.
        checked_at = datetime.utcnow()
        token_note = "connected just now"
        if token_expires_at:
            token_note = f"connected just now; token expires {token_expires_at.date().isoformat()}"
        if existing:
            existing.access_token = access_token
            existing.is_active = True
            existing.token_expires_at = token_expires_at
            existing.page_id = existing.page_id or page_id_val
            existing.ig_user_id = existing.ig_user_id or ig_id_val
            existing.token_status = "healthy"
            existing.token_checked_at = checked_at
            existing.token_note = token_note
            existing.account_status = acct.get("account_status")
            existing.account_checked_at = checked_at
            db.add(existing)
            db.commit()
            db.refresh(existing)
            created.append(existing)
        else:
            new_acct = AdAccount(
                user_id=current_user.id, platform="meta",
                advertiser_id=acct["id"], account_name=acct.get("name", ""),
                currency=acct.get("currency", "USD"), access_token=access_token,
                budget=5000.0, token_expires_at=token_expires_at,
                page_id=page_id_val, ig_user_id=ig_id_val,
                token_status="healthy", token_checked_at=checked_at, token_note=token_note,
                account_status=acct.get("account_status"), account_checked_at=checked_at,
            )
            db.add(new_acct)
            db.commit()
            db.refresh(new_acct)
            created.append(new_acct)

    pages = [{"id": p.get("id"), "name": p.get("name"),
              "ig_id": (p.get("instagram_business_account") or {}).get("id"),
              "ig_username": (p.get("instagram_business_account") or {}).get("username")}
             for p in pages_data.get("data", [])]

    return _back({
        "meta": "connected" if created else "no_accounts",
        "accounts": len(created),
        "pages": len(pages),
        "ig": next((p["ig_id"] for p in pages if p.get("ig_id")), None),
        "page_id": pages[0]["id"] if pages else None,
        "detail": ", ".join(a.account_name or a.advertiser_id for a in created) or "no ad accounts visible to this login",
    }, format)

def _require_system_token(x_resmara_token: str = Header(default="")):
    """The same shared token as the publisher/report entrypoints: this sweep is system-wide."""
    if not settings.PUBLISH_TOKEN:
        raise HTTPException(status_code=503, detail="RESMARA_PUBLISH_TOKEN is not configured")
    if x_resmara_token != settings.PUBLISH_TOKEN:
        raise HTTPException(status_code=403, detail="Bad system token")


@router.post("/meta/check-all")
async def meta_check_all(x_resmara_token: str = Depends(_require_system_token),
                         db: Session = Depends(get_db)):
    """Check every Meta connection on this install, for every user. Called by the scheduler.

    A customer's long-lived token lasts roughly 60 days. This is the job that refreshes it a
    week before it dies and flips the account to "needs reconnect" the moment Meta stops
    honouring it, so a client hears about a broken connection from their dashboard instead of
    from a campaign that quietly never ran.
    """
    from app.services import token_health
    rows = (db.query(AdAccount)
            .filter(AdAccount.platform == "meta", AdAccount.is_active == True).all())
    checks = [await token_health.refresh_account(a, db) for a in rows]
    reconnect, not_ready, refreshed = [], [], []
    simulated = 0
    for c in checks:
        if c.get("simulated"):
            # A demo connection has no token and bills nobody, so it can never be "not ready
            # to spend" - counting it would bury the real problems in test noise.
            simulated += 1
            continue
        if c.get("token_status") == token_health.STATUS_NEEDS_RECONNECT:
            reconnect.append(c["account"])
        elif not c.get("spend_ok"):
            not_ready.append(c["account"])
        if c.get("refreshed"):
            refreshed.append(c["account"])
    return {"checked": len(checks), "simulated": simulated, "refreshed": refreshed,
            "needs_reconnect": reconnect, "not_ready_to_spend": not_ready, "checks": checks}


@router.post("/meta/demo-connect")
async def meta_demo_connect(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Demo mode: simulate Meta OAuth connection without real credentials."""
    existing = db.query(AdAccount).filter(AdAccount.user_id == current_user.id, AdAccount.platform == "meta").first()
    if existing:
        return {"message": "Already connected", "account": {"id": existing.id, "advertiser_id": existing.advertiser_id, "name": existing.account_name}}
    new_acct = AdAccount(
        user_id=current_user.id, platform="meta",
        advertiser_id="act_demo_12345", account_name="Demo RE Business",
        currency="USD", budget=5000.0, access_token="demo_token",
    )
    db.add(new_acct)
    db.commit()
    db.refresh(new_acct)
    return {"message": "Demo Meta account connected", "account": {"id": new_acct.id, "advertiser_id": new_acct.advertiser_id, "name": new_acct.account_name}}
