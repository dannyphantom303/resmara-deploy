"""Billing endpoints: buy one campaign for $49 (Stripe Checkout), and the webhook that
turns a completed payment into a buildable campaign.

There is no subscription and no credit balance. A campaign is a single purchase, recorded in
`orders` and mirrored on the boost as `paid_at`. Everything that costs us model calls or Meta
spend asks `boost_is_paid()` first.
"""
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.session import get_db, User, Boost, Order, Event
from app.services import billing

router = APIRouter()


def boost_is_paid(boost: Boost, db: Session) -> bool:
    """True when this campaign has been paid for.

    Admins and owners are exempt: the operator has to be able to build a campaign to test
    the product they are selling, and refusing them is how a paid product becomes unusable
    the moment the card on file expires.
    """
    if boost.paid_at:
        return True
    return db.query(Order).filter(Order.boost_id == boost.id, Order.status == "paid").first() is not None


def require_paid(boost: Boost, user: User, db: Session) -> None:
    """Raise the one error the UI knows how to act on when a campaign is unpaid."""
    if getattr(user, "is_admin", False):
        return
    if boost_is_paid(boost, db):
        return
    raise HTTPException(status_code=402, detail={
        "error": "payment_required",
        "message": "This campaign is %s. Buy it to build the posts." % billing.price_label(),
        "price_cents": billing.price_cents(),
        "checkout": "/api/billing/checkout",
        "boost_id": boost.id,
    })


@router.get("/billing/config")
def billing_config():
    """What the UI needs to show a price and a button — no secrets."""
    return {
        "price_cents": billing.price_cents(),
        "price_label": billing.price_label(),
        "currency": billing.CURRENCY,
        "enabled": billing.billing_enabled(),
        "publishable_key": billing.publishable_key(),
        "product": "One property campaign",
    }


class CheckoutRequest(BaseModel):
    boost_id: int


