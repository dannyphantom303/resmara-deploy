#!/usr/bin/env python3
"""Focused probe: inspect the photo index, the report payload and the publish details
for the most recent smoke account (read-only, simulated platform)."""
import json
import sqlite3

import httpx

B = "http://127.0.0.1:8083"
con = sqlite3.connect("/Users/dan/resmara/resmara.db")
main = con.execute("SELECT id,email FROM users WHERE email LIKE 'smoke%@example.com' AND email NOT LIKE 'smokeother%' ORDER BY id DESC LIMIT 1").fetchone()
boost = con.execute("SELECT id,address FROM boosts WHERE user_id=? ORDER BY id DESC LIMIT 1", (main[0],)).fetchone()
print("user:", main[1], "boost:", boost[0], boost[1])
c = httpx.Client(base_url=B, timeout=60)
r = c.post("/api/auth/login", data={"username": main[1], "password": "smoke-pass-NEW-67890"})
print("login:", r.status_code)
H = {"Authorization": f"Bearer {r.json()['access_token']}"}

print("\n--- photo index (raw) ---")
print(c.get(f"/api/content/photo-index/{boost[0]}", headers=H).json().get("photo_index"))

print("\n--- assets ---")
print(json.dumps(c.get(f"/api/content/assets/{boost[0]}", headers=H).json(), indent=1)[:900])

print("\n--- publish status ---")
print(json.dumps(c.get(f"/api/content/publish/status/{boost[0]}", headers=H).json(), indent=1)[:900])

print("\n--- report day=7 ---")
print(json.dumps(c.get(f"/api/content/reports/{boost[0]}", headers=H, params={"day": 7}).json(), indent=1)[:2500])

print("\n--- posts 1..3 as stored ---")
for row in con.execute("SELECT id,day,slot,kind,publish_at,client_status,publish_status,image_url,fb_post_id,ig_media_id,last_error FROM posts WHERE boost_id=? ORDER BY day,slot LIMIT 3", (boost[0],)):
    print(" ", row)
con.close()
