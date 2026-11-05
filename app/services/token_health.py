"""Token and ad-account health for a client-billed Meta connection.

In the client-billed model the customer's own ad account is the advertiser: their card
pays Meta and our access is a token they granted. That makes two things our problem which
a simulated connection can never show:

* **the token's lifetime.** A long-lived user token dies after roughly 60 days. When it
  dies, every launch fails with Meta's "Invalid OAuth access token" and the customer sees a
  product that stopped working for no visible reason.
* **whether the account can actually spend.** If the customer never put a payment method on
  the ad account, a campaign we create will sit PAUSED forever while they wait for results
  and blame us.

So before a launch we ask Meta both questions and, when the answer is "no", we say so using
Meta's own wording - and refuse the launch instead of creating a campaign that can never run.
Nothing here is ever invented: if Meta cannot be reached, the account is reported `unknown`
with the reason and the caller is told the same thing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.crypto import TokenDecryptError
from app.db.session import AdAccount

log = logging.getLogger("resmara.token_health")

GRAPH_TIMEOUT = 30

# How close to expiry a token is refreshed. A week is comfortably longer than the gap
# between two launches, so an account in use never actually reaches expiry.
REFRESH_WITHIN_DAYS = 7

STATUS_HEALTHY = "healthy"
STATUS_EXPIRING = "expiring"
STATUS_NEEDS_RECONNECT = "needs_reconnect"
STATUS_SIMULATED = "simulated"
STATUS_UNKNOWN = "unknown"
STATUS_ACCOUNT_NOT_READY = "account_not_ready"

# Meta's own enums, verbatim from the Marketing API Ad Account reference. The point of
# keeping them here is that a refusal can name the real reason ("RISK_PAYMENT") instead of
# a generic "the ad account is not active".
ACCOUNT_STATUS = {
    1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING_RISK_REVIEW",
    8: "PENDING_SETTLEMENT", 9: "IN_GRACE_PERIOD", 100: "PENDING_CLOSURE",
    101: "CLOSED", 201: "ANY_ACTIVE", 202: "ANY_CLOSED",
}
DISABLE_REASON = {
    0: "NONE", 1: "ADS_INTEGRITY_POLICY", 2: "ADS_IP_REVIEW", 3: "RISK_PAYMENT",
    4: "GRAY_ACCOUNT_SHUT_DOWN", 5: "ADS_AFC_REVIEW", 6: "BUSINESS_INTEGRITY_RAR",
    7: "PERMANENT_CLOSE", 8: "UNUSED_RESELLER_ACCOUNT", 9: "UNUSED_ACCOUNT",
    10: "UMBRELLA_AD_ACCOUNT", 11: "BUSINESS_MANAGER_INTEGRITY_POLICY",
    12: "MISREPRESENTED_AD_ACCOUNT", 13: "AOAB_DESHARE_LEGAL_ENTITY",
    14: "CTX_THREAD_REVIEW", 15: "COMPROMISED_AD_ACCOUNT",
}


# --------------------------------------------------------------------------- helpers
def _base(base_url: Optional[str] = None) -> str:
    return base_url or settings.graph_base


def _app_token() -> str:
    """`app_id|app_secret`, the form Graph wants to inspect a user token with."""
    return f"{settings.META_CLIENT_ID}|{settings.META_CLIENT_SECRET}"


def _safe_json(resp: httpx.Response) -> Dict[str, Any]:
    try:
        body = resp.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _meta_message(error: Any) -> str:
    """Meta's most useful sentence about an error, with its subcode when it has one."""
    if not isinstance(error, dict):
        return str(error or "")[:300]
    parts = [error.get("message") or ""]
    if error.get("error_user_msg"):
        parts.append(str(error["error_user_msg"]))
    text = " - ".join(p for p in parts if p)
    if error.get("error_subcode"):
        text = f"{text} (subcode {error['error_subcode']})" if text else f"subcode {error['error_subcode']}"
    return text.strip()[:400]


