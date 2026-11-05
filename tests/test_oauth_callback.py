"""The Meta OAuth callback, tested the way a browser actually reaches it.

Why this test exists: Meta redirects the *browser* to /api/oauth/meta/callback, and that
request carries no Authorization header. The callback used to depend on `get_current_user`,
so a real connect could never finish — every attempt 401'd while the simulated
`demo-connect` kept working, which is exactly the kind of failure a demo hides. This test
drives the flow with NO credentials on the callback at all and a mock Graph endpoint, and
proves the token is stored, the long-lived swap happened, and the page/IG account came back.

Runs hermetically: temp sqlite DB, local mock Graph server, no network.
"""

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from urllib.parse import parse_qs, urlparse

# --- environment BEFORE the app is imported (config reads env at import time) ---
_tmp = tempfile.NamedTemporaryFile(prefix="resmara-oauth-", suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ.pop("RESMARA_SIMULATE", None)
# A Meta app this test owns: without an app id /connect answers 400 instead of handing back an
# authorization URL, and a clean runner has no .env to borrow one from. The secret is a dummy -
# the token exchange goes to the mock Graph below.
os.environ["META_CLIENT_ID"] = "app_test_0000000000"
os.environ["META_CLIENT_SECRET"] = "secret_test_0000000000"
os.environ["META_SCOPES"] = "ads_management,business_management,pages_read_engagement,pages_show_list"
os.environ.pop("META_REDIRECT_URI", None)

# --- mock Graph API ---
SHORT_TOKEN = "short-lived-from-code"
LONG_TOKEN = "long-lived-60-day-token"
calls = []


class Graph(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        calls.append((u.path, q))
        if u.path == "/oauth/access_token":
            if q.get("grant_type") == "fb_exchange_token":
                self._json({"access_token": LONG_TOKEN, "expires_in": 5183944})
            else:
                self._json({"access_token": SHORT_TOKEN, "expires_in": 5183})
        elif u.path == "/me/adaccounts":
            self._json({"data": [{"id": "act_555", "name": "Test Ad Account",
                                 "currency": "USD", "account_status": 1}]})
        elif u.path == "/me/accounts":
            self._json({"data": [{"id": "page_900", "name": "Test Page",
                                  "instagram_business_account": {"id": "ig_700", "username": "test_page"}}]})
        else:
            self._json({"error": {"message": "unexpected " + u.path}}, 404)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer(("127.0.0.1", 0), Graph)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["GRAPH_API_BASE"] = f"http://127.0.0.1:{port}"

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                            # noqa: E402
from app.db.session import Base, engine, SessionLocal, User, AdAccount  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)

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


# --- a customer signs up ---
email = "oauth-browser@example.com"
pw = "oauth-pass-12345"
client.post("/api/auth/register", json={"email": email, "password": pw, "name": "OAuth Check"})
token = client.post("/api/auth/login", data={"username": email, "password": pw}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}
db = SessionLocal()
user = db.query(User).filter(User.email == email).first()

# --- 1. the app hands the browser a consent URL with a signed state ---
r = client.get("/api/oauth/meta/connect", headers=H)
connect = r.json()
ok("connect issues a Meta consent URL", r.status_code == 200 and connect.get("redirect_url", "").startswith(
    "https://www.facebook.com/v19.0/dialog/oauth?"), str(connect)[:120])
ok("the state names the signed-in user", connect.get("state", "").startswith(f"{user.id}:"), connect.get("state", "")[:24])
consent_url = urllib.parse.unquote(connect.get("redirect_url", ""))   # Meta gets it percent-encoded
ok("the consent URL carries the mount-correct redirect_uri",
   "/resmara/api/oauth/meta/callback" in consent_url, consent_url[:140])
# The scope list is configurable (META_SCOPES) because Meta rejects the WHOLE consent
# dialog with "Invalid Scopes" if any single permission is not enabled for the app's use
# cases. Assert what the app actually sends, and that the ads permission is always there.
requested = parse_qs(urlparse(connect.get("redirect_url", "")).query).get("scope", [""])[0].split(",")
from app.api.oauth import META_SCOPES  # noqa: E402
ok("it asks for exactly the configured scopes", requested == META_SCOPES,
   f"asked={requested} configured={META_SCOPES}")
ok("  ...and never drops the ads permission", "ads_management" in requested, str(requested))

# --- 2. Meta bounces the browser back: NO Authorization header on this request ---
state = connect["state"]
r = client.get("/api/oauth/meta/callback", params={"code": "AQD-fake-code", "state": state, "format": "json"})
body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
ok("the callback completes with no bearer token (the browser case)",
   r.status_code == 200 and isinstance(body, dict) and body.get("meta") == "connected", f"{r.status_code} {str(body)[:160]}")
ok("  ...and reports the ad account it stored", body.get("accounts") == 1, str(body)[:160])
ok("  ...and the Page + linked Instagram account", body.get("page_id") == "page_900" and body.get("ig") == "ig_700",
   str(body)[:160])

# --- 3. the stored token is the LONG-LIVED one, not the 1-hour code token ---
db.expire_all()
acct = db.query(AdAccount).filter(AdAccount.user_id == user.id).first()
ok("the ad account row exists for that user", acct is not None and acct.advertiser_id == "act_555",
   acct.advertiser_id if acct else "no row")
ok("the stored token is the long-lived one, not the code token",
   acct is not None and acct.access_token == LONG_TOKEN, "short token stored" if acct and acct.access_token == SHORT_TOKEN else "other")
ok("  ...because the app asked Meta to extend it",
   any(q.get("grant_type") == "fb_exchange_token" for _, q in calls), str([p for p, _ in calls]))
ok("the exchange sent the redirect_uri and never leaked the secret to the browser",
   any(q.get("redirect_uri", "").endswith("/resmara/api/oauth/meta/callback") for _, q in calls)
   and "client_secret" not in r.text, "redirect_uri missing" if not r.text else "secret in response")
ok("the account is no longer treated as simulated", not __import__(
    "app.services.ad_platforms", fromlist=["x"]).is_simulated_account(acct))
ok("the Page that will carry the ad creative is stored on the account",
   acct is not None and acct.page_id == "page_900", str(getattr(acct, "page_id", None)))
ok("the linked Instagram professional account is stored on the account",
   acct is not None and acct.ig_user_id == "ig_700", str(getattr(acct, "ig_user_id", None)))
ok("the long-lived token's expiry is persisted (not left null)",
   acct is not None and acct.token_expires_at is not None, str(getattr(acct, "token_expires_at", None)))

# --- 4. a forged state is refused, and the refusal is honest ---
r = client.get("/api/oauth/meta/callback", params={"code": "x", "state": f"{user.id}:deadbeef", "format": "json"})
ok("a state that is not signed by this app is refused", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
r = client.get("/api/oauth/meta/callback", params={"code": "x", "state": "not-a-state", "format": "json"})
ok("a malformed state is refused", r.status_code == 400, f"{r.status_code} {r.text[:80]}")

# --- 5. a browser never sees raw JSON: it is bounced back into the app ---
r = client.get("/api/oauth/meta/callback", params={"code": "AQD-fake-code", "state": state},
               follow_redirects=False)
ok("a plain browser hit is redirected into the app",
   r.status_code == 302 and "meta=connected" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')}")

# --- 6. the user cancelling consent is reported, not swallowed ---
r = client.get("/api/oauth/meta/callback",
               params={"error": "access_denied", "error_description": "User denied", "state": state},
               follow_redirects=False)
ok("declining consent comes back as an explained error",
   r.status_code == 302 and "meta=error" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')}")

server.shutdown()
print(f"\n{checks} checks, {failures} failed.")
if failures:
    raise SystemExit(1)
print("ALL OAUTH CALLBACK TESTS PASSED")
