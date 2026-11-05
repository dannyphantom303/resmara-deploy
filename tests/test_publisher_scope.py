"""The publish scope filter: the scheduler sees every boost, "publish now" sees one.

Run:
    cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_publisher_scope.py

Pure selection test - it never publishes, so no network and no mock server.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_SCRATCH = "/Users/dan/.hermes/profiles/dev/cache/scratch"
if not os.path.isdir(_SCRATCH):
    _SCRATCH = tempfile.gettempdir()
TMP = tempfile.mkdtemp(prefix="resmara_scope_", dir=_SCRATCH)
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TMP, "scope.db")
os.environ["RESMARA_ENV"] = "test"

from app.services import publisher  # noqa: E402
from app.db.session import Base, engine, SessionLocal, User, AdAccount, Boost, Post  # noqa: E402

Base.metadata.create_all(bind=engine)
db = SessionLocal()
NOW = "2030-01-01T00:00:00"
checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(f"{'ok  ' if ok else 'FAIL'} - {name}" + (f"  [{detail}]" if detail else ""))


user = User(email="scope@example.com", hashed_password="x", name="Scope")
db.add(user)
db.commit()
acct = AdAccount(user_id=user.id, platform="meta", advertiser_id="act_scope",
                 account_name="Scope", budget=100.0, is_active=True)
db.add(acct)
db.commit()


def mk_boost(addr):
    b = Boost(user_id=user.id, ad_account_id=acct.id, address=addr,
              stage="LIVE", main_status="Live")
    db.add(b)
    db.commit()
    return b


def mk_post(b, day, status="scheduled", client="approved", at=NOW):
    p = Post(boost_id=b.id, day=day, slot=1, kind="static", caption="c",
             client_status=client, publish_status=status, publish_at=at,
             publish_target="facebook")
    db.add(p)
    db.commit()
    return p


b1, b2 = mk_boost("1 A St"), mk_boost("2 B St")
p1 = mk_post(b1, 1)
p2 = mk_post(b2, 1)
mk_post(b2, 2)

every = publisher._due_posts(db, NOW, 50)
one = publisher._due_posts(db, NOW, 50, boost_id=b1.id)
check("the scheduler sees every boost's due posts", len(every) == 3,
      f"{[p.id for p in every]}")
check("boost_id narrows the selection to one campaign",
      len(one) == 1 and one[0].id == p1.id, f"{[p.id for p in one]}")

# A withdrawn post in the scoped boost must still be excluded.
p1.client_status = "change_requested"
db.commit()
check("a withdrawn post is excluded from the scoped run",
      len(publisher._due_posts(db, NOW, 50, boost_id=b1.id)) == 0)
p1.client_status = "approved"
db.commit()  # the filter runs on committed state, so commit before asserting
check("and comes back once re-approved",
      len(publisher._due_posts(db, NOW, 50, boost_id=b1.id)) == 1)

# An inactive ad account takes the whole boost out, scoped or not.
acct.is_active = False
db.commit()
check("an inactive ad account stops publishing for that boost",
      len(publisher._due_posts(db, NOW, 50, boost_id=b1.id)) == 0
      and len(publisher._due_posts(db, NOW, 50)) == 0)
acct.is_active = True
db.commit()

# A different boost keeps publishing regardless.
scoped_b2 = publisher._due_posts(db, NOW, 50, boost_id=b2.id)
check("the other boost is still fully selectable on its own",
      len(scoped_b2) == 2 and all(p.boost_id == b2.id for p in scoped_b2),
      f"{[p.id for p in scoped_b2]}")

print(f"\n{sum(checks)} passed, {len(checks) - sum(checks)} failed")
print("ALL PUBLISHER SCOPE TESTS PASSED" if all(checks) else "PUBLISHER SCOPE TESTS FAILED")
sys.exit(0 if all(checks) else 1)