def account_status_label(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    return ACCOUNT_STATUS.get(int(value), f"UNKNOWN({value})")


def disable_reason_label(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    label = DISABLE_REASON.get(int(value))
    return label if label and label != "NONE" else None


def act_id(advertiser_id: str) -> str:
    """`act_<digits>` exactly once, whether or not the stored id already carries the prefix."""
    raw = (advertiser_id or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def is_simulated(acct) -> bool:
    """Reuse the platform client's own notion of a simulated account, never a second one."""
    from app.services.ad_platforms import is_simulated_account
    try:
        return bool(is_simulated_account(acct))
    except TokenDecryptError:
        # An unreadable token is a real (broken) connection, not a prototype.
        return False


# --------------------------------------------------------------------------- checks
async def inspect_token(acct, *, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Ask Graph about the token itself: valid? when does it die? which app? which scopes?"""
    out: Dict[str, Any] = {"status": STATUS_UNKNOWN, "ok": False, "note": ""}

    if not settings.META_CLIENT_ID or not settings.META_CLIENT_SECRET:
        out["note"] = ("Meta app credentials are not configured, so the token cannot be "
                       "verified (set META_CLIENT_ID and META_CLIENT_SECRET)")
        return out

    try:
        token = acct.access_token or ""
    except TokenDecryptError as exc:
        out.update(status=STATUS_NEEDS_RECONNECT, note=str(exc))
        return out
    if not token:
        out.update(status=STATUS_NEEDS_RECONNECT, note="no Meta token is stored for this ad account")
        return out

    async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
        resp = await client.get(f"{_base(base_url)}/debug_token",
                                params={"input_token": token, "access_token": _app_token()})
    body = _safe_json(resp)
    if body.get("error"):
        out.update(status=STATUS_NEEDS_RECONNECT,
                   note=_meta_message(body["error"]) or "Meta refused to verify this token")
        return out

    data = body.get("data") or {}
    if not data:
        out["note"] = "Meta returned no token details"
        return out

    expires = int(data.get("expires_at") or 0)
    days_left = None
    if expires:
        days_left = round((datetime.utcfromtimestamp(expires) - datetime.utcnow()).total_seconds() / 86400, 1)
    scopes = data.get("scopes") or []
    app_id = str(data.get("app_id") or "")

    out.update(valid=bool(data.get("is_valid")),
               expires_at=datetime.utcfromtimestamp(expires) if expires else None,
               days_left=days_left, scopes=scopes, app_id=app_id, type=data.get("type"))

    can_manage_ads = "ads_management" in scopes
    if not data.get("is_valid"):
        out.update(status=STATUS_NEEDS_RECONNECT,
                   note="Meta reports this token as invalid - reconnect the Meta account")
    elif settings.META_CLIENT_ID and app_id and app_id != settings.META_CLIENT_ID:
        out.update(status=STATUS_NEEDS_RECONNECT,
                   note=(f"this token belongs to Meta app {app_id}, not to this app "
                         f"({settings.META_CLIENT_ID}) - reconnect through this app"))
    elif not can_manage_ads:
        out.update(status=STATUS_NEEDS_RECONNECT,
                   note=("this token is missing ads_management, so campaigns cannot be managed - "
                         "reconnect and grant ads management"))
    elif days_left is not None and days_left <= REFRESH_WITHIN_DAYS:
        out.update(status=STATUS_EXPIRING,
                   note=f"token expires in {days_left} days - it is refreshed on every check "
                        "while it is still valid")
    else:
        out.update(status=STATUS_HEALTHY)
    out["ok"] = out["status"] in (STATUS_HEALTHY, STATUS_EXPIRING)
    return out


async def extend_token(acct, *, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Swap a still-valid token for a fresh long-lived one, buying another ~60 days.

    This is Meta's documented refresh for long-lived user tokens: re-run the
    `fb_exchange_token` grant with the token you already hold. It only works while the
    token is still valid, which is why the refresh happens a week early rather than on the
    day it dies - a dead token has to be reconnected by a human.
    """
    try:
        token = acct.access_token or ""
    except TokenDecryptError as exc:
        return {"ok": False, "note": str(exc)}
    if not token:
        return {"ok": False, "note": "no Meta token is stored for this ad account"}
    if not settings.META_CLIENT_ID or not settings.META_CLIENT_SECRET:
        return {"ok": False, "note": "Meta app credentials are not configured"}

    async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
        resp = await client.get(f"{_base(base_url)}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.META_CLIENT_ID,
            "client_secret": settings.META_CLIENT_SECRET,
            "fb_exchange_token": token,
        })
    body = _safe_json(resp)
    if body.get("error"):
        return {"ok": False, "note": _meta_message(body["error"])}
    new_token = body.get("access_token")
    if not new_token:
        return {"ok": False, "note": "Meta returned no token when refreshing"}

    expires_in = int(body.get("expires_in") or 0)
    return {
        "ok": True,
        "access_token": new_token,
        "expires_in": expires_in,
        "expires_at": (datetime.utcnow() + timedelta(seconds=expires_in)) if expires_in else None,
    }


async def spend_readiness(acct, *, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Can this ad account actually spend? Answers from Meta's own fields, never a guess.

    The payment method is reported in two states on purpose. `no_funding` means Meta
    returned the field and it was empty - the customer has no card on the account, so a
    campaign cannot run. `None` means Meta did not return the field at all, which is
    "unknown", not "missing card": an account is never accused of having no payment method
    on the strength of a field the API chose not to send.
    """
    out: Dict[str, Any] = {"ok": False, "status": STATUS_UNKNOWN, "note": "", "account_status": None,
                           "account_status_label": None, "disable_reason": None,
                           "disable_reason_label": None, "funding": None, "funding_note": ""}
    try:
        token = acct.access_token or ""
    except TokenDecryptError as exc:
        out["note"] = str(exc)
        return out
    if not token:
        out["note"] = "no Meta token is stored for this ad account"
        return out

    fields = "name,account_status,disable_reason,funding_source_details,currency,is_prepay_account"
    async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
        resp = await client.get(f"{_base(base_url)}/{act_id(acct.advertiser_id)}",
                                params={"fields": fields, "access_token": token})
    body = _safe_json(resp)
    if body.get("error"):
        out["note"] = _meta_message(body["error"]) or "Meta refused to read this ad account"
        return out

    status = body.get("account_status")
    out["account_status"] = status
    out["account_status_label"] = account_status_label(status)
    reason = body.get("disable_reason")
    out["disable_reason"] = reason
    out["disable_reason_label"] = disable_reason_label(reason)

    if "funding_source_details" in body:
        details = body.get("funding_source_details") or {}
        if details:
            out["funding"] = "has_funding"
            out["funding_note"] = details.get("display_string") or details.get("type") or "payment method on file"
        else:
            out["funding"] = "no_funding"
            out["funding_note"] = ("no payment method on this ad account - in a client-billed "
                                   "connection the client's own card must fund it")
    else:
        out["funding_note"] = "Meta did not return the payment method for this ad account"

    spendable = status in (1, 201)
    out["ok"] = bool(spendable and out["funding"] != "no_funding")
    reasons = []
    if not spendable:
        label = out["account_status_label"] or f"status {status}"
        if out["disable_reason_label"]:
            label += f" ({out['disable_reason_label']})"
        reasons.append(f"ad account is not active: {label}")
    if out["funding"] == "no_funding":
        reasons.append(out["funding_note"])
    out["status"] = STATUS_HEALTHY if out["ok"] else STATUS_ACCOUNT_NOT_READY
    out["note"] = "; ".join(reasons) if reasons else (
        f"ad account {out['account_status_label']} with funding on file")
    log.info("ad account %s readiness: %s (%s)", act_id(acct.advertiser_id), out["status"], out["note"])
    return out


def _should_refresh(ad_account, info: Dict[str, Any], min_days: int) -> bool:
    """Worth re-exchanging only when the token is close to dying - and at most once a day.

    Refreshing on every sweep would churn tokens and burn call quota, and a token Meta will
    not extend must not become an hourly retry loop.
    """
    if not info.get("valid") or info.get("days_left") is None:
        return False
    if info["days_left"] > min_days:
        return False
    last = getattr(ad_account, "token_refreshed_at", None)
    if last is not None:
        if last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        if (datetime.utcnow() - last) < timedelta(hours=24):
            return False
    return True


async def refresh_account(ad_account: AdAccount, db, *, base_url: Optional[str] = None,
                          min_days: int = REFRESH_WITHIN_DAYS) -> Dict[str, Any]:
    """Check one account: inspect the token, extend it if it is close to dying, check
    whether the account can spend, and persist every answer.

    Returns a JSON-safe summary. A simulated account short-circuits: it has no token and no
    network path, and saying so is more useful than a fabricated "healthy".
    """
    if is_simulated(ad_account):
        now = datetime.utcnow()
        ad_account.token_status = STATUS_SIMULATED
        ad_account.token_checked_at = now
        ad_account.token_note = "simulated connection: no Meta token, nothing is billed"
        ad_account.funding_status = None
        ad_account.funding_note = "simulated account: nothing is billed"
        ad_account.account_status = None
        ad_account.account_checked_at = now
        db.add(ad_account)
        db.commit()
        return {"ok": True, "simulated": True, "status": STATUS_SIMULATED, "token_status": STATUS_SIMULATED,
                "token_note": ad_account.token_note, "account": ad_account.account_name or ad_account.advertiser_id}

    info = await inspect_token(ad_account, base_url=base_url)
    refreshed = None
    if _should_refresh(ad_account, info, min_days):
        before = info.get("expires_at")
        refreshed = await extend_token(ad_account, base_url=base_url)
        ad_account.token_refreshed_at = datetime.utcnow()
        if refreshed.get("ok"):
            ad_account.access_token = refreshed["access_token"]
            if refreshed.get("expires_at"):
                ad_account.token_expires_at = refreshed["expires_at"]
            db.add(ad_account)
            db.commit()
            info = await inspect_token(ad_account, base_url=base_url)
            info["refreshed"] = True
            after = info.get("expires_at")
            # Meta does not always hand back more time: for a long-lived token the exchange
            # returns a NEW token that still expires when the old one did. Report that
            # honestly rather than claiming a refresh that bought the client nothing - the
            # whole point of this check is that the connection does not die unnoticed.
            if before and after and after <= before + timedelta(days=1):
                info["extended"] = False
                info["refresh_note"] = (
                    f"Meta renewed the token but kept the same expiry ({after.date()}), so this "
                    "connection still stops working unless it is reconnected before then")
            else:
                info["extended"] = True
        else:
            # Do not fail the whole check over a failed refresh: the old token still works
            # until it expires, and the note tells the operator what happened.
            info["refreshed"] = False
            info["refresh_note"] = refreshed.get("note") or "Meta rejected the refresh"
        if info.get("extended") is False:
            # Surface it where a person will actually see it, not only in the job log.
            info["note"] = ((info.get("note") or "") + " " + info["refresh_note"]).strip()

    ready = None
    if info["status"] != STATUS_NEEDS_RECONNECT:
        ready = await spend_readiness(ad_account, base_url=base_url)

    ad_account.token_status = info["status"]
    ad_account.token_checked_at = datetime.utcnow()
    ad_account.token_note = info.get("note") or ""
    ad_account.token_refresh_note = info.get("refresh_note") or ""
    if info.get("expires_at"):
        ad_account.token_expires_at = info["expires_at"]
    if ready is not None:
        ad_account.funding_status = ready.get("funding")
        ad_account.funding_note = ready.get("funding_note") or ""
        ad_account.account_status = ready.get("account_status")
        ad_account.account_checked_at = datetime.utcnow()
    db.add(ad_account)
    db.commit()

    return {
        "ok": bool(info["status"] != STATUS_NEEDS_RECONNECT and (ready is None or ready["ok"])),
        "simulated": False,
        "status": info["status"] if info["status"] == STATUS_NEEDS_RECONNECT else (ready or {}).get("status", info["status"]),
        "token_status": info["status"],
        "token_note": info.get("note") or "",
        "expires_at": info.get("expires_at"),
        "days_left": info.get("days_left"),
        "scopes": info.get("scopes") or [],
        "refreshed": bool(info.get("refreshed")),
        "extended": info.get("extended"),
        "refresh_note": info.get("refresh_note"),
        "token_refreshed_at": ad_account.token_refreshed_at,
        "account_status": (ready or {}).get("account_status"),
        "account_status_label": (ready or {}).get("account_status_label"),
        "disable_reason_label": (ready or {}).get("disable_reason_label"),
        "funding": (ready or {}).get("funding"),
        "funding_note": (ready or {}).get("funding_note") or "",
        "spend_ok": bool((ready or {}).get("ok")),
        "spend_note": (ready or {}).get("note") or "",
        "account": ad_account.account_name or ad_account.advertiser_id,
    }


async def ensure_ready(ad_account: AdAccount, db, *, base_url: Optional[str] = None) -> Dict[str, Any]:
    """The pre-launch question: may we spend this customer's money right now?

    Deliberately a fresh check rather than a cached status - a launch is exactly the moment
    it matters, and it is one cheap Graph round trip. A simulated account passes, because
    that path never touches Meta or a wallet.
    """
    summary = await refresh_account(ad_account, db, base_url=base_url)
    if summary["status"] == STATUS_SIMULATED:
        return {"ok": True, "status": STATUS_SIMULATED, "needs": [],
                "detail": "simulated ad account - nothing is billed", "summary": summary}
    if summary["token_status"] == STATUS_NEEDS_RECONNECT:
        return {"ok": False, "status": STATUS_NEEDS_RECONNECT, "needs": ["reconnect Meta"],
                "detail": summary.get("token_note") or "the Meta token for this ad account is no longer usable",
                "summary": summary}
    if not summary.get("spend_ok"):
        return {"ok": False, "status": STATUS_ACCOUNT_NOT_READY, "needs": ["ad account ready to spend"],
                "detail": summary.get("spend_note") or "the ad account is not ready to spend",
                "summary": summary}
    return {"ok": True, "status": "ready", "needs": [],
            "detail": "token is valid and the ad account can spend", "summary": summary}


def classify_graph_error(body: Any, status_code: Optional[int] = None) -> Optional[Dict[str, str]]:
    """Turn a Graph error into the one thing a human has to do about it.

    A launch used to surface Meta's bare sentence: "Invalid OAuth access token" for a dead
    token, "Permissions error" for a missing scope. Neither tells an operator whether to
    reconnect, re-grant, or simply wait, so both are classified here.
    """
    if not isinstance(body, dict):
        return None
    error = body.get("error") or {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    detail = _meta_message(error)
    if code in (190, 102) or subcode in (458, 459, 460, 463, 467):
        return {"kind": STATUS_NEEDS_RECONNECT, "detail": detail or "the Meta token is no longer valid"}
    if code in (200, 10, 272, 273):
        return {"kind": "permission_denied", "detail": detail or "the connected login lacks an ads permission"}
    if code in (4, 17, 32, 613):
        return {"kind": "rate_limited", "detail": detail or "Meta rate limit reached"}
    return None
