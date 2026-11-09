"""Hermetic tests for the $49-per-campaign billing that replaced the credit system.

Nothing here touches Stripe: the request body, the signature check and the webhook's decision
are all pure functions, so the parts that would cost money are pinned without a network call.

Run:  cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_billing.py
"""
import hashlib
import hmac
import json
import os
import sys
import time

os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.session import SessionLocal, User, Boost, Order  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.services import billing  # noqa: E402

PASSED = 0
FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  [PASS] %s" % label)
    else:
        FAILED += 1
        print("  [FAIL] %s  %s" % (label, detail))


def sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), b"%d.%s" % (ts, payload), hashlib.sha256).hexdigest()
    return "t=%d,v1=%s" % (ts, mac)


def main():
    global PASSED, FAILED
    client = TestClient(app)

    print("[price]")
    os.environ.pop("STRIPE_PRICE_CENTS", None)
    check("one campaign is $49", billing.price_cents() == 4900, billing.price_cents())
    check("and reads as $49", billing.price_label() == "$49", billing.price_label())
    os.environ["STRIPE_PRICE_CENTS"] = "3900"
    check("a promo price is honoured", billing.price_cents() == 3900 and billing.price_label() == "$39")
    os.environ["STRIPE_PRICE_CENTS"] = "not-a-number"
    check("junk config falls back to $49", billing.price_cents() == 4900)
    os.environ.pop("STRIPE_PRICE_CENTS", None)

    print("\n[checkout payload]")
    body = dict(billing.checkout_payload(7, 3, "1248 Oakridge Drive", "https://resmara.com"))
    check("charges 4900 cents", body["line_items[0][price_data][unit_amount]"] == "4900")
    check("one item, quantity one", body["line_items[0][quantity]"] == "1")
    check("mode is payment, not subscription", body["mode"] == "payment")
    check("carries the boost id", body["metadata[boost_id]"] == "7")
    check("carries the user id", body["metadata[user_id]"] == "3")
    check("returns to the app with the boost",
          "checkout=success" in body["success_url"] and "boost=7" in body["success_url"],
          body["success_url"])
    check("names the property on the Stripe page", "1248 Oakridge Drive" in body["line_items[0][price_data][product_data][name]"])

    print("\n[webhook signature]")
    payload = json.dumps({"type": "checkout.session.completed"}).encode()
    good = sign(payload, "whsec_test")
    check("a correctly signed body verifies", billing.verify_webhook(payload, good, "whsec_test") is True)
    check("another secret does not", billing.verify_webhook(payload, good, "whsec_other") is False)
    check("a tampered body does not",
          billing.verify_webhook(payload.replace(b"completed", b"expired"), good, "whsec_test") is False)
    stale = sign(payload, "whsec_test", ts=int(time.time()) - 3600)
    check("a replayed old timestamp does not",
          billing.verify_webhook(payload, stale, "whsec_test") is False)
    check("a missing header does not", billing.verify_webhook(payload, "", "whsec_test") is False)
    check("no configured secret never verifies", billing.verify_webhook(payload, good, "") is False)

    print("\n[webhook meaning]")
    paid_event = {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_test_123", "payment_status": "paid", "amount_total": 4900,
        "payment_intent": "pi_123", "metadata": {"boost_id": "11", "user_id": "4"}}}}
    out = billing.checkout_outcome(paid_event)
    check("a paid session is paid", out["paid"] is True)
    check("it carries the session, boost and amount",
          (out["session_id"], out["boost_id"], out["amount_cents"]) == ("cs_test_123", 11, 4900), out)
    unpaid = {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_9", "payment_status": "unpaid", "metadata": {}}}}
    check("a completed-but-unpaid session is not paid", billing.checkout_outcome(unpaid)["paid"] is False)
    expired = {"type": "checkout.session.expired", "data": {"object": {"id": "cs_9", "metadata": {}}}}
    check("an expired session is not paid", billing.checkout_outcome(expired)["paid"] is False)
    other = {"type": "customer.created", "data": {"object": {"id": "cus_1"}}}
    check("unrelated events are ignored", billing.checkout_outcome(other).get("ignored") is True)

    print("\n[endpoints]")
    cfg = client.get("/api/billing/config")
    check("config answers without a login", cfg.status_code == 200, cfg.text[:120])
    check("config advertises $49", cfg.json()["price_cents"] == 4900 and cfg.json()["price_label"] == "$49")
    check("config says billing is off with no key", cfg.json()["enabled"] is False)
    check("config leaks no secret", "secret" not in json.dumps(cfg.json()).lower(), cfg.text[:200])

    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_(["pay-test@example.com", "pay-admin@example.com"])).delete()
        db.commit()
        buyer = User(email="pay-test@example.com", hashed_password=get_password_hash("Hunter2Hunter2"),
                     name="Buyer", is_active=True, is_admin=False)
        admin = User(email="pay-admin@example.com", hashed_password=get_password_hash("Hunter2Hunter2"),
                     name="Owner", is_active=True, is_admin=True)
        db.add_all([buyer, admin])
        db.commit()
        boost = Boost(user_id=buyer.id, address="9 Unpaid Way")
        db.add(boost)
        db.commit()
        boost_id, buyer_id = boost.id, buyer.id
    finally:
        db.close()

    tok = client.post("/api/auth/login", data={"username": "pay-test@example.com",
                                               "password": "Hunter2Hunter2"}).json()["access_token"]
    auth = {"Authorization": "Bearer %s" % tok}

    state = client.get("/api/billing/boost/%d" % boost_id, headers=auth)
    check("the campaign reports unpaid", state.status_code == 200 and state.json()["paid"] is False,
          state.text[:160])
    check("and quotes the price", state.json()["price_label"] == "$49")

    build = client.post("/api/boosts/%d/build" % boost_id, json={"force": True}, headers=auth)
    check("an unpaid campaign cannot build", build.status_code == 402, "%s %s" % (build.status_code, build.text[:160]))
    check("the refusal is machine-readable",
          build.json().get("detail", {}).get("error") == "payment_required", build.text[:200])

    launch = client.post("/api/boosts/%d/launch" % boost_id, json={}, headers=auth)
    check("an unpaid campaign cannot launch", launch.status_code == 402, launch.status_code)

    checkout = client.post("/api/billing/checkout", json={"boost_id": boost_id}, headers=auth)
    check("checkout says billing is unconfigured rather than pretending",
          checkout.status_code == 503 and "STRIPE_SECRET_KEY" in checkout.text, checkout.text[:200])

    # The webhook is the only thing that marks a campaign paid.
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    db = SessionLocal()
    try:
        db.add(Order(user_id=buyer_id, boost_id=boost_id, amount_cents=4900, currency="usd",
                     status="pending", stripe_session_id="cs_test_ABC"))
        db.commit()
    finally:
        db.close()

    event = json.dumps({"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_test_ABC", "payment_status": "paid", "amount_total": 4900,
        "payment_intent": "pi_ABC",
        "metadata": {"boost_id": str(boost_id), "user_id": str(buyer_id)}}}}).encode()
    bad = client.post("/api/billing/webhook", content=event,
                      headers={"stripe-signature": sign(event, "whsec_wrong")})
    check("a forged webhook is refused", bad.status_code == 400, bad.status_code)

    ok = client.post("/api/billing/webhook", content=event,
                     headers={"stripe-signature": sign(event, "whsec_test")})
    check("a genuine webhook is accepted", ok.status_code == 200, ok.text[:160])

    state = client.get("/api/billing/boost/%d" % boost_id, headers=auth)
    check("the campaign is now paid", state.json()["paid"] is True, state.text[:200])
    check("its latest order is paid", (state.json()["order"] or {}).get("status") == "paid", state.text[:200])

    # Ask the gate itself rather than starting a real engine run in the test process.
    from app.api.billing import require_paid
    db = SessionLocal()
    try:
        paid_boost = db.query(Boost).filter(Boost.id == boost_id).first()
        paid_user = db.query(User).filter(User.email == "pay-test@example.com").first()
        require_paid(paid_boost, paid_user, db)
        check("a paid campaign may build", True)
    except Exception as e:  # noqa: BLE001 - the test asserts the gate opens
        check("a paid campaign may build", False, repr(e))
    finally:
        db.close()

    orders = client.get("/api/billing/orders", headers=auth)
    check("the receipt is listed", orders.status_code == 200 and orders.json()[0]["status"] == "paid",
          orders.text[:160])
    check("the receipt is labelled in dollars", orders.json()[0]["amount_label"] == "$49", orders.text[:160])

    replay = client.post("/api/billing/webhook", content=event,
                         headers={"stripe-signature": sign(event, "whsec_test")})
    check("a replayed webhook is idempotent", replay.status_code == 200, replay.text[:120])
    db = SessionLocal()
    try:
        paid_rows = db.query(Order).filter(Order.boost_id == boost_id, Order.status == "paid").count()
        check("and does not create a second paid order", paid_rows == 1, paid_rows)
    finally:
        db.close()

    print("\n[cleanup]")
    os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
    db = SessionLocal()
    try:
        db.query(Order).filter(Order.boost_id == boost_id).delete()
        db.query(Boost).filter(Boost.id == boost_id).delete()
        db.query(User).filter(User.email.in_(["pay-test@example.com", "pay-admin@example.com"])).delete()
        db.commit()
        print("  cleaned test rows")
    finally:
        db.close()

    print("\n" + "=" * 60)
    print("%d passed, %d failed" % (PASSED, FAILED))
    if FAILED:
        print("BILLING TESTS FAILED")
        sys.exit(1)
    print("ALL BILLING TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
