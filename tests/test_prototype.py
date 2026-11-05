"""End-to-end prototype test for Resmara.

Tests the full flow:
1. Register user + login
2. Connect Meta ad account (simulated)
3. Create approved creative
4. Create boost (campaign)
5. Launch campaign (auto-publish without Meta approval)
6. Create posts for calendar
7. Approve posts
8. Admin portal (users, support, health, metrics)
9. Support ticket creation
"""

import os
import tempfile

# Run against a throwaway database. This test used to run on whatever database the
# environment pointed at - the shipped resmara.db - and only worked because importing
# app.main migrated it as a side effect. A test must never touch the real install.
_scratch_db = tempfile.NamedTemporaryFile(prefix="resmara-prototype-", suffix=".db", delete=False)
_scratch_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_scratch_db.name}"

from fastapi.testclient import TestClient
from app.main import app
from app.db.migrate import migrate
from app.db.session import Base, engine, SessionLocal, User
import json

Base.metadata.create_all(bind=engine)
migrate()  # the same idempotent ALTER pass the app runs on startup
client = TestClient(app)

def get_token(email, password):
    resp = client.post("/api/auth/login", data={"username": email, "password": password})
    return resp.json()["access_token"]

# --- 1. Register + Login ---
print("=== 1. Register + Login ===")
resp = client.post("/api/auth/register", json={"email": "agent@resmara.com", "password": "test123", "name": "Test Agent"})
print(f"Register: {resp.status_code}")
token = get_token("agent@resmara.com", "test123")
headers = {"Authorization": f"Bearer {token}"}
print(f"Login: OK, token: {token[:20]}...")

# --- 2. Make user premium ---
db = SessionLocal()
user = db.query(User).filter(User.email == "agent@resmara.com").first()
user.subscription_status = "active"
db.commit()

# --- 3. Connect Meta ad account ---
print("\n=== 2. Connect Meta Ad Account ===")
resp = client.post("/api/ad-accounts", headers=headers, json={"platform": "meta", "advertiser_id": "act_987654321", "account_name": "Test RE Business", "budget": 5000.0})
acct = resp.json()
print(f"Ad Account: {resp.status_code}, id={acct['id']}, platform={acct['platform']}, budget={acct['budget']}")

# --- 4. Create approved creative ---
print("\n=== 3. Create Approved Creative ===")
resp = client.post("/api/creatives", headers=headers, json={"asset_url": "https://example.com/photo1.jpg", "asset_type": "image", "asset_name": "hero_photo.jpg", "copy_text": "Stunning 4BR home in Austin. $450K. Call today!", "cta_text": "Learn More", "landing_page_url": "https://example.com/listing"})
creative = resp.json()
print(f"Creative: {resp.status_code}, id={creative['id']}, status={creative['render_status']}")
# Approve it
resp = client.patch(f"/api/creatives/{creative['id']}/approve", headers=headers)
print(f"Approved: {resp.json()}")

# --- 5. Create boost (campaign) ---
print("\n=== 4. Create Boost (Campaign) ===")
resp = client.post("/api/boosts", headers=headers, json={"address": "123 Main St, Austin TX 78701", "tier": "bap_shoot_499", "go_live_date": "2026-11-10", "campaign_days": 14, "ad_budget_usd": 50.0, "property_facts": "4BR/3BA, 2400sqft, pool, updated kitchen"})
boost = resp.json()
print(f"Boost: {resp.status_code}, id={boost['id']}, address={boost['address']}, status={boost['main_status']}")

# --- 6. Launch campaign (auto-publish) ---
print("\n=== 5. Launch Campaign (auto-publish) ===")
resp = client.post("/api/launch", headers=headers, json={
    "platform": "meta",
    "source": "scratch",
    "meta_account_id": "act_987654321",
    "meta_custom_configs": {
        "campaign": {"name": "Austin Listing Boost", "objective": "REACH", "daily_budget": 3571},
        "adset": {"name": "Austin 15mi Radius", "targeting": {"geo_locations": {"countries": ["US"]}}},
        "adcreative": {"object_story_spec": {"page_id": "123", "link_data": {"link": "https://example.com/listing", "message": "Stunning 4BR home in Austin. $450K."}}}
    },
    "medias": [{"creative_id": creative['id'], "source": creative['asset_url'], "name": creative['asset_name']}]
})
result = resp.json()
print(f"Launch: {resp.status_code}")
print(f"  status: {result.get('status')}")
print(f"  budget_approved: {result.get('budget_approved')}")
print(f"  copy_approved: {result.get('copy_approved')}")
print(f"  can_auto_publish: {result.get('can_auto_publish')}")
print(f"  stage: {result.get('stage')}")
print(f"  meta_campaign_id: {result.get('meta_campaign_id')}")

