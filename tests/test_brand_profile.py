"""A brand profile must outlive the browser it was typed in.

The bug: a customer filled in My Brand, signed in, and the page came back empty — signing in
replaced the whole local state with a blank one, and the profile had never been anywhere but
that browser's localStorage. This pins both halves of the fix:

  * the account keeps the profile (GET/PUT /api/auth/me/brand, authenticated, size-capped);
  * signing in on a second, empty browser returns the same profile instead of a blank form.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.NamedTemporaryFile(prefix="resmara-brand-", suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["SECRET_KEY"] = "test-secret-key-for-brand-profile-000000"
os.environ["RESMARA_ADMIN_EMAILS"] = "owner@example.com"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


client = TestClient(app)

# --- an account ------------------------------------------------------------------
r = client.post("/api/auth/register",
                json={"email": "owner@example.com", "password": "brandtest123", "name": "Dana Agent"})
check("an admin-allowlisted account can be created", r.status_code == 201, f"{r.status_code} {r.text[:120]}")

r = client.post("/api/auth/login", data={"username": "owner@example.com", "password": "brandtest123"})
check("login answers a token", r.status_code == 200 and r.json().get("access_token"), r.text[:120])
token = r.json().get("access_token", "")
auth = {"Authorization": f"Bearer {token}"}

# --- the profile starts empty, not missing ---------------------------------------
r = client.get("/api/auth/me/brand", headers=auth)
check("a new account has an empty profile, not an error", r.status_code == 200 and r.json().get("brand") == {},
      f"{r.status_code} {r.text[:120]}")

# --- write it ---------------------------------------------------------------------
profile = {
    "agent": "Dana Agent", "brokerage": "Morgan & Co.", "license": "TX-0123456",
    "website": "https://dana.example.com", "market": "Austin, TX",
    "colours": "#143a50,#d8c8ac", "colour": "#143a50", "voice": "Warm, direct",
    "brandLink": "https://instagram.com/dana",
}
r = client.put("/api/auth/me/brand", headers=auth, json={"brand": profile})
check("the profile is stored on the account", r.status_code == 200 and r.json()["brand"]["brokerage"] == "Morgan & Co.",
      f"{r.status_code} {r.text[:160]}")

# --- it comes back on another browser / after signing in again -------------------
r = client.post("/api/auth/login", data={"username": "owner@example.com", "password": "brandtest123"})
fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
got = client.get("/api/auth/me/brand", headers=fresh).json()["brand"]
check("a fresh sign-in reads the same profile back", got == profile, f"{got}")

# --- it is the account's, not the world's ----------------------------------------
check("no session, no profile", client.get("/api/auth/me/brand").status_code == 401,
      str(client.get("/api/auth/me/brand").status_code))
check("no session, no write",
      client.put("/api/auth/me/brand", json={"brand": {"agent": "Someone Else"}}).status_code == 401)

# --- a bad payload is refused, not stored -----------------------------------------
check("a non-object brand is refused",
      client.put("/api/auth/me/brand", headers=auth, json={"brand": "not an object"}).status_code == 400)
huge = {"agent": "x" * 40000}
check("an oversized profile is refused by name",
      client.put("/api/auth/me/brand", headers=auth, json={"brand": huge}).status_code == 413)
after = client.get("/api/auth/me/brand", headers=auth).json()["brand"]
check("a refused write leaves the stored profile alone", after == profile, f"{list(after)[:4]}")

# --- a second account cannot see the first account's profile ----------------------
r = client.post("/api/auth/register",
                json={"email": "second@example.com", "password": "brandtest123", "name": "Other"})
if r.status_code in (201, 403):
    # 403 is the beta gate — that is the door working, so the isolation check is skipped
    # rather than asserted against an unauthenticated 401.
    if r.status_code == 201:
        r2 = client.post("/api/auth/login", data={"username": "second@example.com", "password": "brandtest123"})
        other = {"Authorization": f"Bearer {r2.json()['access_token']}"}
        check("another account has its own empty profile",
              client.get("/api/auth/me/brand", headers=other).json()["brand"] == {})
    else:
        print("skip another account is gated by the beta invite code (403)")

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL BRAND PROFILE TESTS PASSED")
