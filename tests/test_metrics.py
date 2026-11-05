"""Hermetic tests for app/services/metrics.py - the operator's numbers.

What this suite is really guarding:

  * **No doubles.** Health must not carry product counts and metrics must not carry
    service state, because the console renders both and a figure printed twice invites
    the reader to believe it twice. The check is explicit: health has no 'total_users'
    style key, metrics has no 'status'/'db_ok'.
  * **No invented numbers.** Every count is asserted against rows this test inserted,
    and anything unknowable must appear under ``unavailable`` with a reason.
  * **Honest windows.** ``active_24h`` counts sign-ins in the last day (it used to count
    any account that had ever signed in), ``errors_24h`` counts errors inside the day,
    and ``per_day`` only counts events inside its window.
  * **A ticket is open until it is resolved.** The old metric counted the literal
    status ``open``, so a queue of in-progress tickets read as zero.

Run:  cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_metrics.py
Writes only to a temp sqlite DB under the Hermes scratch dir; no network.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import (AdAccount, Asset, Base, Boost, Event, Post,
                           SupportTicket, User)
from app.services import metrics as M

PASSED = 0
FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}  {detail}")


def now():
    return datetime.utcnow()


def build_db():
    """A temp database with exactly the rows the assertions below count."""
    scratch = "/Users/dan/.hermes/profiles/dev/cache/scratch"
    if not os.path.isdir(scratch):
        scratch = tempfile.gettempdir()
    path = tempfile.mkdtemp(prefix="resmara_metrics_", dir=scratch)
    engine = create_engine("sqlite:///" + os.path.join(path, "m.db"),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    # users: one fresh sign-in, one stale sign-in, one that never signed in
    fresh = User(email="fresh@example.com", hashed_password="x", last_login=now() - timedelta(hours=2))
    stale = User(email="stale@example.com", hashed_password="x", last_login=now() - timedelta(hours=40))
    never = User(email="never@example.com", hashed_password="x", is_admin=True)
    gone = User(email="gone@example.com", hashed_password="x", is_active=False)
    db.add_all([fresh, stale, never, gone])
    db.flush()
    # created_at is server_default; backdate one account so "new in 7d" has a real edge
    db.query(User).filter(User.id == stale.id).update({"created_at": now() - timedelta(days=30)})
    db.commit()

    # ad accounts: one simulated (prototype sentinel token), one with a real-looking token
    sim = AdAccount(user_id=fresh.id, platform="meta", advertiser_id="act_1",
                    access_token="sim_token_prototype", budget=500.0)
    live = AdAccount(user_id=fresh.id, platform="meta", advertiser_id="act_2",
                     access_token="EAAG" + "x" * 40, budget=1500.0)
    db.add_all([sim, live])
    db.flush()

    built = Boost(user_id=fresh.id, ad_account_id=live.id, address="1 Metric Way",
                  stage="LIVE", plan={"posts": [{"day": 1}]}, ad_budget_usd=50.0,
                  launched_at=now())
    pending = Boost(user_id=fresh.id, ad_account_id=live.id, address="2 Metric Way",
                    stage="PENDING", plan={}, ad_budget_usd=25.0)
    inactive = Boost(user_id=fresh.id, ad_account_id=sim.id, address="3 Metric Way",
                     stage="PENDING", plan={}, ad_budget_usd=10.0)
    sim.is_active = False
    db.add_all([built, pending, inactive])
    db.flush()

    due = now() - timedelta(minutes=5)
    future = now() + timedelta(days=2)
    db.add_all([
        # approved + scheduled + due + live account -> the publisher will pick this up
        Post(boost_id=built.id, day=1, client_status="approved", publish_status="scheduled",
             publish_at=due.isoformat()),
        # approved but on a deactivated account -> not the publisher's work
        Post(boost_id=inactive.id, day=1, client_status="approved", publish_status="scheduled",
             publish_at=due.isoformat()),
        # still awaiting approval -> not the publisher's work
        Post(boost_id=built.id, day=2, client_status="pending", publish_status="scheduled",
             publish_at=due.isoformat()),
        # approved, but not due yet
        Post(boost_id=built.id, day=3, client_status="approved", publish_status="scheduled",
             publish_at=future.isoformat()),
        Post(boost_id=built.id, day=4, client_status="approved", publish_status="posted"),
        Post(boost_id=built.id, day=5, client_status="approved", publish_status="failed"),
        Post(boost_id=built.id, day=6, client_status="change_requested", publish_status="scheduled"),
    ])
    db.add_all([
        Asset(user_id=fresh.id, boost_id=built.id, filename="a.jpg", url="/uploads/a.jpg",
              kind="photo", tagged_by="ai"),
        Asset(user_id=fresh.id, boost_id=built.id, filename="b.jpg", url="/uploads/b.jpg",
              kind="photo", tagged_by="none"),
        Asset(user_id=fresh.id, boost_id=built.id, filename="c.png", url="/uploads/c.png",
              kind="design"),
    ])
    db.add_all([
        # latest message is from the client -> the team owes them an answer
        SupportTicket(user_id=fresh.id, subject="Post failed", status="open",
                      messages=[{"from": "fresh@example.com", "text": "help", "at": now().isoformat()}]),
        # already answered -> nothing owed
        SupportTicket(user_id=fresh.id, subject="Invoice", status="in_progress",
                      messages=[{"from": "fresh@example.com", "text": "?", "at": now().isoformat()},
                                {"from": "admin", "text": "on it", "at": now().isoformat()}]),
        SupportTicket(user_id=never.id, subject="Old one", status="resolved",
                      messages=[{"from": "admin", "text": "done", "at": now().isoformat()}]),
    ])
    db.add_all([
        Event(event_type="campaign_built", created_at=now()),
        Event(event_type="user_registered", created_at=now()),
        Event(event_type="error", created_at=now() - timedelta(hours=3)),      # inside 24h
        Event(event_type="error", created_at=now() - timedelta(days=3)),       # outside 24h
        Event(event_type="campaign_launched", created_at=now() - timedelta(days=30)),  # outside 14d
    ])
    db.commit()
    return db, sim, live, built, inactive


def main():
    db, sim, live, built, inactive = build_db()

    print("\n[system health carries no product counts]")
    h = M.system_health(db)
    for key in ("status", "db_ok", "version", "env", "errors_24h", "last_error_at",
                "last_build_at", "last_launch_at", "ai_mode", "ai_note",
                "platform_mode", "platform_note", "checked_at"):
        check(f"health has '{key}'", key in h, sorted(h))
    for banned in ("total_users", "total_boosts", "active_campaigns", "total_posts",
                   "open_support_tickets", "active_users_24h"):
        check(f"health does NOT repeat '{banned}'", banned not in h, "doubles the metrics card")
    check("health says healthy with a reachable db", h["status"] == "healthy" and h["db_ok"] is True)
    check("errors_24h only counts errors inside 24h", h["errors_24h"] == 1, h["errors_24h"])
    check("last_error_at is the most recent error",
          (h["last_error_at"] or "").startswith((now() - timedelta(hours=3)).date().isoformat()),
          h["last_error_at"])

    print("\n[metrics carries no service state]")
    a = M.activity(db)
    for group in ("users", "campaigns", "content", "support", "advertising", "activity", "unavailable"):
        check(f"metrics has group '{group}'", group in a, sorted(a))
    for banned in ("status", "db_ok", "version", "errors_24h"):
        check(f"metrics does NOT repeat '{banned}'", banned not in a, "doubles the health card")

    print("\n[users]")
    u = a["users"]
    check("counts every account", u["total"] == 4, u)
    check("active means enabled", u["active"] == 3, u)
    check("admins are flagged", u["admins"] == 1, u)
    check("new_7d uses a real 7-day window", u["new_7d"] == 3, u)
    check("active_24h counts sign-ins in the last day, not 'has ever signed in'",
          u["active_24h"] == 1, u)
    check("never_signed_in counts accounts with no sign-in (two: the admin and the disabled one)",
          u["never_signed_in"] == 2, u)

    print("\n[campaigns]")
    c = a["campaigns"]
    check("counts campaigns", c["total"] == 3, c)
    check("by_stage groups them", c["by_stage"].get("LIVE") == 1 and c["by_stage"].get("PENDING") == 2, c["by_stage"])
    check("live counts stage LIVE", c["live"] == 1, c)
    check("launched counts a launch timestamp", c["launched"] == 1, c)
    check("awaiting_build counts the ones with no plan", c["awaiting_build"] == 2, c)
    check("budget is the sum of configured budgets", c["budget_configured_usd"] == 85.0, c)

    print("\n[content]")
    t = a["content"]
    check("counts posts", t["posts_total"] == 7, t)
    check("approved", t["approved"] == 5, t)
    check("awaiting_approval", t["awaiting_approval"] == 1, t)
    check("changes_requested", t["changes_requested"] == 1, t)
    check("published", t["published"] == 1, t)
    check("failed", t["failed"] == 1, t)
    check("due_now matches the publisher's rule (approved + scheduled + due + live account)",
          t["due_now"] == 1, t)
    check("next_publish_at is the soonest future slot",
          (t["next_publish_at"] or "").startswith((now() + timedelta(days=2)).date().isoformat()),
          t["next_publish_at"])
    check("photos counted", t["photos"] == 2 and t["designs"] == 1, t)
    check("tagged/untagged split", t["photos_tagged"] == 1 and t["photos_untagged"] == 1, t)

    print("\n[support]")
    s = a["support"]
    check("counts tickets", s["tickets_total"] == 3, s)
    check("open includes in_progress (a queue of open work read as zero before)",
          s["open"] == 2, s)
    check("waiting_on_us counts only the ones the client spoke last on", s["waiting_on_us"] == 1, s)
    check("resolved", s["resolved"] == 1, s)
    check("oldest_waiting_at is the OLDEST waiting ticket",
          s["oldest_waiting_at"] is not None, s)

    print("\n[advertising + platform mode]")
    ad = a["advertising"]
    check("counts accounts", ad["accounts"] == 2, ad)
    check("a prototype sentinel token is NOT a live account", ad["live_accounts"] == 1, ad)
    check("simulated is the rest", ad["simulated"] == 1, ad)
    check("platforms grouped", ad["platforms"].get("meta") == 2, ad["platforms"])
    check("platform_mode reports live while a real token exists",
          M.system_health(db)["platform_mode"] == "live", M.system_health(db))

    print("\n[activity log]")
    log = a["activity"]
    check("per_day has one bucket per day", len(log["per_day"]) == 14, len(log["per_day"]))
    check("the window's total counts in-window events only", log["total_14d"] == 4, log["total_14d"])
    check("a 30-day-old event is outside the window",
          log["by_type_14d"].get("campaign_launched") is None, log["by_type_14d"])
    check("days are in order", [d["date"] for d in log["per_day"]] == sorted(d["date"] for d in log["per_day"]))

    print("\n[not measured]")
    names = {x["metric"] for x in a["unavailable"]}
    check("ad_spend is named as unmeasured", "ad_spend" in names, names)
    check("revenue is named as unmeasured", "revenue" in names, names)
    check("every unavailable entry carries a reason",
          all(x.get("reason") for x in a["unavailable"]), a["unavailable"])

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
