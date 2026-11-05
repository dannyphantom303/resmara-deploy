#!/usr/bin/env python3
"""One REAL content-engine build (no offline fixtures) against the running app.

Registers a fresh user, creates a boost on a real, publicly documented address, runs
POST /api/boosts/{id}/build and prints what the models actually returned: the research
lines with their sources, the plan's shape, the posts, and any spec violations.

Costs real tokens (R1/R3 use gpt-5.5 with web search, R2/R4 chat calls). Run it
deliberately, not in a loop.
"""
import json
import sqlite3
import sys
import time

import httpx

B = "http://127.0.0.1:8083"
ADDRESS = sys.argv[1] if len(sys.argv) > 1 else "706 Congress Ave, Austin TX"
stamp = str(int(time.time()))
EMAIL = f"realbuild{stamp}@example.com"
PW = "realbuild-pass-12345"

c = httpx.Client(base_url=B, timeout=900)
c.post("/api/auth/register", json={"email": EMAIL, "password": PW, "name": "Real Build"})
r = c.post("/api/auth/login", data={"username": EMAIL, "password": PW})
H = {"Authorization": f"Bearer {r.json()['access_token']}"}
print("login:", r.status_code)

r = c.post("/api/ad-accounts", headers=H, json={
    "platform": "meta", "advertiser_id": f"act_real_{stamp}",
    "account_name": "Real Build Account", "budget": 500.0})
acct = r.json()["id"]
r = c.post("/api/boosts", headers=H, json={
    "address": ADDRESS, "ad_account_id": acct,
    "go_live_date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400)),
    "campaign_days": 14, "ad_budget_usd": 50.0})
boost_id = r.json()["id"]
print("boost:", boost_id, ADDRESS)

t0 = time.time()
r = c.post(f"/api/boosts/{boost_id}/build", headers=H, json={"force": True})
elapsed = time.time() - t0
print(f"build: http={r.status_code} in {elapsed:.1f}s")
if r.status_code != 200:
    print(r.text[:800])
    sys.exit(1)
res = r.json()
print("keys:", sorted(res.keys()))
print("source:", res.get("source"), "posts:", res.get("posts_created"),
      "violations:", res.get("violations"), "missing_info:", res.get("missing_info"))

plan = c.get(f"/api/boosts/{boost_id}/plan", headers=H).json()
p = plan.get("plan") or {}
print("\nplan keys:", sorted(p.keys()))
print("\n--- research (R1) ---")
for line in (p.get("research") or p.get("facts") or [])[:8]:
    print("  ", line)
print("\n--- brand (R2) ---")
print("  ", json.dumps(p.get("brand") or p.get("brandProfile") or {}, indent=1)[:600])
print("\n--- style recipe (R3) head ---")
print("  ", str(p.get("styleRecipe") or p.get("style_recipe") or "")[:400].replace("\n", "\n   "))
print("\n--- ad (R4) ---")
print("  ", json.dumps(p.get("ad") or {}, indent=1)[:600])
print("\n--- video mix in the stored plan ---")
_posts = p.get("posts") or []
from collections import Counter
print("  ", dict(Counter(x.get("kind") for x in _posts)))
print("\n--- first 2 posts ---")
for post in (p.get("posts") or [])[:2]:
    print("  ", json.dumps(post, indent=1)[:500])

con = sqlite3.connect("/Users/dan/resmara/resmara.db")
print("\n--- stored posts ---")
for row in con.execute("SELECT day,slot,kind,caption,cta,image_url,publish_at FROM posts WHERE boost_id=? ORDER BY day,slot LIMIT 2", (boost_id,)):
    print("  ", row)
print("total posts:", con.execute("SELECT count(*) FROM posts WHERE boost_id=?", (boost_id,)).fetchone()[0])
con.close()
print("\nboost_id:", boost_id, "email:", EMAIL)