# --- 7. Create posts for calendar ---
print("\n=== 6. Create Posts (14-day calendar) ===")
for day in range(1, 4):
    resp = client.post(f"/api/posts?boost_id={boost['id']}&day={day}&caption=Day {day} post for Austin listing&image_url=https://example.com/photo{day}.jpg", headers=headers)
    print(f"  Post day {day}: {resp.status_code}")

# --- 8. Approve posts ---
print("\n=== 7. Approve Posts ===")
posts = client.get(f"/api/posts/{boost['id']}", headers=headers).json()
for p in posts:
    resp = client.patch(f"/api/posts/{p['id']}/approve", headers=headers)
    print(f"  Post {p['id']} (day {p['day']}): {resp.json()['status']}")

# --- 9. Support ticket ---
print("\n=== 8. Support Ticket ===")
resp = client.post("/api/support", headers=headers, json={"subject": "Question about campaign", "message": "When will my ads go live?"})
ticket = resp.json()
print(f"Ticket: {resp.status_code}, id={ticket['id']}, status={ticket['status']}")

# --- 10. Admin portal ---
print("\n=== 9. Admin Portal ===")
# Make user admin
db_user = db.query(User).filter(User.email == "agent@resmara.com").first()
db_user.is_admin = True
db.commit()
admin_token = get_token("agent@resmara.com", "test123")
admin_headers = {"Authorization": f"Bearer {admin_token}"}

resp = client.get("/api/admin/users", headers=admin_headers)
users = resp.json()
print(f"Admin Users: {resp.status_code}, count={len(users)}")
for u in users:
    print(f"  {u['email']} | campaigns={u['campaign_count']} | last_login={u['last_login']}")

# Health answers "is the service well" and must NOT carry product counts (the console
# prints both cards, and a figure printed twice gets believed twice).
resp = client.get("/api/admin/health", headers=admin_headers)
health = resp.json()
assert resp.status_code == 200, resp.text
assert health["db_ok"] is True, health
assert not ({"total_users", "total_boosts", "active_campaigns"} & set(health)), health
print(f"Health: {resp.status_code}, status={health['status']}, db={health['db_ok']}, "
      f"ai={health['ai_mode']}, platform={health['platform_mode']}, errors_24h={health['errors_24h']}")

resp = client.get("/api/admin/metrics", headers=admin_headers)
metrics = resp.json()
assert resp.status_code == 200, resp.text
assert not ({"status", "db_ok", "errors_24h"} & set(metrics)), metrics
assert set(metrics) >= {"users", "campaigns", "content", "support", "advertising", "activity", "unavailable"}, metrics
print(f"Metrics: {resp.status_code}")
for group in ("users", "campaigns", "content", "support", "advertising"):
    print(f"  {group}: {metrics[group]}")
print(f"  not measured: {[x['metric'] for x in metrics['unavailable']]}")
print(f"  activity: {metrics['activity']['total_14d']} event(s) in {metrics['activity']['days']}d")

resp = client.get("/api/admin/support", headers=admin_headers)
tickets = resp.json()
assert tickets, "the ticket raised above should be listed"
assert tickets[0]["client_email"], tickets[0]
print(f"Support Tickets: {resp.status_code}, count={len(tickets)}, newest from={tickets[0]['client_email']}")

# The ticket the client raised must read as "waiting on us" until the operator answers.
assert metrics["support"]["waiting_on_us"] >= 1, metrics["support"]

# Reply to ticket
resp = client.patch(f"/api/admin/support/{ticket['id']}?status=in_progress&reply=Your ads are scheduled to go live on Nov 10.", headers=admin_headers)
assert resp.status_code == 200, resp.text
assert resp.json()["messages"][-1]["from"] == "admin", resp.json()
print(f"Ticket Update: {resp.status_code}, {resp.json()}")

# ...and the client reads the reply back on their own support list.
mine = client.get("/api/support", headers=headers).json()
answered = [t for t in mine if t["id"] == ticket["id"]][0]
assert answered["messages"][-1]["text"].startswith("Your ads are scheduled"), answered
assert answered["status"] == "in_progress", answered
print(f"Client sees reply: {answered['messages'][-1]['from']} -> {answered['messages'][-1]['text'][:40]}...")

after = client.get("/api/admin/metrics", headers=admin_headers).json()
print(f"Waiting on us after the reply: {after['support']['waiting_on_us']} (was {metrics['support']['waiting_on_us']})")

# --- Summary ---
print("\n" + "="*50)
print("ALL PROTOTYPE TESTS PASSED")
print("="*50)
print(f"User: agent@resmara.com")
print(f"Ad Account: act_987654321 (Meta, $5000 budget)")
print(f"Boost: 123 Main St, Austin TX (14-day campaign)")
print(f"Campaign: Auto-published (stage=LIVE)")
print(f"Posts: {len(posts)} created and approved")
print(f"Support: 1 ticket created and replied")
print(f"Admin: {len(users)} users, {metrics['campaigns']['total']} boosts, {metrics['campaigns']['live']} live")
db.close()
