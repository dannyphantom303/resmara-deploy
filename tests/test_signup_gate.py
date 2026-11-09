"""Signup has to be closed on a public domain during the beta.

Two things are being protected here: a stranger cannot create an account, and the owners
cannot lock themselves out — an allowlisted address gets in even if the code is lost, and an
environment with neither setting behaves exactly as before (local dev, the rest of the suite).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services.access import parse_allowlist, signup_block_reason  # noqa: E402

# The suite reuses this repo's dev database, which may predate a column the User model now
# maps. Startup does this in the running app; a bare TestClient does not fire startup.
from app.db.session import Base, engine  # noqa: E402
from app.db.migrate import migrate  # noqa: E402

Base.metadata.create_all(bind=engine)
migrate()

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


# ---- the decision itself -------------------------------------------------------------
check("an unset gate lets everyone through",
      signup_block_reason("someone@example.com", None, "", "") is None)
check("an address on the list gets in without a code",
      signup_block_reason("Dan@Example.com", None, "dan@example.com, partner@example.com", "s3cret") is None)
check("a stranger with no code is stopped",
      signup_block_reason("stranger@example.com", None, "dan@example.com", "s3cret") is not None)
check("a stranger with the wrong code is stopped",
      signup_block_reason("stranger@example.com", "nope", None, "s3cret") is not None)
check("a stranger with the right code gets in",
      signup_block_reason("partner@example.com", "s3cret", "", "s3cret") is None)
check("code comparison tolerates surrounding spaces",
      signup_block_reason("partner@example.com", "  s3cret ", None, "s3cret") is None)
check("the refusal explains what to do",
      "private beta" in (signup_block_reason("x@example.com", None, "", "s3cret") or "").lower())
check("the allowlist parser accepts commas, spaces and semicolons",
      parse_allowlist("a@x.com, b@x.com; c@x.com\nd@x.com") == {"a@x.com", "b@x.com", "c@x.com", "d@x.com"})

# ---- through the real endpoint -------------------------------------------------------
# TestClient without a context manager does not run startup, so the idempotent column pass
# that the live app does at boot has to happen here; otherwise a database created before a
# column existed answers with "no such column: users.brand".
from app.db.migrate import migrate  # noqa: E402

migrate()
client = TestClient(app)
before = (settings.SIGNUP_EMAILS, settings.SIGNUP_CODE, settings.ADMIN_EMAILS)
try:
    settings.SIGNUP_EMAILS = "owner@example.com"
    settings.SIGNUP_CODE = "beta-code-123"
    settings.ADMIN_EMAILS = "second.owner@example.com"

    blocked = client.post("/api/auth/register", json={
        "email": "stranger@example.com", "password": "Hunter2Hunter2", "name": "Stranger"})
    check("register is refused without an invite", blocked.status_code == 403, str(blocked.status_code))
    check("and the reason is readable", "private beta" in blocked.text.lower(), blocked.text[:120])

    wrong = client.post("/api/auth/register", json={
        "email": "stranger@example.com", "password": "Hunter2Hunter2", "invite_code": "guess"})
    check("a wrong invite code is refused", wrong.status_code == 403, str(wrong.status_code))

    invited = client.post("/api/auth/register", json={
        "email": "partner@example.com", "password": "Hunter2Hunter2", "invite_code": "beta-code-123"})
    check("the right invite code creates the account", invited.status_code == 201, invited.text[:120])

    owner = client.post("/api/auth/register", json={
        "email": "owner@example.com", "password": "Hunter2Hunter2"})
    check("an allowlisted owner needs no code", owner.status_code == 201, owner.text[:120])

    # A second operator is an env-var edit, not a database script: the address signs up
    # without an invite code and comes out of registration already an operator.
    second = client.post("/api/auth/register", json={
        "email": "second.owner@example.com", "password": "Hunter2Hunter2", "name": "Second"})
    check("a listed operator signs up without an invite", second.status_code == 201, second.text[:160])
    check("and is an operator immediately", second.json().get("is_admin") is True, str(second.json()))
    first = client.post("/api/auth/register", json={
        "email": "plain@example.com", "password": "Hunter2Hunter2", "invite_code": "beta-code-123"})
    check("an ordinary invited account is not an operator",
          first.status_code == 201 and first.json().get("is_admin") is False, str(first.json())[:160])

    # An account that predates the setting is promoted the next time it signs in.
    from app.db.session import SessionLocal, User
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == "second.owner@example.com").update({"is_admin": False})
        db.commit()
    finally:
        db.close()
    relogin = client.post("/api/auth/login",
                          data={"username": "second.owner@example.com", "password": "Hunter2Hunter2"})
    check("signing in promotes a pre-existing account", relogin.status_code == 200, relogin.text[:120])
    db = SessionLocal()
    try:
        promoted = db.query(User).filter(User.email == "second.owner@example.com").first()
        check("and the operator flag sticks", bool(promoted and promoted.is_admin), "not admin")
    finally:
        db.close()

    check("robots.txt keeps the beta out of search",
          client.get("/robots.txt").text.strip().endswith("Disallow: /"), client.get("/robots.txt").text)
finally:
    settings.SIGNUP_EMAILS, settings.SIGNUP_CODE, settings.ADMIN_EMAILS = before

    from app.db.session import SessionLocal, User
    db = SessionLocal()
    try:
        for email in ("partner@example.com", "owner@example.com",
                      "second.owner@example.com", "plain@example.com"):
            db.query(User).filter(User.email == email).delete()
        db.commit()
    finally:
        db.close()

check("robots.txt opens up again when the gate is off",
      client.get("/robots.txt").text.strip().endswith("Allow: /"), client.get("/robots.txt").text)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
    sys.exit(1)
print("ok — signup gate")
