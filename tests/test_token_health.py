"""Connection health for a client-billed Meta account, tested against a mock Graph.

Why this test exists: in the client-billed model the customer's own ad account is the
advertiser and their own card pays Meta. Two failures are invisible until it is too late -
the token expires or is revoked, and the account cannot spend because no payment method is
on it. Both produced a launch that "succeeded" by creating a PAUSED campaign that would
never run. This test drives the real code paths with a mock Graph and pins down:

  * tokens are encrypted at rest and never returned by the API;
  * a token close to expiry is refreshed before it dies (and an invalid one is reported);
  * "cannot spend" is reported with Meta's own reason, and an unmeasured payment method is
    reported as unknown rather than as "no card";
  * a launch is REFUSED when the connection is not healthy, and no campaign is created;
  * a launch that fails halfway rolls its own chain back instead of leaving an orphan.

Runs hermetically: temp sqlite DB, local mock Graph server, no network.
"""

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# --- environment BEFORE the app is imported (config reads env at import time) ---
_tmp = tempfile.NamedTemporaryFile(prefix="resmara-health-", suffix=".db", delete=False)
_tmp.close()
DB_PATH = _tmp.name
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ.pop("RESMARA_SIMULATE", None)

ADVERTISER = "act_777000111"
LONG_TOKEN = "long-lived-token-A"
FRESH_TOKEN = "long-lived-token-B"

# What the mock Graph answers. Mutated per case so one server covers every scenario.
STATE = {
    "valid": True,
    "expires_at": int(time.time()) + 55 * 86400,   # plenty of life left
    "scopes": ["ads_management", "business_management"],
    "app_id": os.environ.get("META_CLIENT_ID", ""),
    "account_status": 1,
    "disable_reason": 0,
    "funding_source_details": {"id": "1", "type": "VISA", "display_string": "Visa ending in 4242"},
    "include_funding_field": True,
    "fail_adset": False,
    "throttle": False,
    "refresh_extends": True,        # does the exchange actually buy more time?
}
calls = []


