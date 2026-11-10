"""A customer must be able to clear their campaign list without losing what matters.

Two different needs, two different answers:

  * hide  — reversible, a flag on the campaign; the report stays readable;
  * delete — Resmara's copy of the campaign and the content built for it, gone.

Both are scoped to the account that owns the campaign, and a paid campaign cannot be deleted:
the order is the record that money changed hands, and it must survive the campaign.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.NamedTemporaryFile(prefix="resmara-campaigns-", suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["SECRET_KEY"] = "test-secret-key-for-campaign-lifecycle-0000"
os.environ["RESMARA_ADMIN_EMAILS"] = "owner@example.com"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.migrate import migrate  # noqa: E402
from app.db.session import Base, Boost, Order, Post, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)
migrate()

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


client = TestClient(app)


def account(email):
    r = client.post("/api/auth/register",
                    json={"email": email, "password": "campaigntest123", "name": "Dana"})
    if r.status_code == 403:
        # The beta invite gate refuses a second public signup. This test is about ownership,
        # not about the door, so the second account is created the way support would create it.
        from app.core.security import get_password_hash
        from app.db.session import User
        db = SessionLocal()
        if not db.query(User).filter(User.email == email).first():
            db.add(User(email=email, name="Dana", hashed_password=get_password_hash("campaigntest123")))
            db.commit()
        db.close()
    r = client.post("/api/auth/login", data={"username": email, "password": "campaigntest123"})
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


owner = account("owner@example.com")
other = account("other@example.com")

# --- a campaign with content, owned by the first account --------------------------
db = SessionLocal()
boost = Boost(address="14 Cedar Lane, Austin TX", user_id=1, stage="PENDING", hidden=False)
db.add(boost)
db.commit()
boost_id = boost.id
db.add_all([Post(boost_id=boost_id, day=1, caption="Just listed"),
            Post(boost_id=boost_id, day=2, caption="Kitchen")])
db.commit()
db.close()

r = client.get("/api/boosts", headers=owner)
check("the owner sees the campaign", r.status_code == 200 and [b["id"] for b in r.json()] == [boost_id],
      f"{r.status_code} {r.text[:120]}")
check("a new campaign is not hidden", r.json()[0]["hidden"] is False)

# --- hide, then find it again -----------------------------------------------------
r = client.post(f"/api/boosts/{boost_id}/hide", headers=owner)
check("hiding answers the campaign, flagged hidden", r.status_code == 200 and r.json()["hidden"] is True,
      f"{r.status_code} {r.text[:160]}")
listed = client.get("/api/boosts", headers=owner).json()
check("a hidden campaign is still listed, still openable", len(listed) == 1 and listed[0]["hidden"] is True,
      f"{listed}")
check("hiding leaves the customer's posts alone",
      len(client.get(f"/api/posts/{boost_id}", headers=owner).json()) == 2)

r = client.post(f"/api/boosts/{boost_id}/hide?hidden=false", headers=owner)
check("it can be brought back", r.status_code == 200 and r.json()["hidden"] is False, r.text[:120])

# --- someone else's campaign is not addressable ----------------------------------
check("another account cannot hide it", client.post(f"/api/boosts/{boost_id}/hide", headers=other).status_code == 404)
check("another account cannot delete it", client.delete(f"/api/boosts/{boost_id}", headers=other).status_code == 404)
check("no session, no delete", client.delete(f"/api/boosts/{boost_id}").status_code == 401)

# --- a paid campaign refuses deletion --------------------------------------------
db = SessionLocal()
db.add(Order(user_id=1, boost_id=boost_id, amount_cents=4900, status="paid"))
db.commit()
db.close()
r = client.delete(f"/api/boosts/{boost_id}", headers=owner)
check("a paid campaign cannot be deleted; the payment record stays",
      r.status_code == 409 and "paid" in r.json().get("detail", "").lower(), f"{r.status_code} {r.text[:160]}")
check("the refused delete changed nothing",
      client.get(f"/api/boosts/{boost_id}", headers=owner).status_code == 200)

# --- an unpaid campaign deletes, content and all ---------------------------------
db = SessionLocal()
db.query(Order).filter(Order.boost_id == boost_id).delete()
db.commit()
db.close()

r = client.delete(f"/api/boosts/{boost_id}", headers=owner)
body = r.json() if r.status_code == 200 else {}
check("an unpaid campaign deletes", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
check("its posts go with it", body.get("removed", {}).get("posts") == 2, f"{body.get('removed')}")
check("the campaign is gone from the list", client.get("/api/boosts", headers=owner).json() == [])
check("and cannot be opened by id", client.get(f"/api/boosts/{boost_id}", headers=owner).status_code == 404)

db = SessionLocal()
left = db.query(Post).filter(Post.boost_id == boost_id).count()
db.close()
check("no orphaned posts are left behind", left == 0, str(left))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL CAMPAIGN LIFECYCLE TESTS PASSED")
