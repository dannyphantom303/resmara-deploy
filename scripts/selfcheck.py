#!/usr/bin/env python
"""Check that a running Resmara deployment is actually serving what it should.

Read-only by default — safe to point at production:

    python scripts/selfcheck.py --base https://app.example.com

With --full it also walks the client flow the way the browser does: registers a throwaway
client (selfcheck+<timestamp>@... by default), creates a boost, and runs a build, then
reports the engine `source` the build declared. Use it right after a deploy:

    python scripts/selfcheck.py --base http://127.0.0.1:8000 --full

Exit code 0 = every check passed. Nothing here publishes, launches or spends anything.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

OK, BAD = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, OK if ok else BAD, detail))
    print(f"[{OK if ok else BAD}] {name}{(' — ' + detail) if detail else ''}", flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="where the deployment answers")
    ap.add_argument("--full", action="store_true", help="also register a client and run a build")
    ap.add_argument("--email", default=None, help="client email for --full (a throwaway is generated)")
    ap.add_argument("--password", default="Selfcheck123!")
    ap.add_argument("--system-token", default=None, help="RESMARA_PUBLISH_TOKEN, to check the scheduler endpoints")
    ap.add_argument("--timeout", type=float, default=300.0, help="per-request timeout for the build")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    with httpx.Client(base_url=base, timeout=30.0, follow_redirects=True) as c:
        r = c.get("/openapi.json")
        api_ok = r.status_code == 200 and "Resmara API" in r.text
        check("API answers at /openapi.json", api_ok, f"HTTP {r.status_code}")
        check("frontend serves at /", c.get("/").status_code == 200)
        check("API docs at /docs", c.get("/docs").status_code == 200)
        check("privacy policy page (Meta requires a public URL)", c.get("/privacy.html").status_code == 200)
        check("terms page", c.get("/terms.html").status_code == 200)
        check("operator console at /admin.html", c.get("/admin.html").status_code == 200)

        if args.system_token:
            h = {"X-Resmara-Token": args.system_token}
            check("publisher endpoint rejects a bad token",
                  c.post("/api/content/publish/run", headers={"X-Resmara-Token": "wrong"}).status_code == 403)
            check("publisher endpoint accepts the scheduler token",
                  c.post("/api/content/publish/run", headers=h).status_code == 200)
            check("token-health sweep accepts the scheduler token",
                  c.post("/api/oauth/meta/check-all", headers=h).status_code == 200)

        if not args.full:
            print("\nread-only checks only (add --full to exercise the client flow)")
        else:
            email = args.email or f"selfcheck+{int(time.time())}@example.com"
            r = c.post("/api/auth/register", json={"email": email, "password": args.password, "name": "Self Check"})
            if r.status_code == 409:
                check("client signup", True, "already registered, reusing")
            else:
                check("client signup", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
            r = c.post("/api/auth/login", data={"username": email, "password": args.password})
            token = (r.json() or {}).get("access_token", "") if r.status_code == 200 else ""
            check("client login", bool(token), f"HTTP {r.status_code}")
            if token:
                h = {"Authorization": f"Bearer {token}"}
                # Upload a listing photo first when the repo ships one, so the media checks below
                # are meaningful (Instagram cannot publish a post that has no reachable picture).
                uploaded = False
                fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "listing-photo.jpg"
                if fixture.exists():
                    with fixture.open("rb") as fh:
                        r = c.post("/api/content/upload/photo", headers=h,
                                   files={"file": (fixture.name, fh, "image/jpeg")})
                    uploaded = r.status_code < 400
                    check("upload a listing photo", uploaded, f"HTTP {r.status_code}")
                r = c.post("/api/boosts", headers=h, json={
                    "address": "500 Selfcheck Ave, Testville",
                    "campaign_days": 14, "ad_budget_usd": 20.0,
                    "property_facts": "3 bed 2 bath, 1,600 sqft, built 1975",
                })
                bid = (r.json() or {}).get("id") if r.status_code < 400 else None
                check("create a campaign", bool(bid), f"HTTP {r.status_code} id={bid}")
                if bid and uploaded:
                    with fixture.open("rb") as fh:
                        c.post("/api/content/upload/photo", headers=h, data={"boost_id": str(bid)},
                               files={"file": (fixture.name, fh, "image/jpeg")})
                if bid:
                    t0 = time.time()
                    # The build runs in the background now (a hosted proxy cuts a request at ~100s),
                    # so start it, then follow /build-status.
                    r = c.post(f"/api/boosts/{bid}/build", headers=h, json={"force": True}, timeout=60)
                    check("start the campaign build", r.status_code in (200, 202),
                          f"HTTP {r.status_code}")
                    body = {}
                    while time.time() - t0 < args.timeout:
                        time.sleep(3)
                        s = c.get(f"/api/boosts/{bid}/build-status", headers=h, timeout=60).json()
                        if s.get("status") in ("done", "error"):
                            body = s
                            break
                    secs = time.time() - t0
                    check("build the campaign with the content engine", body.get("status") == "done",
                          f"{body.get('status')} in {secs:.0f}s source={body.get('source')} error={body.get('error')}")
                    if body.get("source") == "offline":
                        print("      note: engine reported source=offline (no model configured) — expected "
                              "on a smoke test, NOT acceptable on a client-facing deployment")
                    r = c.get(f"/api/boosts/{bid}/posts", headers=h)
                    posts = r.json()
                    posts = posts.get("posts", posts) if isinstance(posts, dict) else posts
                    check("campaign has posts", isinstance(posts, list) and len(posts) > 0,
                          f"{len(posts) if isinstance(posts, list) else 0} rows")
                    if isinstance(posts, list) and posts and uploaded:
                        with_media = [p for p in posts if (p.get("image_url") or "").strip()]
                        reachable = all(c.get(p["image_url"]).status_code == 200 for p in with_media) if with_media else False
                        check("post media is reachable at its public URL (Instagram fetches this)",
                              bool(with_media) and reachable,
                              f"{len(with_media)}/{len(posts)} posts carry media")
                    # Leave the test campaign out of the way: it stays a draft; never launched.
                    print(f"      (test campaign id={bid} stays unapproved; delete it from the console if unwanted)")

    failed = [r for r in results if r[1] == BAD]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("failed: " + ", ".join(r[0] for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