@router.post("/billing/checkout")
async def create_checkout(body: CheckoutRequest, current_user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Start a Stripe Checkout for one campaign and return the hosted URL.

    Reuses a still-open session for the same boost so a double-click cannot create two
    payable pages for one campaign.
    """
    q = db.query(Boost).filter(Boost.id == body.boost_id)
    if not current_user.is_admin:
        q = q.filter(Boost.user_id == current_user.id)
    boost = q.first()
    if not boost:
        raise HTTPException(status_code=404, detail="Boost not found")
    if not billing.billing_enabled():
        raise HTTPException(status_code=503, detail=(
            "Billing is not configured yet: set STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY "
            "on the service."))
    if boost_is_paid(boost, db) and not current_user.is_admin:
        return {"status": "already_paid", "boost_id": boost.id}

    existing = (db.query(Order)
                .filter(Order.boost_id == boost.id, Order.status == "pending",
                        Order.checkout_url.isnot(None))
                .order_by(Order.id.desc()).first())
    if existing:
        return {"status": "pending", "boost_id": boost.id, "url": existing.checkout_url,
                "session_id": existing.stripe_session_id, "price_cents": existing.amount_cents}

    # One Customer per account. This is what makes the saved card appear at Checkout next time
    # instead of an empty card form; the id is ours to remember, the card stays at Stripe.
    customer_id = current_user.stripe_customer_id
    if not customer_id:
        try:
            customer_id = await billing.ensure_customer(
                user_id=current_user.id, email=current_user.email,
                name=current_user.name or "")
        except httpx.HTTPStatusError as e:
            detail = "Stripe refused to create the customer"
            try:
                detail = (e.response.json().get("error") or {}).get("message") or detail
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(status_code=502, detail=detail)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        current_user.stripe_customer_id = customer_id
        db.add(Event(user_id=current_user.id, boost_id=boost.id,
                     event_type="stripe_customer_created",
                     payload={"customer_id": customer_id}))
        db.commit()

    try:
        session = await billing.create_checkout_session(
            boost_id=boost.id, user_id=current_user.id, address=boost.address,
            base_url=settings.PUBLIC_BASE_URL, customer_id=customer_id, save_card=True)
    except httpx.HTTPStatusError as e:
        detail = "Stripe refused the checkout"
        try:
            detail = (e.response.json().get("error") or {}).get("message") or detail
        except Exception:  # noqa: BLE001 - a non-JSON error body still has to surface
            pass
        raise HTTPException(status_code=502, detail=detail)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    order = Order(user_id=current_user.id, boost_id=boost.id,
                  amount_cents=billing.price_cents(), currency=billing.CURRENCY,
                  status="pending", stripe_session_id=session.get("id"),
                  checkout_url=session.get("url"))
    db.add(order)
    db.add(Event(user_id=current_user.id, boost_id=boost.id, event_type="checkout_started",
                 payload={"session_id": session.get("id"), "amount_cents": order.amount_cents}))
    db.commit()
    return {"status": "pending", "boost_id": boost.id, "url": session.get("url"),
            "session_id": session.get("id"), "price_cents": order.amount_cents}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe calls this after a payment. Signature-verified, then idempotent on the session.

    Anonymous by design: Stripe has no account here. The signature is the authentication.
    """
    payload = await request.body()
    header = request.headers.get("stripe-signature", "")
    secret = billing.webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET is not set")
    if not billing.verify_webhook(payload, header, secret):
        raise HTTPException(status_code=400, detail="Bad signature")

    event = billing.load_event(payload)
    outcome = billing.checkout_outcome(event)
    if outcome.get("ignored"):
        return {"received": True, "ignored": outcome["event"]}

    order = None
    if outcome.get("session_id"):
        order = db.query(Order).filter(Order.stripe_session_id == outcome["session_id"]).first()
    boost = db.query(Boost).filter(Boost.id == outcome["boost_id"]).first() if outcome.get("boost_id") else None

    if outcome.get("paid"):
        if not order and boost:
            # The session was created before this deploy, or the row was lost: record it now
            # rather than taking money and leaving the campaign locked.
            order = Order(user_id=outcome.get("user_id") or boost.user_id, boost_id=boost.id,
                          amount_cents=outcome.get("amount_cents") or billing.price_cents(),
                          currency=billing.CURRENCY, status="paid",
                          stripe_session_id=outcome.get("session_id"),
                          stripe_payment_intent=outcome.get("payment_intent"))
            db.add(order)
        if order and order.status != "paid":
            order.status = "paid"
            order.paid_at = datetime.utcnow()
            order.stripe_payment_intent = outcome.get("payment_intent") or order.stripe_payment_intent
        # Belt and braces: if the checkout that paid was created before the account had a
        # customer id, remember the one Stripe actually charged so the next purchase prefills.
        payer = db.query(User).filter(User.id == (order.user_id if order else outcome.get("user_id"))).first()
        if payer is not None and outcome.get("customer") and not payer.stripe_customer_id:
            payer.stripe_customer_id = outcome.get("customer")
        if boost:
            boost.paid_at = datetime.utcnow()
            boost.paid_amount_cents = outcome.get("amount_cents") or billing.price_cents()
        if order:
            db.add(Event(user_id=order.user_id, boost_id=order.boost_id, event_type="campaign_paid",
                         payload={"session_id": outcome.get("session_id"),
                                  "amount_cents": order.amount_cents}))
    elif order and order.status == "pending":
        order.status = "expired" if outcome.get("event") == "checkout.session.expired" else "failed"

    db.commit()
    return {"received": True, "status": order.status if order else "unmatched"}


@router.get("/billing/cards")
async def my_cards(current_user: User = Depends(get_current_user)):
    """The cards Stripe already has for this account, masked. Drives the 'saved card' note."""
    if not billing.billing_enabled():
        return {"enabled": False, "cards": [], "note": "Billing is not configured yet."}
    customer_id = current_user.stripe_customer_id
    if not customer_id:
        return {"enabled": True, "cards": [], "note": "No card saved yet."}
    try:
        cards = await billing.list_cards(customer_id)
    except Exception as exc:  # noqa: BLE001 - a Stripe outage must not break the billing page
        return {"enabled": True, "cards": [], "note": "Could not read saved cards (%s)." %
                type(exc).__name__}
    return {
        "enabled": True,
        "cards": cards,
        "note": ("Your card is saved - checkout will offer it." if cards
                 else "No card saved yet."),
    }


@router.get("/billing/orders")
def my_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """This account's purchases, newest first — the receipts list behind the Billing page."""
    q = db.query(Order)
    if not current_user.is_admin:
        q = q.filter(Order.user_id == current_user.id)
    rows = q.order_by(Order.id.desc()).limit(50).all()
    addresses = {b.id: b.address for b in db.query(Boost).filter(
        Boost.id.in_([o.boost_id for o in rows if o.boost_id])).all()} if rows else {}
    return [{
        "id": o.id, "boost_id": o.boost_id,
        "address": addresses.get(o.boost_id), "status": o.status,
        "amount_cents": o.amount_cents, "amount_label": billing.price_label(o.amount_cents or 0),
        "currency": o.currency, "session_id": o.stripe_session_id,
        "created_at": o.created_at, "paid_at": o.paid_at,
    } for o in rows]


@router.get("/billing/boost/{boost_id}")
def boost_billing(boost_id: int, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Whether this campaign is paid for, and its latest order — what the review screen asks."""
    q = db.query(Boost).filter(Boost.id == boost_id)
    if not current_user.is_admin:
        q = q.filter(Boost.user_id == current_user.id)
    boost = q.first()
    if not boost:
        raise HTTPException(status_code=404, detail="Boost not found")
    order = (db.query(Order).filter(Order.boost_id == boost.id)
             .order_by(Order.id.desc()).first())
    return {
        "boost_id": boost.id,
        "paid": bool(boost.paid_at) or (order is not None and order.status == "paid"),
        "exempt": bool(current_user.is_admin),
        "price_cents": billing.price_cents(),
        "price_label": billing.price_label(),
        "order": None if not order else {
            "id": order.id, "status": order.status, "amount_cents": order.amount_cents,
            "checkout_url": order.checkout_url, "paid_at": order.paid_at,
        },
    }
