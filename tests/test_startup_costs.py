#!/usr/bin/env python3
"""Start-up costs: the running total, the recurring clock, and who may see a receipt.

The point of this ledger is that nobody has to remember what the project costs. So the
things worth pinning are the arithmetic a person would otherwise do by hand:

  * a one-off counts once, on its own date, and not before
  * a monthly subscription counts once per month from its start date — three months in,
    it has been charged three times, and its next charge is the month after today
  * a yearly one divides into the monthly run rate but charges once
  * ending a subscription stops it counting and clears its next charge
  * the summary total equals the sum of the rows (a total that disagrees with its rows is
    worse than no total)
  * a receipt comes back byte-identical to an admin and 403 to anyone else — a receipt
    shows the last four digits of a card
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILS
    if cond:
        print("  ok   %s" % label)
    else:
        FAILS += 1
        print("  FAIL %s %s" % (label, detail))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="resmara-costs-")
    os.environ["RESMARA_UPLOAD_DIR"] = tmp
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "costs.db")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-costs")
    os.environ["RESMARA_ADMIN_EMAILS"] = "owner@example.com"

    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import Base, engine, SessionLocal, User

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    from app.core.security import get_password_hash

    def account(email: str, admin: bool = False) -> dict:
        """Make the account, then sign in with the real login route.

        The beta gate refuses a stranger's signup outright (403), which is correct and is
        not what this test is about, so the second account is written straight to the
        table — the same row the gate would eventually produce — and then logs in normally.
        """
        with SessionLocal() as db:
            if not db.query(User).filter(User.email == email).first():
                db.add(User(email=email, name=email, hashed_password=get_password_hash("costs-pass-123"),
                            is_active=True, is_admin=admin, subscription_status="active"))
                db.commit()
        r = client.post("/api/auth/login", data={"username": email, "password": "costs-pass-123"})
        token = r.json().get("access_token", "")
        if not token:
            check("login as " + email, False, r.text[:160])
        return {"Authorization": "Bearer " + token}

    admin = account("owner@example.com", admin=True)
    other = account("notadmin@example.com")

    # ── the admin-only door ────────────────────────────────────────────────────
    check("a stranger cannot read the ledger",
          client.get("/api/admin/costs", headers=other).status_code == 403,
          str(client.get("/api/admin/costs", headers=other).status_code))
    check("an admin can", client.get("/api/admin/costs", headers=admin).status_code == 200)

    today = date.today()
    months_ago_3 = date(today.year - (1 if today.month <= 3 else 0),
                        ((today.month - 4) % 12) + 1, min(today.day, 28))

    # ── a one-off: the domain ──────────────────────────────────────────────────
    r = client.post("/api/admin/costs", headers=admin, json={
        "paid_on": months_ago_3.isoformat(), "paid_by": "Dan", "vendor": "Namecheap",
        "description": "resmara.com, one year", "amount_cents": 1598, "kind": "one_off"})
    check("a one-off purchase is recorded", r.status_code == 201, r.text[:200])
    domain = r.json()
    check("and charged exactly once", domain["charges"] == 1, str(domain["charges"]))
    check("with no next charge", domain["next_charge_on"] is None, str(domain["next_charge_on"]))

    # a one-off dated in the future has not been charged yet
    r = client.post("/api/admin/costs", headers=admin, json={
        "paid_on": (today + timedelta(days=30)).isoformat(), "paid_by": "Dan", "vendor": "Later Co",
        "amount_cents": 5000, "kind": "one_off"})
    check("a future one-off has not been charged yet", r.json()["charges"] == 0, str(r.json()["charges"]))

    # ── a monthly subscription: hosting ────────────────────────────────────────
    r = client.post("/api/admin/costs", headers=admin, json={
        "paid_on": months_ago_3.isoformat(), "paid_by": "Dan", "vendor": "Render",
        "description": "web service", "amount_cents": 700, "kind": "recurring",
        "cadence": "monthly", "started_on": months_ago_3.isoformat()})
    check("a monthly subscription is recorded", r.status_code == 201, r.text[:200])
    render = r.json()
    check("three months in it has charged three times (or two, on the boundary day)",
          render["charges"] in (3, 4), str(render["charges"]))
    check("its next charge is dated", bool(render["next_charge_on"]), str(render["next_charge_on"]))
    check("and the amount charged matches the count",
          abs(render["charged_to_date_usd"] - 7.00 * render["charges"]) < 0.011,
          str(render["charged_to_date_usd"]))

    # ── a yearly subscription divides into the run rate, charges once a year ────
    r = client.post("/api/admin/costs", headers=admin, json={
        "paid_on": months_ago_3.isoformat(), "paid_by": "Dan", "vendor": "Resend",
        "amount_cents": 12000, "kind": "recurring", "cadence": "yearly"})
    check("a yearly subscription is recorded", r.status_code == 201, r.text[:200])
    yearly = r.json()
    check("yearly charges once", yearly["charges"] == 1, str(yearly["charges"]))

    # ── the summary has to agree with its rows ─────────────────────────────────
    body = client.get("/api/admin/costs", headers=admin).json()
    items, summary = body["items"], body["summary"]
    row_total = round(sum(i["charged_to_date_usd"] for i in items), 2)
    check("the total equals the sum of the rows", abs(summary["spent_to_date_usd"] - row_total) < 0.02,
          "%s vs %s" % (summary["spent_to_date_usd"], row_total))
    check("a monthly run rate is shown", summary["monthly_recurring_usd"] >= 7.00,
          str(summary["monthly_recurring_usd"]))
    # $7 monthly + $120 yearly/12 = $17: the yearly charge is divided, never dropped on
    check("the yearly one is folded into it, not added whole",
          16.99 <= summary["monthly_recurring_usd"] <= 17.01, str(summary["monthly_recurring_usd"]))
    check("the run rate is annualised", abs(summary["yearly_run_rate_usd"] - summary["monthly_recurring_usd"] * 12) < 0.05,
          str(summary["yearly_run_rate_usd"]))
    check("two subscriptions are active", summary["active_subscriptions"] == 2, str(summary["active_subscriptions"]))
    check("who paid is grouped", summary["by_payer_usd"].get("Dan", 0) > 0, str(summary["by_payer_usd"]))

    # ── a receipt: admin only, byte for byte ───────────────────────────────────
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    r = client.post("/api/admin/costs/%d/receipt" % render["id"], headers=admin,
                    files={"file": ("render-oct.pdf", pdf, "application/pdf")})
    check("a receipt attaches", r.status_code == 201, r.text[:200])
    meta = r.json()
    check("and is listed on the row", meta.get("url", "").startswith("/api/admin/costs/receipts/"), str(meta)[:120])

    r = client.get(meta["url"], headers=admin)
    check("the receipt answers its owner", r.status_code == 200, str(r.status_code))
    check("byte for byte", r.content == pdf, "%d bytes" % len(r.content))
    check("as a PDF", r.headers.get("content-type", "").startswith("application/pdf"),
          r.headers.get("content-type", ""))
    check("with no cache", r.headers.get("cache-control") == "no-store", str(r.headers.get("cache-control")))
    check("and a stranger gets 403", client.get(meta["url"], headers=other).status_code == 403)

    r = client.post("/api/admin/costs/%d/receipt" % render["id"], headers=admin,
                    files={"file": ("notes.exe", b"MZ", "application/octet-stream")})
    check("a non-receipt file is refused", r.status_code == 415, str(r.status_code))

    body = client.get("/api/admin/costs", headers=admin).json()
    check("the receipt count is on the summary",
          body["summary"]["with_receipt"] == 1 and body["summary"]["without_receipt"] == 3,
          "%s / %s" % (body["summary"]["with_receipt"], body["summary"]["without_receipt"]))

    # ── cancelling a subscription stops the clock ──────────────────────────────
    r = client.patch("/api/admin/costs/%d" % render["id"], headers=admin,
                     json={"ended_on": today.isoformat()})
    check("a subscription can be ended", r.status_code == 200, r.text[:200])
    ended = r.json()
    check("an ended subscription has no next charge", ended["next_charge_on"] is None,
          str(ended["next_charge_on"]))
    body = client.get("/api/admin/costs", headers=admin).json()
    check("and drops out of the run rate", body["summary"]["active_subscriptions"] == 1,
          str(body["summary"]["active_subscriptions"]))
    check("but its past charges still count",
          body["summary"]["recurring_to_date_usd"] > 0, str(body["summary"]["recurring_to_date_usd"]))
    r = client.patch("/api/admin/costs/%d" % render["id"], headers=admin, json={"ended_on": None})
    check("and it can be started again", r.status_code == 200 and r.json()["next_charge_on"] is not None,
          str(r.json().get("next_charge_on")))

    # ── deleting a row takes its receipts with it ──────────────────────────────
    check("delete works", client.delete("/api/admin/costs/%d" % render["id"], headers=admin).status_code == 200)
    check("and the receipt is gone", client.get(meta["url"], headers=admin).status_code == 404,
          str(client.get(meta["url"], headers=admin).status_code))

    if FAILS:
        print("FAIL — %d check(s) failed" % FAILS)
        return 1
    print("PASS — one-offs count once, subscriptions keep counting, an ended one stops, the\n"
          "       summary agrees with its rows, and a receipt is admin-only and byte-exact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
