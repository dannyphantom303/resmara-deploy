"""A returning customer must not retype the card.

Stripe keeps the card on a Customer; we keep the Customer id. The pieces that can go wrong are
pure: the Checkout body must carry the customer and `setup_future_usage`, and the saved-card
summary must never be more than a masked line. Both are pinned here against a fake Stripe so no
network or money is involved.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["STRIPE_SECRET_KEY"] = "sk_test_savedcards"
os.environ.pop("STRIPE_PRICE_CENTS", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import billing  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


class Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %s" % self.status_code)


class FakeStripe:
    """Stands in for httpx.AsyncClient: records the request, answers like Stripe."""

    def __init__(self, cards=()):
        self.cards = list(cards)
        self.calls = []

    async def post(self, url, content=None, headers=None, data=None):
        self.calls.append(("POST", url, content if content is not None else data, headers))
        return Resp({"id": "cus_test_123"})

    async def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params, headers))
        return Resp({"data": [{"id": "pm_1", "card": c} for c in self.cards]})

    async def aclose(self):
        return None


def main():
    # --- the Checkout body ------------------------------------------------------------
    plain = billing.checkout_payload(7, 3, "1 Test Ln", "https://example.test", 4900)
    check("without a customer the body is unchanged",
          not any(k in ("customer",) for k, _ in plain) and
          "payment_intent_data[setup_future_usage]" not in dict(plain).keys())

    saved = billing.checkout_payload(7, 3, "1 Test Ln", "https://example.test", 4900,
                                     customer_id="cus_test_123")
    d = dict(saved)
    check("the session is charged to the customer", d.get("customer") == "cus_test_123")
    check("the card is kept for next time",
          d.get("payment_intent_data[setup_future_usage]") == "off_session")
    check("the billing address follows the customer",
          d.get("customer_update[address]") == "auto")
    check("the boost is still named in the metadata", d.get("metadata[boost_id]") == "7")
    check("a one-off payment is still one item", d.get("line_items[0][price_data][unit_amount]") == "4900")

    no_save = dict(billing.checkout_payload(7, 3, "1 Test Ln", "https://x.test", customer_id="cus_1",
                                            save_card=False))
    check("saving can be turned off explicitly",
          "payment_intent_data[setup_future_usage]" not in no_save)

    # --- the body must survive httpx's async path ------------------------------------
    # httpx 0.28's AsyncClient rejects `data=<list of pairs>` ("Attempted to send an sync request
    # with an AsyncClient instance"), which made every hosted checkout answer 503. The body is
    # encoded by hand now; repeated keys must survive that.
    body, headers = billing.form_body([("a", "1"), ("a", "2"), ("brackets[x]", "3")])
    encoded = body.decode()
    check("the body is url-encoded, not sent as data=", isinstance(body, bytes), type(body).__name__)
    check("repeated keys are kept", encoded.count("a=") == 2, encoded)
    check("bracket keys are encoded once", "brackets%5Bx%5D=3" in encoded, encoded)
    check("the form content type is set",
          headers.get("Content-Type") == "application/x-www-form-urlencoded", str(headers))
    check("the secret key stays in the header, not the body", "sk_test" not in encoded, encoded[:60])

    # --- the customer is created once ------------------------------------------------
    import asyncio
    fake = FakeStripe()
    cid = asyncio.run(billing.ensure_customer(9, "agent@example.com", "Dana", client=fake))
    check("a Stripe customer is created", cid == "cus_test_123", cid)
    method, url, body, headers = fake.calls[0]
    form = body.decode() if isinstance(body, bytes) else str(body)
    check("against /v1/customers", url.endswith("/v1/customers"), url)
    check("with the account's email", "email=agent%40example.com" in form, form[:120])
    check("and our user id in metadata", "metadata%5Buser_id%5D=9" in form, form[:120])
    check("authenticated with the secret key", headers["Authorization"].startswith("Bearer sk_"))

    # --- what the page is allowed to show -------------------------------------------
    fake = FakeStripe(cards=[{"brand": "visa", "last4": "4242", "exp_month": 4, "exp_year": 2029}])
    cards = asyncio.run(billing.list_cards("cus_test_123", client=fake))
    check("one saved card is reported", len(cards) == 1, str(cards))
    check("as a masked label", cards[0]["label"] == "Visa •••• 4242, expires 04/2029",
          cards[0]["label"])
    check("with nothing that could be charged",
          set(cards[0]) == {"id", "brand", "last4", "exp_month", "exp_year", "label"}, str(cards[0]))
    check("the lookup is scoped to the customer",
          fake.calls[0][2].get("customer") == "cus_test_123", str(fake.calls[0][2]))

    # --- and the endpoint refuses strangers -----------------------------------------
    client = TestClient(app)
    anon = client.get("/api/billing/cards")
    check("saved cards need a sign-in", anon.status_code == 401, str(anon.status_code))

    # --- the webhook carries the customer through -----------------------------------
    outcome = billing.checkout_outcome({
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "payment_status": "paid", "amount_total": 4900,
                            "customer": "cus_test_123", "metadata": {"boost_id": "7", "user_id": "3"}}},
    })
    check("a paid session reports its customer", outcome.get("customer") == "cus_test_123", str(outcome))

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        raise SystemExit(1)
    print("ALL SAVED CARD TESTS PASSED")


if __name__ == "__main__":
    main()
