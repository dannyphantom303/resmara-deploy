#!/usr/bin/env python3
"""POST /build must not hold a request open: it answers 202 and the run continues in the
background, followed through GET /build-status.

Why this shape: a real build is four model calls and takes minutes. Hosted platforms cut the
request (Render: 502 at ~100s) and that cancelled the request task mid-build, so a campaign
came back with zero posts and no error of its own.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS += 1


def main() -> int:
    db = tempfile.mkdtemp(prefix="resmara_async_build_")
    os.environ["DATABASE_URL"] = f"sqlite:///{db}/app.db"
    os.environ["UPLOAD_DIR"] = str(Path(db) / "uploads")
    # No engine endpoint -> the offline fixture path, so this test spends nothing.
    for key in ("RESMARA_ENGINE_BASE_URL", "RESMARA_ENGINE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        os.environ.pop(key, None)
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        del sys.modules[mod]

    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.main import app

    # Hermetic: no key, no local endpoint, simulate on — the offline fixture path.
    settings.SIMULATE = True
    settings.OPENAI_API_KEY = ""

    with TestClient(app) as client:
        reg = client.post("/api/auth/register", json={
            "email": f"async{int(time.time())}@example.com", "password": "async-pass-12345", "name": "Async"})
        check("register", reg.status_code in (200, 201), str(reg.status_code))
        login = client.post("/api/auth/login", data={
            "username": reg.json()["email"], "password": "async-pass-12345"})
        check("login", login.status_code == 200, str(login.status_code))
        token = login.json().get("access_token")
        h = {"Authorization": f"Bearer {token}"}

        made = client.post("/api/boosts", headers=h, json={
            "address": "706 Congress Ave, Austin TX", "tier": "standard",
            "campaign_days": 14, "ad_budget_usd": 250})
        check("create a boost", made.status_code in (200, 201), str(made.status_code))
        boost_id = made.json()["id"]

        # This suite is about the async build, not the price. A campaign is $49 and an unpaid
        # one is refused with 402 (covered in test_billing), so mark this one paid here rather
        # than making the account an admin and hiding a real gate.
        from datetime import datetime

        from app.db.session import SessionLocal, Boost
        db = SessionLocal()
        try:
            row = db.query(Boost).filter(Boost.id == boost_id).first()
            row.paid_at = datetime.utcnow()
            row.paid_amount_cents = 4900
            db.commit()
        finally:
            db.close()

        t0 = time.time()
        started = client.post(f"/api/boosts/{boost_id}/build", headers=h, json={"force": True})
        elapsed = time.time() - t0
        check("POST /build answers 202 at once", started.status_code == 202, str(started.status_code))
        check("POST /build does not wait for the engine", elapsed < 5, f"{elapsed:.1f}s")
        check("the body says the run is going", started.json().get("status") == "running", str(started.json()))

        status = {}
        deadline = time.time() + 120
        while time.time() < deadline:
            status = client.get(f"/api/boosts/{boost_id}/build-status", headers=h).json()
            if status.get("status") in ("done", "error"):
                break
            time.sleep(0.5)

        check("the background run finishes", status.get("status") == "done", str(status))
        check("the run reports the posts it wrote", (status.get("posts_created") or 0) == 14, str(status.get("posts_created")))
        posts = client.get(f"/api/boosts/{boost_id}/posts", headers=h).json()
        check("the posts are readable afterwards", len(posts) == 14, str(len(posts)))

        # A build that is genuinely running must read as running. This is what the live site got
        # wrong: the status came from a dict in the web process, so the first poll after a deploy
        # saw an empty dict, called a healthy build "interrupted" and marked it Build failed. The
        # answer is read from the event log now, so any process gives the same one.
        from datetime import timedelta
        from app.api.engine import _durable_build_state
        from app.db.session import Boost, Event, Post, SessionLocal

        fresh = SessionLocal()
        try:
            boost_row = fresh.query(Boost).filter(Boost.id == boost_id).first()
            fresh.query(Post).filter(Post.boost_id == boost_id).delete()
            fresh.query(Event).filter(Event.boost_id == boost_id).delete()
            fresh.add(Event(user_id=boost_row.user_id, boost_id=boost_id, event_type="build_started",
                            payload={"force": True}))
            fresh.commit()
            state = _durable_build_state(fresh, boost_row)
            check("a build that just started reads as running", state.get("status") == "running", str(state))

            fresh.query(Event).filter(Event.boost_id == boost_id).update(
                {"created_at": datetime.utcnow() - timedelta(seconds=16 * 60)})
            fresh.commit()
            stale = _durable_build_state(fresh, boost_row)
            check("a run past the deadline reads as interrupted",
                  stale.get("status") == "error" and stale.get("interrupted") is True, str(stale))

            fresh.add(Event(user_id=boost_row.user_id, boost_id=boost_id, event_type="campaign_built",
                            payload={"posts": 14, "source": "offline"}))
            fresh.commit()
            done = _durable_build_state(fresh, boost_row)
            check("a finished build reads as done", done.get("status") == "done", str(done))
        finally:
            fresh.close()

        second = client.post(f"/api/boosts/{boost_id}/build", headers=h, json={"force": True})
        check("a forced rebuild can start again", second.status_code == 202, str(second.status_code))

    print(f"{'FAILED' if FAILS else 'ok'} — async build endpoint")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
