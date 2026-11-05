"""The operator console, tested for the two things that made it unusable.

Why this test exists: the suites register a throwaway client on every run, so the console
had 75 accounts and 78 ticket rows, 71 and 24 of which no human ever created - a 9,700px
page on a laptop, with the four real accounts buried in it. Two rules follow, and this file
is what holds them:

  * **A test row is flagged, never deleted, and never silently dropped from a total.**
    ``total`` stays every row in the database; ``real``/``test_*`` name the split so the
    console can print "4 real - 71 test" and hide the test share on request.
  * **The console starts folded.** Every section ships closed and the operator's own
    folding is remembered, so the console opens on one screen of "what is waiting on me".

Runs hermetically: temp sqlite DB, no network, no real install touched.

Run:  cd /Users/dan/resmara && venv/bin/python tests/test_admin_console.py
"""

import os
import re
import tempfile
from datetime import datetime, timedelta

# --- environment BEFORE the app is imported (config reads env at import time) ---
_tmp = tempfile.NamedTemporaryFile(prefix="resmara-console-", suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ.pop("RESMARA_SIMULATE", None)

import sys                                                            # noqa: E402

sys.path.insert(0, "/Users/dan/resmara")

from fastapi.testclient import TestClient                             # noqa: E402

from app.core.security import get_password_hash                        # noqa: E402
from app.core.testdata import is_test_advertiser, is_test_email       # noqa: E402
from app.db.session import (AdAccount, Asset, Base, Boost, Post,      # noqa: E402
                            SessionLocal, SupportTicket, User, engine)
from app.main import app                                              # noqa: E402
from app.services import metrics as M                                 # noqa: E402

checks = 0
failures = 0


def ok(name, cond, extra=""):
    global checks, failures
    checks += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        failures += 1
        print(f"  FAIL  {name}" + (f"  ({extra})" if extra else ""))


# --------------------------------------------------------------------- the rule itself
print("\n[which rows are ours, not a customer's]")
for email in ("smoke1793825878@example.com", "test@example.com", "demo@example.org",
              "qa@test", "someone@localhost"):
    ok(f"{email} is a test account", is_test_email(email))
for email in ("danieldaymude@gmail.com", "agent@resmara.com", "partner@resmara.com",
              "client1@gmail.com", None, ""):
    ok(f"{email!r} is a real account (hiding a customer is worse than showing a test)",
       not is_test_email(email))
ok("a smoke ad account id is a test account", is_test_advertiser("act_smoke_1793825878"))
ok("a real ad account id is not", not is_test_advertiser("act_254170201"))

# --------------------------------------------------------------- a database we can count
Base.metadata.create_all(bind=engine)
db = SessionLocal()

PW = "console-pass-12345"
ops = User(email="ops@resmara.com", hashed_password=get_password_hash(PW), is_admin=True,
           subscription_status="active")
client1 = User(email="client1@gmail.com", hashed_password="x", subscription_status="active")
client2 = User(email="client2@yahoo.com", hashed_password="x")
smoke = User(email="smoke1793825878@example.com", hashed_password="x")
qa = User(email="qa@test", hashed_password="x")
db.add_all([ops, client1, client2, smoke, qa])
db.flush()

real_acct = AdAccount(user_id=client1.id, platform="meta", advertiser_id="act_1001",
                      access_token="EAAG" + "x" * 40, token_status="healthy", is_active=True)
reconnect = AdAccount(user_id=client1.id, platform="meta", advertiser_id="act_1002",
                      access_token="EAAG" + "y" * 40, token_status="needs_reconnect", is_active=True)
sim = AdAccount(user_id=smoke.id, platform="meta", advertiser_id="act_smoke_1",
                access_token="sim_token_prototype", token_status="simulated", is_active=True)
db.add_all([real_acct, reconnect, sim])
db.flush()

live = Boost(user_id=client1.id, ad_account_id=real_acct.id, address="1 Real Way", stage="LIVE",
             plan={"posts": [{"day": 1}]}, ad_budget_usd=50.0, launched_at=datetime.utcnow())
empty = Boost(user_id=client1.id, ad_account_id=real_acct.id, address="2 Real Way",
              stage="PENDING", plan={})
noisy = Boost(user_id=smoke.id, ad_account_id=sim.id, address="3 Test Way", stage="PENDING", plan={})
db.add_all([live, empty, noisy])
db.flush()

due = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
db.add_all([
    Post(boost_id=live.id, day=1, client_status="approved", publish_status="scheduled", publish_at=due),
    Post(boost_id=live.id, day=2, client_status="approved", publish_status="failed"),
    Post(boost_id=noisy.id, day=1, client_status="approved", publish_status="scheduled", publish_at=due),
    Asset(user_id=client1.id, boost_id=live.id, filename="real.jpg", url="/uploads/real.jpg", kind="photo"),
    Asset(user_id=smoke.id, boost_id=noisy.id, filename="test.jpg", url="/uploads/test.jpg", kind="photo"),
    SupportTicket(user_id=client1.id, subject="A real question", status="open",
                  messages=[{"from": "client1@gmail.com", "text": "help", "at": due}]),
    SupportTicket(user_id=smoke.id, subject="A test question", status="open",
                  messages=[{"from": "smoke@example.com", "text": "help", "at": due}]),
])
db.commit()

# ------------------------------------------------------------------ metrics: the split
print("\n[metrics name the test share instead of losing it]")
a = M.activity(db)
u, c, ct, s, adv = a["users"], a["campaigns"], a["content"], a["support"], a["advertising"]

ok("every account is still in the total", u["total"] == 5, u)
ok("real accounts are the ones a person made", u["real"] == 3, u)
ok("test accounts are named", u["test_accounts"] == 2, u)

ok("every campaign is in the total", c["total"] == 3, c)
ok("campaigns split into real/test", c["real"] == 2 and c["test_campaigns"] == 1, c)
ok("awaiting build counts them", c["awaiting_build"] == 2, c)
ok("  ...and says how many are a test's", c["awaiting_build_test"] == 1, c)

ok("every post is in the total", ct["posts_total"] == 3, ct)
ok("posts split into real/test", ct["real_posts"] == 2 and ct["test_posts"] == 1, ct)
ok("due now keeps the publisher's rule for every row", ct["due_now"] == 2, ct)
ok("  ...and names the test share of it", ct["due_now_test"] == 1, ct)
ok("failed posts are split too", ct["failed"] == 1 and ct["failed_test"] == 0, ct)
ok("photos are split too", ct["photos"] == 2 and ct["photos_test"] == 1, ct)

ok("every ticket is in the total", s["tickets_total"] == 2, s)
ok("tickets split into real/test", s["real"] == 1 and s["test_tickets"] == 1, s)
ok("waiting on us counts both", s["waiting_on_us"] == 2, s)
ok("  ...and names the test share, so the tile cannot inflate", s["waiting_on_us_test"] == 1, s)

ok("token state is reported per row", adv["by_token_status"].get("healthy") == 1
   and adv["by_token_status"].get("needs_reconnect") == 1 and adv["by_token_status"].get("simulated") == 1,
   adv["by_token_status"])
ok("needs_reconnect is counted from those rows", adv["needs_reconnect"] == 1, adv)
ok("a real token is a live account, a sentinel is not", adv["live_accounts"] == 2 and adv["simulated"] == 1, adv)

print("\n[no doubles - the console renders both cards, so no figure is printed twice]")
h = M.system_health(db)
ok("health still carries no product counts",
   not ({"total_users", "total_boosts", "total_posts", "test_accounts"} & set(h)), sorted(h))
ok("metrics still carries no service state",
   not ({"status", "db_ok", "version", "errors_24h"} & set(a)), sorted(a))

# -------------------------------------------------------------- the operator's endpoints
print("\n[the endpoints flag a test row instead of hiding it]")
client = TestClient(app)
login = client.post("/api/auth/login", data={"username": ops.email, "password": PW})
ok("the operator can sign in", login.status_code == 200, login.text[:120])
token = login.json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

rows = client.get("/api/admin/users", headers=H).json()
by_email = {r["email"]: r for r in rows}
ok("the operator sees every account", len(rows) == 5, len(rows))
ok("a real account is not flagged", by_email["client1@gmail.com"]["is_test"] is False, by_email.get("client1@gmail.com"))
ok("a smoke account is flagged", by_email["smoke1793825878@example.com"]["is_test"] is True)
ok("the flagged count matches the metric",
   len([r for r in rows if r["is_test"]]) == u["test_accounts"], u["test_accounts"])

tickets = client.get("/api/admin/support", headers=H).json()
real = [t for t in tickets if not t["is_test"]]
noisy_tickets = [t for t in tickets if t["is_test"]]
ok("tickets carry the client's email", real and real[0]["client_email"] == "client1@gmail.com", real[:1])
ok("a ticket from a test account is flagged",
   len(noisy_tickets) == 1 and noisy_tickets[0]["client_email"].endswith("@example.com"),
   [t["client_email"] for t in noisy_tickets])

# ---------------------------------------------------------------- the console itself
print("\n[the console folds, and hides what is not a customer]")
r = client.get("/admin.html")
html = r.text
ok("it is served through the app, with the metrics card the deploy smoke test looks for",
   r.status_code == 200 and 'id="metricsBody"' in html, r.status_code)
sections = re.findall(r'data-sec="([a-z]+)"', html)
ok("every area is its own foldable section",
   {"support", "content", "campaigns", "users", "advertising", "activity", "health", "checks"} <= set(sections),
   sections)
ok("no section ships open, so the console opens on one screen",
   not re.findall(r"<details[^>]*\sopen", html), re.findall(r"<details[^>]*\sopen", html))
ok("folding is remembered per operator", "resmara_admin_open" in html)
ok("the index jumps to a section", 'href="#sec-support"' in html and "openSection(" in html)
ok("an account's test rows are hidden unless asked for",
   "showTestUsers" in html and "showTestUsers').checked" in html)
ok("a ticket's test rows are hidden unless asked for", "showTestTickets" in html)
ok("the console reports how many it is holding back",
   "test accounts hidden" in html and "test ticket(s)" in html)
ok("the triage tiles come first, before any list", html.index('id="triage"') < html.index('id="sec-support"'))
ok("the triage tile for support only counts real ones",
   "(s.waiting_on_us || 0) - (s.waiting_on_us_test || 0)" in html)
ok("the real number is printed beside the test share",
   "u.real + ' real · ' + u.test_accounts + ' test'" in html)
ok("a half-written reply is never refreshed over", "value.trim()" in html and "ticket-detail:not(.hidden)" in html)

db.close()
print(f"\n{checks} checks, {failures} failed.")
if failures:
    raise SystemExit(1)
print("ALL OPERATOR CONSOLE TESTS PASSED")