class Graph(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # --- helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message, code=400, subcode=None, http=400):
        err = {"message": message}
        if subcode:
            err["error_subcode"] = subcode
        self._json({"error": err}, code=http)

    # --- routes
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        calls.append(("GET", u.path, q))

        if u.path == "/debug_token":
            if STATE["throttle"]:
                return self._json({"error": {"message": "too many calls", "code": 4}}, code=400)
            data = {
                "app_id": STATE["app_id"] or "1881970083170197",
                "type": "USER",
                "application": "Resmara Test",
                "is_valid": STATE["valid"],
                "expires_at": STATE["expires_at"],
                "data_access_expires_at": STATE["expires_at"] + 86400,
                "scopes": STATE["scopes"],
            }
            return self._json({"data": data})

        if u.path == "/oauth/access_token":
            if q.get("grant_type") != "fb_exchange_token":
                return self._error("unexpected grant", http=400)
            if not q.get("fb_exchange_token"):
                return self._error("fb_exchange_token missing", http=400)
            # A real refresh hands back a token whose life starts over, so the next
            # debug_token must report the fresh expiry - otherwise the check would keep
            # saying "expiring" about a token it just renewed.
            if STATE["refresh_extends"]:
                STATE["expires_at"] = int(time.time()) + 55 * 86400
            return self._json({"access_token": FRESH_TOKEN, "expires_in": 5183944})

        if u.path == f"/{ADVERTISER}":
            body = {"id": ADVERTISER, "name": "Client Ad Account",
                    "account_status": STATE["account_status"],
                    "disable_reason": STATE["disable_reason"],
                    "currency": "USD"}
            if STATE["include_funding_field"]:
                body["funding_source_details"] = STATE["funding_source_details"]
            return self._json(body)

        if u.path == f"/{ADVERTISER}/campaigns":
            return self._json({"id": "camp_1"})
        if u.path == f"/{ADVERTISER}/adsets":
            if STATE["fail_adset"]:
                return self._error("Ad set rejected by policy", code=100, subcode=1815857)
            return self._json({"id": "adset_1"})
        if u.path == f"/{ADVERTISER}/adcreatives":
            return self._json({"id": "creative_1"})
        if u.path == f"/{ADVERTISER}/ads":
            return self._json({"id": "ad_1"})
        return self._error("unexpected " + u.path, http=404)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        calls.append(("POST", u.path, q))
        return self.do_GET()

    def do_DELETE(self):
        u = urlparse(self.path)
        calls.append(("DELETE", u.path, {}))
        if STATE.get("fail_delete"):
            return self._error("cannot delete", http=400)
        return self._json({"success": True})


server = HTTPServer(("127.0.0.1", 0), Graph)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["GRAPH_API_BASE"] = f"http://127.0.0.1:{port}"

from fastapi.testclient import TestClient                       # noqa: E402
from app.main import app                                        # noqa: E402
from app.db.session import Base, engine, SessionLocal, AdAccount  # noqa: E402
from app.core.crypto import is_encrypted, decrypt              # noqa: E402
from app.core.config import settings                           # noqa: E402
from app.services import token_health                          # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)

# The app loads its own .env at import (config.py), so META_CLIENT_ID/SECRET and
# RESMARA_PUBLISH_TOKEN come from there. GRAPH_API_BASE was set above, which is what
# settings.graph_base reads - the app under test therefore talks to the mock Graph and
# never to Facebook. Nothing here prints or asserts on the real secret.
STATE["app_id"] = settings.META_CLIENT_ID

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


def reset_calls():
    calls.clear()


def sign_up(email):
    """A signed-up customer with a live subscription, so the launch gate is exercised on the
    connection health it is testing and not stopped earlier by a budget/credit refusal."""
    pw = "health-pass-12345"
    client.post("/api/auth/register", json={"email": email, "password": pw, "name": "Health Check"})
    token = client.post("/api/auth/login", data={"username": email, "password": pw}).json()["access_token"]
    session = SessionLocal()
    from app.db.session import User
    user = session.query(User).filter(User.email == email).first()
    user.subscription_status = "active"
    session.add(user)
    session.commit()
    session.close()
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- 1. encryption
print("\n=== 1. tokens are encrypted at rest ===")
H = sign_up("health-owner@example.com")
resp = client.post("/api/ad-accounts", headers=H, json={
    "platform": "meta", "advertiser_id": ADVERTISER, "account_name": "Client Ad Account",
    "budget": 5000.0})
ok("ad account created", resp.status_code in (200, 201), resp.text[:120])

db = SessionLocal()
acct = db.query(AdAccount).filter(AdAccount.advertiser_id == ADVERTISER).first()
acct.access_token = LONG_TOKEN                      # a real token, not the simulated placeholder
db.add(acct)
db.commit()
db.refresh(acct)

ok("the app reads the token back in plaintext", acct.access_token == LONG_TOKEN, acct.access_token)
row = engine.connect().exec_driver_sql(
    "SELECT access_token FROM ad_accounts WHERE advertiser_id = ?", (ADVERTISER,)).fetchone()
raw = row[0]
ok("the database holds ciphertext, not the token", LONG_TOKEN not in raw and is_encrypted(raw),
   str(raw)[:40])
ok("  ...so the token cannot be read out of the .db file", LONG_TOKEN.encode() not in open(DB_PATH, "rb").read())
ok("the ciphertext decrypts back to the token", decrypt(raw) == LONG_TOKEN)

listing = client.get("/api/ad-accounts", headers=H).json()
ok("the API returns the account with its health fields",
   isinstance(listing, list) and listing and "token_status" in listing[0], str(listing)[:160])
ok("  ...and never returns the token itself",
   LONG_TOKEN not in json.dumps(listing) and "access_token" not in json.dumps(listing))

# --------------------------------------------------------------------------- 2. token check
print("\n=== 2. a healthy long-lived token is left alone ===")
reset_calls()
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("a token with weeks left is reported healthy", summary["token_status"] == "healthy", str(summary)[:200])
ok("  ...with the days left, from Meta", summary["days_left"] and summary["days_left"] > 30, str(summary["days_left"]))
ok("  ...and is NOT needlessly re-exchanged",
   not [c for c in calls if c[1] == "/oauth/access_token"], str([c[1] for c in calls]))
ok("  ...and the expiry Meta reported is stored", acct.token_expires_at is not None)

print("\n=== 3. a token about to expire is refreshed before it dies ===")
STATE["expires_at"] = int(time.time()) + 3 * 86400      # 3 days left, inside the refresh window
reset_calls()
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("a token inside the refresh window is exchanged for a fresh one", summary.get("refreshed") is True, str(summary)[:200])
ok("  ...using the documented fb_exchange_token grant",
   any(c[1] == "/oauth/access_token" and c[2].get("grant_type") == "fb_exchange_token" for c in calls),
   str([c[1] for c in calls]))
db.refresh(acct)
ok("  ...and the NEW token is what gets stored (encrypted)", acct.access_token == FRESH_TOKEN, acct.access_token)
ok("  ...and the new expiry replaces the old one", acct.token_expires_at is not None)
ok("  ...and the account ends up healthy again", summary["token_status"] == "healthy", str(summary["token_status"]))
STATE["expires_at"] = int(time.time()) + 55 * 86400

print("\n=== 3b. a refresh that buys nothing is reported honestly ===")
STATE["expires_at"] = int(time.time()) + 3 * 86400
STATE["refresh_extends"] = False
acct.token_refreshed_at = None
db.commit()
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("Meta accepted the refresh", summary.get("refreshed") is True, str(summary)[:220])
ok("  ...but we noticed it did NOT buy more time", summary.get("extended") is False, str(summary)[:260])
ok("  ...so the account is 'expiring', not 'healthy'", summary["token_status"] == "expiring", str(summary["token_status"]))
ok("  ...and the note the client sees says the expiry did not move",
   "same expiry" in (summary.get("token_note") or ""), str(summary.get("token_note")))

print("\n=== 3c. the token is re-exchanged at most once a day ===")
reset_calls()
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("a second check does not churn the token again",
   not [c for c in calls if c[1] == "/oauth/access_token"], str([c[1] for c in calls]))
ok("  ...and still reports it as expiring", summary["token_status"] == "expiring", str(summary["token_status"]))
STATE["refresh_extends"] = True
STATE["expires_at"] = int(time.time()) + 55 * 86400
acct.token_refreshed_at = None
db.commit()

print("\n=== 4. a revoked or invalid token is reported, never ignored ===")
STATE["valid"] = False
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("an invalid token becomes needs_reconnect", summary["token_status"] == "needs_reconnect", str(summary)[:200])
ok("  ...with a reason that tells the user what to do",
   "reconnect" in (summary["token_note"] or "").lower(), summary["token_note"])
ok("  ...and spend readiness is not even claimed", summary["spend_ok"] is False)
STATE["valid"] = True

print("\n=== 5. a token that is missing the ads permission is useless, and says why ===")
STATE["scopes"] = ["business_management"]
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("a token without ads_management is needs_reconnect", summary["token_status"] == "needs_reconnect", str(summary)[:200])
ok("  ...naming the missing permission", "ads_management" in (summary["token_note"] or ""), summary["token_note"])
STATE["scopes"] = ["ads_management", "business_management"]

print("\n=== 6. a token from a different Meta app is refused ===")
STATE["app_id"] = "9999999999999999"
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("a foreign app's token is needs_reconnect", summary["token_status"] == "needs_reconnect", str(summary)[:200])
ok("  ...and names the app mismatch", "not to this app" in (summary["token_note"] or ""), summary["token_note"])
STATE["app_id"] = settings.META_CLIENT_ID

# --------------------------------------------------------------------------- 3. spend readiness
print("\n=== 7. can this account spend? ===")
reset_calls()
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("an ACTIVE account with a card on file can spend", summary["spend_ok"] is True, str(summary)[:200])
ok("  ...and the payment method is reported as on file", summary["funding"] == "has_funding", summary["funding"])
ok("  ...and Meta's account status is preserved by name", summary["account_status_label"] == "ACTIVE",
   str(summary["account_status_label"]))

STATE["funding_source_details"] = {}
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("an account with NO payment method cannot spend", summary["spend_ok"] is False, str(summary)[:200])
ok("  ...and that is blamed on the client's card, not on Meta",
   "client" in (summary["spend_note"] or "").lower(), summary["spend_note"])

STATE["include_funding_field"] = False
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("a payment method Meta does not return is 'unknown', not 'no card'",
   summary["funding"] is None and "did not return" in (summary["funding_note"] or ""),
   f"funding={summary['funding']} note={summary['funding_note']}")
ok("  ...and an unknown payment method does not by itself block spending", summary["spend_ok"] is True,
   str(summary["spend_ok"]))
STATE["include_funding_field"] = True
STATE["funding_source_details"] = {"id": "1", "type": "VISA", "display_string": "Visa ending in 4242"}

STATE["account_status"] = 3          # UNSETTLED: the client owes Meta money
summary = __import__("asyncio").run(token_health.refresh_account(acct, db))
ok("an UNSETTLED account cannot spend", summary["spend_ok"] is False, str(summary)[:200])
ok("  ...and Meta's own status word is used", summary["account_status_label"] == "UNSETTLED",
   str(summary["account_status_label"]))
STATE["account_status"] = 1

print("\n=== 8. Graph errors are classified into an action ===")
ok("an expired-token error says reconnect",
   (token_health.classify_graph_error({"error": {"code": 190, "error_subcode": 463}}) or {}).get("kind") == "needs_reconnect")
ok("a permission error says permission_denied",
   (token_health.classify_graph_error({"error": {"code": 200}}) or {}).get("kind") == "permission_denied")
ok("a rate limit says rate_limited",
   (token_health.classify_graph_error({"error": {"code": 17}}) or {}).get("kind") == "rate_limited")
ok("an unrecognised error is not mislabelled", token_health.classify_graph_error({"error": {"code": 12345}}) is None)

# --------------------------------------------------------------------------- 4. the launch gate
print("\n=== 9. a launch is refused when the connection cannot back it ===")


def make_boost(headers, address):
    boost = client.post("/api/boosts", headers=headers, json={
        "address": address, "tier": "bap_shoot_499", "go_live_date": "2026-12-01",
        "campaign_days": 14, "ad_budget_usd": 50.0,
        "property_facts": "4BR/3BA, 2400sqft"}).json()
    post = client.post(f"/api/posts?boost_id={boost['id']}&day=1&caption=Day 1"
                       "&image_url=https://example.com/p1.jpg", headers=headers).json()
    client.patch(f"/api/posts/{post['id']}/approve", headers=headers)
    return boost


def launch(headers, boost, account=ADVERTISER):
    return client.post("/api/launch", headers=headers, json={
        "platform": "meta", "source": "scratch", "boost_id": boost["id"],
        "meta_account_id": account,
        "meta_custom_configs": {
            "campaign": {"name": "Client Listing Boost", "objective": "OUTCOME_TRAFFIC"},
            "adset": {"name": "Client 15mi Radius"},
            "adcreative": {"object_story_spec": {"page_id": "page_900"}},
        },
    }).json()


boost = make_boost(H, "11 Refuse St, Austin TX 78701")

STATE["valid"] = False
reset_calls()
result = launch(H, boost)
ok("a launch on a dead token is refused", result.get("status") == "needs_reconnect", str(result)[:220])
ok("  ...and tells the user to reconnect", "reconnect" in (result.get("detail") or "").lower(), str(result.get("detail")))
ok("  ...and creates NOTHING in the ad account",
   not [c for c in calls if c[1].endswith("/campaigns")], str([c[1] for c in calls]))
db.refresh(acct)
ok("  ...and the refusal is recorded on the account", acct.token_status == "needs_reconnect", str(acct.token_status))

STATE["valid"] = True
STATE["funding_source_details"] = {}
result = launch(H, boost)
ok("a launch on an account with no payment method is refused",
   result.get("status") == "account_not_ready", str(result)[:220])
ok("  ...and says the client's card has to be added in Meta",
   "payment method" in (result.get("detail") or "").lower(), str(result.get("detail")))
ok("  ...and creates NOTHING in the ad account",
   not [c for c in calls if c[1].endswith("/campaigns")], str([c[1] for c in calls]))

STATE["funding_source_details"] = {"id": "1", "type": "VISA", "display_string": "Visa ending in 4242"}
reset_calls()
result = launch(H, boost)
ok("a healthy, funded connection launches", result.get("status") in ("launched", "live", "running"), str(result)[:220])
ok("  ...and the campaign really was created",
   any(c[1].endswith("/campaigns") for c in calls), str([c[1] for c in calls]))

print("\n=== 10. a failed launch cleans up after itself ===")
boost2 = make_boost(H, "22 Rollback Rd, Austin TX 78702")
STATE["fail_adset"] = True
reset_calls()
result = launch(H, boost2)
ok("the failed launch reports failure", result.get("status") == "failed", str(result)[:220])
ok("  ...and names the half-created chain", result.get("created_ids", {}).get("campaign") == "camp_1",
   str(result.get("created_ids")))
ok("  ...and deletes the orphan campaign instead of leaving it behind",
   ("DELETE", "/camp_1", {}) in calls, str([c for c in calls if "/camp" in c[1]]))
ok("  ...and reports what it cleaned up", "campaign:camp_1" in (result.get("rolled_back") or []),
   str(result.get("rolled_back")))
ok("  ...and the ad set error is passed through with its subcode",
   "subcode 1815857" in (result.get("detail") or ""), str(result.get("detail")))
STATE["fail_adset"] = False

print("\n=== 11. the demo path still works, untouched ===")
H2 = sign_up("health-demo@example.com")
client.post("/api/ad-accounts", headers=H2, json={
    "platform": "meta", "advertiser_id": "act_sim_health", "account_name": "Demo", "budget": 1000.0})
boost3 = make_boost(H2, "33 Demo Dr, Austin TX 78703")
reset_calls()
result = launch(H2, boost3, account="act_sim_health")
ok("a simulated account still launches without any Meta call", result.get("status") in ("launched", "live", "running"),
   str(result)[:220])
ok("  ...and nothing was sent to Meta", not [c for c in calls if c[1].startswith(f"/{ADVERTISER}")],
   str([c[1] for c in calls]))

print("\n=== 12. the scheduler can check every connection ===")
r = client.post("/api/oauth/meta/check-all")
ok("the sweep refuses to run without the system token", r.status_code == 403, f"{r.status_code} {r.text[:80]}")
r = client.post("/api/oauth/meta/check-all", headers={"X-Resmara-Token": settings.PUBLISH_TOKEN or "unset"})
ok("with the token it sweeps every connected account",
   r.status_code == 200 and r.json().get("checked", 0) >= 1, f"{r.status_code} {r.text[:120]}")
ok("  ...and reports the accounts it found",
   isinstance(r.json().get("checks"), list) and r.json()["checks"][0].get("account"), r.text[:160])
ok("  ...and does not count demo connections as spending problems",
   r.json().get("simulated", 0) >= 1
   and not [a for a in r.json().get("not_ready_to_spend", []) if "demo" in a.lower()], r.text[:200])

server.shutdown()
print(f"\n{checks} checks, {failures} failed.")
if failures:
    raise SystemExit(1)
print("ALL TOKEN HEALTH TESTS PASSED")
