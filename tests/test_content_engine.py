"""Plain-assert test suite for app.services.content_engine (+ prompts fidelity).

Run with:
    cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_content_engine.py

No pytest in this venv, so this is a script: one line per check, sys.exit(1) on any
failure. It is HERMETIC: it runs the whole pipeline OFFLINE (settings.SIMULATE=True,
OPENAI_API_KEY='') against a throw-away sqlite file, so the live resmara.db is never
written to.
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Force offline before the engine is exercised (the engine reads settings at call
# time; this just makes the intent explicit).
settings.SIMULATE = True
settings.OPENAI_API_KEY = ""

from app.db.session import Ad, Asset, Base, Boost, Post, User  # noqa: E402
from app.services import content_engine, prompts  # noqa: E402

FAILS = []


def check(cond, label):
    if cond:
        print(f"ok   - {label}")
    else:
        print(f"FAIL - {label}")
        FAILS.append(label)


def section(title):
    print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# Hermetic temp database
# ---------------------------------------------------------------------------
def make_temp_db():
    tmpdir = tempfile.mkdtemp(prefix="resmara_engine_test_")
    path = os.path.join(tmpdir, "test.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session(), path


def seed(db, *, with_photos=True, campaign_days=14, go_live="2026-11-10"):
    user = User(email=f"agent{os.urandom(3).hex()}@example.com", hashed_password="x",
                name="Dana Rivers")
    db.add(user)
    db.commit()
    boost = Boost(user_id=user.id, address="12 Cedar Lane, Fairview",
                  campaign_days=campaign_days, go_live_date=go_live, ad_budget_usd=50.0)
    db.add(boost)
    db.commit()
    if with_photos:
        for name in ("hero.jpg", "kitchen.jpg", "pool.jpg"):
            db.add(Asset(user_id=user.id, boost_id=boost.id, filename=name,
                         url="/uploads/" + name, original_name=name, kind="photo"))
    # a non-photo asset that must be excluded from the PHOTO INDEX
    db.add(Asset(user_id=user.id, boost_id=boost.id, filename="headshot.png",
                 url="/uploads/headshot.png", kind="headshot"))
    db.commit()
    return user, boost


OPENINGS = {
    "agent_name": "Dana Rivers",
    "phone": "555-0142",
    "license": "DRE 01987654",
    "brokerage": "Rivers & Co Realty",
    "instagram": "@danarivers",
    "website": "https://danarivers.example.com",
    "facts": "4 bed, 3 bath, 2,400 sqft, built 1964.",
    "notes": "Open the story with the arrival.",
}

# ===========================================================================
section("prompt fidelity (verbatim from engine_spec/prompts.json)")
# ===========================================================================
SPEC = json.loads((Path(__file__).resolve().parents[1] / "engine_spec" / "prompts.json").read_text())
K_R1 = '10_AI_build_the_campaign.md :: R1 — "AI research: look the property up on public pages" :: #1'
K_R2S = '10_AI_build_the_campaign.md :: R2 — "AI call 1: learn the agent\'s brand" :: #2'
K_R2U = '10_AI_build_the_campaign.md :: R2 — "AI call 1: learn the agent\'s brand" :: #3'
K_R3 = '10_AI_build_the_campaign.md :: R3 — "AI research: current best post styles blended with this agent\'s brand" :: #4'
K_R4S = '10_AI_build_the_campaign.md :: R4 — "AI call 2: draft the 14-day campaign" (the core prompt) :: #5'
K_R4U = '10_AI_build_the_campaign.md :: R4 — "AI call 2: draft the 14-day campaign" (the core prompt) :: #6'
K_PH = '14_intake_onboarding_golive.md :: AI photo-tagging prompt (verbatim) :: #1'

FIDELITY = [
    ("R1_PROPERTY_RESEARCH", K_R1, ["{address}"]),
    ("R2_BRAND_SYSTEM", K_R2S, []),
    ("R2_BRAND_USER", K_R2U,
     ["{agent}", "{address}", "{website_provided}", "{page_head}", "{page_text}", "{brand_kit}"]),
    ("R3_STYLE_RECIPE", K_R3,
     ["{agent}", "{website}", "{instagram}", "{brokerage}", "{brand_json}", "{brand_kit}",
      "{agent}", "{phone}", "{license}"]),
    ("R4_PLAN_SYSTEM", K_R4S,
     ["{days}", "{total_posts}", "{days}", "{days}", "{per_day}", "{days}", "{total_posts}"]),
    ("R4_PLAN_USER", K_R4U,
     ["{agent}", "{address}", "{go_live}", "{services}", "{days}", "{per_day}", "{total_posts}",
      "{notes}", "{video_library}", "{brand_json}", "{style}", "{phone}", "{photo_index}",
      "{license}", "{brokerage}", "{instagram}", "{facts}", "{ai_notes}", "{video_transcript}",
      "{research}", "{property_page_url}", "{property_page_text}"]),
    ("PHOTO_TAGGING_PROMPT", K_PH, []),
]


def norm_placeholders(text):
    return re.sub(r"\{[A-Za-z_]\w*\}", "@", text)


def norm_expressions(text):
    return re.sub(r"\{\{.*?\}\}", "@", text, flags=re.S)


for name, key, expected in FIDELITY:
    const = getattr(prompts, name)
    raw = SPEC[key]
    check(norm_placeholders(const) == norm_expressions(raw),
          f"{name}: byte-identical to the spec block once placeholders <-> Make-exprs normalise")
    phs = re.findall(r"\{[A-Za-z_]\w*\}", const)
    check(phs == expected, f"{name}: placeholder order matches the spec's Make expressions")
    check(len(phs) == len(re.findall(r"\{\{.*?\}\}", raw, flags=re.S)),
          f"{name}: exactly one placeholder per Make expression")


# ===========================================================================
section("build_photo_index (doc 10 photo index line format)")
# ===========================================================================
db, db_path = make_temp_db()
user, boost = seed(db)
assets = db.query(Asset).filter(Asset.boost_id == boost.id).all()
photos = [a for a in assets if a.kind == "photo"]

idx = content_engine.build_photo_index(assets)
lines = idx.split(" ;; ")
check(len(lines) == 3, "3 photo assets -> 3 lines (' ;; ' separator, per doc 10)")
check(idx.count(" ;; ") == 2, "photos are separated by two semicolons")
check(all(l.split(" | ")[0] in ("hero.jpg", "kitchen.jpg", "pool.jpg") for l in lines),
      "each line starts with the asset file name")
check(all(len(l.split(" | ")) >= 7 for l in lines),
      "each line has the doc's 7 fields (file name | id | room | social | shape | SEE | STORY)")
check("headshot.png" not in idx, "a non-photo asset (headshot) is excluded")
check(content_engine.build_photo_index([]) == "", "no assets -> empty PHOTO INDEX string")


# ===========================================================================
section("tag_assets (doc 14 verbatim prompt, offline)")
# ===========================================================================
res_tag = asyncio.run(content_engine.tag_assets(photos, base_url="https://example.test", db=db))
check(res_tag["source"] == "offline", "tag_assets reports source='offline' when simulating")
check(res_tag["tagged"] == 3, f"tag_assets tagged all 3 photos (got {res_tag['tagged']})")
check(res_tag["errors"] == [], "tag_assets had no per-photo errors")
check(all(a.tagged_by == "ai" for a in photos), "every asset has tagged_by='ai'")
check(all(a.room and a.social_score and a.shape and a.see and a.story for a in photos),
      "every asset got room/social_score/shape/see/story")
check(all(isinstance(a.tags, list) and a.tags for a in photos),
      "every asset got a non-empty tags list")

idx2 = content_engine.build_photo_index(photos)
check("POST:" in idx2 and "FEATURE:" in idx2, "tags are appended to the photo index lines")


# ===========================================================================
section("build_campaign (offline, 14 days / 1 per day)")
# ===========================================================================
db2, _ = make_temp_db()
user2, boost2 = seed(db2, campaign_days=14, go_live="2026-11-10")
result = asyncio.run(content_engine.build_campaign(boost2, db2, openings=OPENINGS))

check(result["source"] == "offline", "build_campaign reports source='offline'")
check(result["posts_created"] == 14, f"14 posts created for campaign_days=14 (got {result['posts_created']})")
check(len(result["plan"]["posts"]) == 14, "plan carries exactly 14 posts")

posts = db2.query(Post).filter(Post.boost_id == boost2.id).all()
check(len(posts) == 14, f"14 Post rows persisted (got {len(posts)})")

ads = db2.query(Ad).filter(Ad.boost_id == boost2.id).all()
check(len(ads) == 1, f"exactly one Ad row (got {len(ads)})")
check(result["ad_id"] == ads[0].id, "returned ad_id matches the persisted Ad row")
check(ads[0].kind in ("photo", "video"), "Ad kind derived from the plan's creatives")
check(bool(ads[0].primary_text and ads[0].headline and ads[0].description),
      "Ad has primary_text/headline/description")

base = date.fromisoformat("2026-11-10")
ok_dates = all(
    datetime.fromisoformat(p.publish_at).date() == base + timedelta(days=p.day - 1)
    for p in posts
)
ok_times = all(
    (datetime.fromisoformat(p.publish_at).hour, datetime.fromisoformat(p.publish_at).minute) == (9, 0)
    for p in posts
)
check(ok_dates, "every post.publish_at is on go-live date + (day-1)")
check(ok_times, "every slot-1 post.publish_at is at 09:00 (per_day=1 -> all slot 1)")

targets_ok = all(
    p.publish_target == ("instagram" if p.kind == "short_video" else "both") for p in posts
)
check(targets_ok, "publish_target: 'both' for static/main_video, 'instagram' for short_video")
check(all(p.client_status == "pending" for p in posts), "every post.client_status='pending'")
check(all(p.publish_status == "scheduled" for p in posts), "every post.publish_status='scheduled'")

check(boost2.main_status == "Team Review", "boost.main_status set to 'Team Review'")
check(isinstance(boost2.brand_profile, dict) and bool(boost2.brand_profile),
      "boost.brand_profile saved as a dict")
check(isinstance(boost2.plan, dict) and bool(boost2.plan.get("posts")),
      "boost.plan saved as the plan dict")

matched = [p for p in posts if p.kind == "static" and p.image_url]
check(len(matched) > 0 and all(p.image_url.startswith("/uploads/") for p in matched),
      "static posts whose photoFile is a real asset get that asset's url in image_url")

check(result["violations"] == [],
      f"the offline plan passes every hard rule (violations={result['violations']!r})")
check(not any("No uploaded photos" in m for m in result["missing_info"]),
      "with photos present, missing_info has no 'no photos' note")

try:
    blob = json.dumps(result)
    serialisable = True
except (TypeError, ValueError):
    serialisable = False
check(serialisable, f"the returned dict is JSON-serialisable ({len(blob) if serialisable else 0} bytes)")


# ===========================================================================
section("build_campaign (offline, boost with NO assets)")
# ===========================================================================
db3, _ = make_temp_db()
user3, boost3 = seed(db3, with_photos=False, campaign_days=14, go_live="2026-11-12")
boost3_photos = [a for a in db3.query(Asset).filter(Asset.boost_id == boost3.id).all()
                 if a.kind == "photo"]
check(content_engine.build_photo_index(boost3_photos) == "",
      "no photo assets -> the PHOTO INDEX passed to R4 is the empty string")

result3 = asyncio.run(content_engine.build_campaign(boost3, db3, openings=OPENINGS))
check(result3["source"] == "offline", "no-asset build still reports source='offline'")
check(any("PHOTO INDEX" in m and "empty" in m for m in result3["missing_info"]),
      "no-asset build says so in missing_info")
check(all(p.get("photoFile") == "NEEDS PHOTO"
          for p in result3["plan"]["posts"] if p.get("kind") == "static"),
      "no-asset build sets static photoFile to 'NEEDS PHOTO' (per doc 10)")
posts3 = db3.query(Post).filter(Post.boost_id == boost3.id).all()
check(len(posts3) == 14, "no-asset build still creates 14 posts")
check(all(p.image_url == "" for p in posts3),
      "no-asset build leaves image_url empty (no matching Asset)")


# ===========================================================================
print()
if FAILS:
    print(f"{len(FAILS)} CHECK(S) FAILED")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL CONTENT ENGINE TESTS PASSED")
