"""One property campaign costs $49. Stripe Checkout takes the card; this module is the only
place that talks to Stripe.

The credit system this replaces priced a build in invented "campaign credits" that nobody
could buy, so the dashboard advertised a balance it could never fund. A campaign is now a
one-off purchase: POST /api/billing/checkout asks Stripe for a hosted checkout page, and the
webhook marks the order paid. Card data never reaches this app.

No STRIPE_SECRET_KEY means billing is disabled, not silently free: the endpoints answer 503
with a readable reason, and build/launch keep refusing an unpaid campaign.
"""
import hashlib
import hmac
import json
import os
import time

import httpx

STRIPE_API = "https://api.stripe.com/v1"

# $49 per campaign, in the smallest currency unit. Overridable so a promo does not need a
# deploy, but the default is the published price and the tests pin it.
DEFAULT_PRICE_CENTS = 4900
CURRENCY = "usd"


def price_cents() -> int:
    """The price of one campaign in cents. Bad configuration falls back to $49."""
    raw = (os.getenv("STRIPE_PRICE_CENTS") or "").strip()
    if not raw:
        return DEFAULT_PRICE_CENTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PRICE_CENTS
    return value if value > 0 else DEFAULT_PRICE_CENTS


def price_label(cents: int | None = None) -> str:
    cents = price_cents() if cents is None else cents
    return "$%d" % (cents // 100) if cents % 100 == 0 else "$%.2f" % (cents / 100.0)


def secret_key() -> str:
    return (os.getenv("STRIPE_SECRET_KEY") or "").strip()


def publishable_key() -> str:
    return (os.getenv("STRIPE_PUBLISHABLE_KEY") or "").strip()


def webhook_secret() -> str:
    return (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()


def billing_enabled() -> bool:
    """True only when there is a key to charge with — never guess at a live secret."""
    key = secret_key()
    return bool(key) and key.startswith(("sk_", "rk_"))


def _success_url(base: str, boost_id: int) -> str:
    return "%s/?checkout=success&boost=%d" % (base.rstrip("/"), boost_id)


def _cancel_url(base: str, boost_id: int) -> str:
    return "%s/?checkout=cancelled&boost=%d" % (base.rstrip("/"), boost_id)


def checkout_payload(boost_id: int, user_id: int, address: str, base_url: str,
                     cents: int | None = None) -> list:
    """The form-encoded body for POST /v1/checkout/sessions, as a list of pairs.

    A list (not a dict) because Stripe's bracket notation repeats keys; httpx preserves the
    order and repeats, a dict would collapse them.
    """
    cents = price_cents() if cents is None else cents
    name = "Resmara campaign — %s" % (address or "your listing")
    return [
        ("mode", "payment"),
        ("success_url", _success_url(base_url, boost_id)),
        ("cancel_url", _cancel_url(base_url, boost_id)),
        ("client_reference_id", str(boost_id)),
        ("line_items[0][quantity]", "1"),
        ("line_items[0][price_data][currency]", CURRENCY),
        ("line_items[0][price_data][unit_amount]", str(cents)),
        ("line_items[0][price_data][product_data][name]", name[:250]),
        ("metadata[boost_id]", str(boost_id)),
        ("metadata[user_id]", str(user_id)),
        # One campaign, one purchase: the webhook is idempotent on the session id, and this
        # key keeps a double-clicked button from opening two checkout pages for one boost.
        ("payment_intent_data[metadata][boost_id]", str(boost_id)),
    ]


async def create_checkout_session(boost_id: int, user_id: int, address: str, base_url: str,
                                  cents: int | None = None, client: httpx.AsyncClient | None = None) -> dict:
    """Create a Stripe Checkout session and return its JSON (id + url).

    Raises httpx.HTTPStatusError on a refusal so the caller can surface Stripe's own message
    instead of a generic failure.
    """
    if not billing_enabled():
        raise RuntimeError("Stripe is not configured: set STRIPE_SECRET_KEY on the service.")
    data = checkout_payload(boost_id, user_id, address, base_url, cents)
    headers = {"Authorization": "Bearer %s" % secret_key()}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.post("%s/checkout/sessions" % STRIPE_API, data=data, headers=headers)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await client.aclose()


def parse_signature_header(header: str) -> tuple[int, list[str]]:
    """Split a Stripe-Signature header into (timestamp, [v1 signatures])."""
    ts = 0
    sigs: list[str] = []
    for part in (header or "").split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k == "t":
            try:
                ts = int(v.strip())
            except ValueError:
                ts = 0
        elif k == "v1":
            sigs.append(v.strip())
    return ts, sigs


def verify_webhook(payload: bytes, header: str, secret: str, tolerance: int = 300,
                   now: float | None = None) -> bool:
    """True when the payload really came from Stripe.

    Stripe signs the string "{timestamp}.{raw body}" with the endpoint secret. The timestamp
    check stops a captured request being replayed later; comparison is constant time.
    """
    if not secret:
        return False
    ts, sigs = parse_signature_header(header)
    if not ts or not sigs:
        return False
    now = time.time() if now is None else now
    if tolerance and abs(now - ts) > tolerance:
        return False
    signed = b"%d.%s" % (ts, payload)
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def checkout_outcome(event: dict) -> dict:
    """What a webhook event means for us: which order, paid or not.

    Kept pure so the webhook's decision is testable without a database or a network call.
    """
    kind = (event or {}).get("type") or ""
    obj = ((event or {}).get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        paid = (obj.get("payment_status") or "").lower() in ("paid", "no_payment_required")
        return {"event": kind, "session_id": obj.get("id"), "paid": paid,
                "boost_id": _as_int((obj.get("metadata") or {}).get("boost_id")),
                "user_id": _as_int((obj.get("metadata") or {}).get("user_id")),
                "amount_cents": _as_int(obj.get("amount_total")),
                "payment_intent": obj.get("payment_intent")}
    if kind in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        return {"event": kind, "session_id": obj.get("id"), "paid": False,
                "boost_id": _as_int((obj.get("metadata") or {}).get("boost_id")),
                "user_id": _as_int((obj.get("metadata") or {}).get("user_id")),
                "amount_cents": _as_int(obj.get("amount_total")),
                "payment_intent": obj.get("payment_intent")}
    return {"event": kind, "session_id": obj.get("id"), "paid": False, "ignored": True}


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_event(payload: bytes) -> dict:
    """Parse a webhook body, tolerating the odd non-object payload."""
    try:
        data = json.loads(payload.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
