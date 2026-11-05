#!/usr/bin/env python3
"""Live end-to-end smoke against the running Resmara app on 127.0.0.1:8083.

Exercises the whole product path over real HTTP with a fresh user:
  register -> login -> ad account -> boost -> photo upload -> AI tag -> photo index
  -> content engine build -> plan/posts -> approve -> credit precheck -> launch
  -> publish due posts -> report -> password reset -> support desk (client raises, operator
  answers, client reads the reply) -> operator metrics -> per-user isolation.

Runs in simulated-platform mode automatically (the ad account is created with a
prototype token, which is what makes the Graph client skip the network). Nothing here
touches real ad spend.

Prints one line per step and exits non-zero on the first hard failure. No secret is
printed: the reset token is masked to its first 6 characters.
"""
import base64
import json
import pathlib
import sqlite3
import sys
import time

import os

import httpx

B = "http://127.0.0.1:8083"
env = {}
for line in open("/Users/dan/resmara/.env"):
    if line.startswith("RESMARA_PUBLISH_TOKEN="):
        env["token"] = line.split("=", 1)[1].strip()

stamp = str(int(time.time()))
EMAIL = f"smoke{stamp}@example.com"
PW = "smoke-pass-12345"
failures = []


def step(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def main():
    c = httpx.Client(base_url=B, timeout=float(os.environ.get("SMOKE_TIMEOUT", "120")))

    r = c.post("/api/auth/register", json={"email": EMAIL, "password": PW, "name": "Smoke Tester"})
    step("register", r.status_code == 201, f"{r.status_code}")

    r = c.post("/api/auth/login", data={"username": EMAIL, "password": PW})
    step("login", r.status_code == 200 and "access_token" in r.json(), f"{r.status_code}")
    tok = r.json().get("access_token")
    H = {"Authorization": f"Bearer {tok}"}

    r = c.get("/api/auth/me", headers=H)
    step("me", r.status_code == 200 and r.json()["email"] == EMAIL, f"{r.status_code}")

    r = c.post("/api/ad-accounts", headers=H, json={
        "platform": "meta", "advertiser_id": f"act_smoke_{stamp}",
        "account_name": "Smoke Meta Account", "budget": 500.0,
    })
    step("connect ad account (prototype token -> simulated)", r.status_code == 201, f"{r.status_code}")
    acct_id = r.json()["id"]

    # Go-live yesterday so day-1 and day-2 posts are already due for the publisher.
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    r = c.post("/api/boosts", headers=H, json={
        "address": "123 Smoke Test Lane, Austin TX", "ad_account_id": acct_id,
        "go_live_date": yesterday, "campaign_days": 14, "ad_budget_usd": 50.0,
        "property_facts": "4 bedrooms · 3 bathrooms · 2400 sqft · updated kitchen",
    })
    step("create boost", r.status_code == 201, f"{r.status_code}")
    boost_id = r.json()["id"]

    # A REAL listing photo, not a 1x1 stub: the tag step sends the bytes to a vision model,
    # and a blank image only proves the call happens, not that the photo is seen. It is a
    # JPEG because Instagram feed posts accept nothing else, and this campaign publishes to
    # Facebook and Instagram - the platform is right to refuse a PNG.
    photo = pathlib.Path(__file__).with_name("fixtures").joinpath("listing-photo.jpg").read_bytes()
    r = c.post("/api/content/upload/photo", headers=H,
               files={"file": ("front-room.jpg", photo, "image/jpeg")},
               data={"boost_id": str(boost_id), "kind": "photo"})
    ok = step("upload photo -> asset row", r.status_code == 201 and r.json().get("asset_id"), f"{r.status_code}")
    asset_id = r.json().get("asset_id") if ok else None

    if asset_id:
        r = c.post(f"/api/content/assets/{boost_id}/tag", headers=H, timeout=600)
        j = r.json() if r.status_code == 200 else {}
        step("AI-tag photos", r.status_code == 200 and j.get("tagged", 0) >= 1,
             f"{r.status_code} tagged={j.get('tagged')} source={j.get('source')} "
             f"errors={j.get('errors')}")

        r = c.get(f"/api/content/assets/{boost_id}", headers=H)
        body = r.json() if r.status_code == 200 else []
        rows = body.get("assets") or body.get("items") if isinstance(body, dict) else body
        first = (rows or [{}])[0]
        step("tagging returned a room and tags for the photo",
             bool(str(first.get("room") or "").strip()) and bool(first.get("tags")),
             f"room={first.get('room')} social={first.get('social_score')} "
             f"shape={first.get('shape')} tags={first.get('tags')}")

        r = c.get(f"/api/content/photo-index/{boost_id}", headers=H)
        idx = r.json().get("photo_index", "")
        step("photo index built", r.status_code == 200 and "upload: front-room.jpg" in idx,
             f"{r.status_code} len={len(idx)}")

    # A real build runs four model calls and can take several minutes; the wire test must
    # not fail just because the app is in real (non-offline) mode.
    r = c.post(f"/api/boosts/{boost_id}/build", headers=H, json={"force": True}, timeout=1500)
    j = r.json() if r.status_code == 200 else {}
    step("content engine build", r.status_code == 200 and j.get("posts_created") == 14,
         f"{r.status_code} posts={j.get('posts_created')} source={j.get('source')} "
         f"violations={len(j.get('violations') or [])}")

    r = c.get(f"/api/boosts/{boost_id}/plan", headers=H)
    plan = r.json().get("plan") or {}
    step("plan stored", r.status_code == 200 and bool(plan.get("posts")),
         f"{r.status_code} plan_posts={len(plan.get('posts') or [])} ad={bool(plan.get('ad'))}")

    r = c.get(f"/api/boosts/{boost_id}/posts", headers=H)
    posts = r.json() if r.status_code == 200 else []
    sched = [p for p in posts if p.get("publish_at")]
    step("posts scheduled", len(posts) == 14 and len(sched) == 14,
         f"{len(posts)} posts, {len(sched)} with publish_at, first={sched[0]['publish_at'] if sched else None}")

    r = c.post(f"/api/boosts/{boost_id}/approve", headers=H, json={})
    step("client approval", r.status_code == 200 and r.json().get("posts_approved") == 14,
         f"{r.status_code} approved={r.json().get('posts_approved')}")

    r = c.post("/api/adflow/credits/precheck/", headers=H, json={"platform": "meta", "budget": 50.0})
    pre = r.json() if r.status_code == 200 else {}
    step("creatify-style credit precheck (gated: needs an active account)", r.status_code == 200,
         f"{r.status_code} budget_approved={pre.get('budget_approved')} available={pre.get('available_budget')}")

    # The gate requires an active subscription; the operator sets that (admin action).
    # For the smoke run we flip it directly in the database and say so.
    con = sqlite3.connect("/Users/dan/resmara/resmara.db")
    con.execute("UPDATE users SET subscription_status='active' WHERE email=?", (EMAIL,))
    con.commit()
    con.close()

    r = c.post("/api/launch", headers=H, json={"platform": "meta", "boost_id": boost_id, "auto_approve": False})
    j = r.json() if r.status_code == 200 else {}
    step("launch (real gate, simulated platform)", r.status_code == 200 and j.get("status") == "launched",
         f"{r.status_code} status={j.get('status')} simulated={j.get('simulated')} "
         f"campaign={j.get('meta_campaign_id')} reasons={j.get('reasons')}")

    r = c.get(f"/api/content/publish/status/{boost_id}", headers=H)
    j = r.json() if r.status_code == 200 else {}
    step("publish status", r.status_code == 200 and "counts" in j,
         f"{r.status_code} counts={j.get('counts')} next_due={j.get('next_due')}")

    r = c.post(f"/api/content/publish/boost/{boost_id}", headers=H)
    j = r.json() if r.status_code == 200 else {}
    step("publish due posts", r.status_code == 200 and j.get("posted", 0) >= 1,
         f"{r.status_code} checked={j.get('checked')} posted={j.get('posted')} failed={j.get('failed')}")

    # Idempotency: a second run must not republish.
    r = c.post(f"/api/content/publish/boost/{boost_id}", headers=H)
    j2 = r.json() if r.status_code == 200 else {}
    step("publisher is idempotent", j2.get("posted", 1) == 0 and j2.get("failed", 1) == 0,
         f"second run posted={j2.get('posted')} failed={j2.get('failed')}")

    r = c.get(f"/api/content/reports/{boost_id}", headers=H, params={"day": 7})
    j = r.json() if r.status_code == 200 else {}
    step("report (no invented numbers)", r.status_code == 200
         and (j.get("organic") or {}).get("source") in ("meta", "unavailable")
         and j.get("metrics", {}).get("reach") is None,
         f"{r.status_code} organic={((j.get('organic') or {}).get('source'))} "
         f"paid={((j.get('paid') or {}).get('source'))} published={(j.get('posts') or {}).get('published')}")

    if env.get("token"):
        r = c.post("/api/content/publish/run", headers={"X-Resmara-Token": env["token"]}, json={})
        step("scheduler entrypoint (token)", r.status_code == 200, f"{r.status_code} {r.text[:90]}")
        r = c.post("/api/content/publish/run", headers={"X-Resmara-Token": "wrong"}, json={})
        step("scheduler entrypoint rejects a bad token", r.status_code == 403, f"{r.status_code}")

    # --- password reset, end to end ---
    r = c.post("/api/auth/password-reset/request", params={"email": EMAIL})
    j = r.json() if r.status_code == 200 else {}
    rt = j.get("reset_token")
    step("password reset request", r.status_code == 200 and j.get("status") == "ok",
         f"{r.status_code} delivery={j.get('delivery')} token={'yes' if rt else 'no'}")
    if rt:
        newpw = "smoke-pass-NEW-67890"
        r = c.post("/api/auth/password-reset/confirm", params={"token": rt, "new_password": newpw})
        step("password reset confirm", r.status_code == 200, f"{r.status_code}")
        r = c.post("/api/auth/login", data={"username": EMAIL, "password": newpw})
        step("login with the new password", r.status_code == 200, f"{r.status_code}")
        r = c.post("/api/auth/login", data={"username": EMAIL, "password": PW})
        step("old password no longer works", r.status_code == 400, f"{r.status_code}")
        r = c.post("/api/auth/password-reset/confirm", params={"token": rt, "new_password": "another-one-123"})
        step("used token cannot be replayed", r.status_code == 400, f"{r.status_code}")

    # --- support desk, wired end to end -------------------------------------------------
    # The client's Support page and the in-page assistant both call these two endpoints;
    # the operator answers from the console. A ticket is not "done" until the client can
    # read the reply, so both directions are asserted here.
    r = c.post("/api/support", headers=H, json={
        "subject": f"Smoke question {stamp}",
        "message": "Day 1 Instagram post failed - what should I do?"})
    step("client raises a support request", r.status_code == 201 and r.json().get("id"), f"{r.status_code}")
    ticket_id = r.json().get("id")

    r = c.get("/api/support", headers=H)
    mine = [t for t in r.json() if t["id"] == ticket_id]
    step("client reads their own request back", len(mine) == 1 and mine[0]["messages"][0]["from"] == EMAIL,
         f"{r.status_code}")

    # An operator account is the only thing the console adds; mint one the way an operator
    # would be minted (the flag), not by weakening the admin check.
    admin_email = f"smokeadmin{stamp}@example.com"
    c.post("/api/auth/register", json={"email": admin_email, "password": PW, "name": "Smoke Operator"})
    con = sqlite3.connect("/Users/dan/resmara/resmara.db")
    con.execute("update users set is_admin=1, subscription_status='active' where email=?", (admin_email,))
    con.commit()
    con.close()
    ra = c.post("/api/auth/login", data={"username": admin_email, "password": PW})
    HA = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    step("operator can sign in", ra.status_code == 200, f"{ra.status_code}")

    before = c.get("/api/admin/metrics", headers=HA).json()
    row = [t for t in c.get("/api/admin/support", headers=HA).json() if t["id"] == ticket_id]
    step("operator sees the request with the client's email",
         len(row) == 1 and row[0]["client_email"] == EMAIL, f"{len(row)}")
    step("operator queue counts it as waiting on us",
         before["support"]["waiting_on_us"] >= 1 and before["support"]["open"] >= 1,
         str(before["support"]))

    r = c.patch(f"/api/admin/support/{ticket_id}?status=in_progress"
                "&reply=Instagram needs a JPG for feed posts - re-upload the photo as JPG and retry.",
                headers=HA)
    step("operator replies and moves the ticket on", r.status_code == 200
         and r.json()["messages"][-1]["from"] == "admin", f"{r.status_code}")

    mine = [t for t in c.get("/api/support", headers=H).json() if t["id"] == ticket_id][0]
    step("client reads the operator's reply", mine["messages"][-1]["text"].startswith("Instagram needs a JPG")
         and mine["status"] == "in_progress", mine["status"])

    after = c.get("/api/admin/metrics", headers=HA).json()
    step("answering it drops 'waiting on us' by exactly one",
         after["support"]["waiting_on_us"] == before["support"]["waiting_on_us"] - 1,
         f"{before['support']['waiting_on_us']} -> {after['support']['waiting_on_us']}")

    # The two operator cards must not repeat each other's figures, and the activity line
    # must be counting events this run actually wrote.
    step("health carries no product counts",
         not ({"total_users", "total_boosts", "active_campaigns"} & set(
             c.get("/api/admin/health", headers=HA).json())), "overlap with the metrics card")
    step("metrics carries no service state",
         not ({"status", "db_ok", "errors_24h"} & set(after)), "overlap with the health card")
    step("metrics are grouped and name what is not measured",
         {"users", "campaigns", "content", "support", "advertising", "activity", "unavailable"} <= set(after)
         and {x["metric"] for x in after["unavailable"]} == {"ad_spend", "revenue"}, str(after["unavailable"]))
    step("the activity log records real events this run produced",
         after["activity"]["by_type_14d"].get("ticket_created", 0) >= 1
         and after["activity"]["by_type_14d"].get("user_registered", 0) >= 1,
         str(after["activity"]["by_type_14d"]))
    step("the counting window is 14 days of buckets",
         after["activity"]["days"] == 14 and len(after["activity"]["per_day"]) == 14,
         f"{len(after['activity']['per_day'])} buckets")

    # The console itself is served (not just the API behind it), and it is served from the
    # same mount as the app so it works behind the Command Center router too.
    r = c.get("/admin.html")
    step("operator console is served", r.status_code == 200 and 'id="metricsBody"' in r.text,
         f"{r.status_code}")
    r = c.get("/api.js")
    step("front-end client exposes the support calls",
         r.status_code == 200 and "createTicket" in r.text and "base: BASE" in r.text,
         f"{r.status_code}; createTicket={'createTicket' in r.text} base={'base: BASE' in r.text}")

# --- public legal pages (Meta's crawler fetches these with no cookie) ---
    for page, marker in (("privacy.html", "Privacy Policy"), ("terms.html", "Terms of Service")):
        r = c.get(f"/{page}")
        step(f"/{page} is served publicly",
             r.status_code == 200 and marker in r.text,
             f"{r.status_code}; marker={marker in r.text}")

    # --- per-user isolation ---
    other = f"smokeother{stamp}@example.com"
    c.post("/api/auth/register", json={"email": other, "password": PW, "name": "Other"})
    r2 = c.post("/api/auth/login", data={"username": other, "password": PW})
    H2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = c.get(f"/api/boosts/{boost_id}", headers=H2)
    step("other user cannot read the boost", r.status_code == 404, f"{r.status_code}")
    r = c.get(f"/api/posts/{boost_id}", headers=H2)
    step("other user cannot read the posts", r.status_code == 404, f"{r.status_code}")
    r = c.get(f"/api/boosts/{boost_id}/plan", headers=H2)
    step("other user cannot read the plan", r.status_code == 404, f"{r.status_code}")

    print()
    if failures:
        print(f"{len(failures)} STEP(S) FAILED: {', '.join(failures)}")
        return 1
    print("ALL LIVE SMOKE STEPS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
