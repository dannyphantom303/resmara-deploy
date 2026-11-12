#!/usr/bin/env python3
"""The gallery decides the campaign: the plan must fill all 14 slots and use the photos that
sell the house, not the first files in upload order.

Covers the four complaints this suite was written for:
  1. a 14-day campaign must be 14 posts even when the model answers 10;
  2. photo selection is ranked by the tagger's SOCIAL score, not by upload order;
  3. a photo nobody named never falls back to upload order, and never repeats while the
     gallery still has an unused photo;
  4. a half-downloaded file is spotted instead of being planned onto a post.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Hermetic: no engine endpoint, offline fixtures, so this suite spends nothing and never
# reaches the local model that may or may not be running on this Mac.
from app.core.config import settings  # noqa: E402

settings.SIMULATE = True
settings.OPENAI_API_KEY = ""
for _key in ("RESMARA_ENGINE_API_KEY", "OPENAI_BASE_URL"):
    if getattr(settings, _key, None):
        setattr(settings, _key, "")

FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS += 1


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def make_temp_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base

    tmpdir = tempfile.mkdtemp(prefix="resmara_gallery_test_")
    engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)(), tmpdir


def seed(db, photos):
    """photos: list of (filename, room, social, tags) — uploaded in this order."""
    from app.db.session import Asset, Boost, User

    user = User(email=f"gal{os.urandom(3).hex()}@example.com", hashed_password="x", name="Gal")
    db.add(user)
    db.commit()
    boost = Boost(user_id=user.id, address="9 Ridge Way, Fairview", campaign_days=14,
                  go_live_date="2026-11-10", ad_budget_usd=50.0)
    db.add(boost)
    db.commit()
    for name, room, social, tags in photos:
        db.add(Asset(user_id=user.id, boost_id=boost.id, filename=name, url="/uploads/" + name,
                     original_name=name, kind="photo", room=room, social_score=social,
                     tags=tags))
    db.commit()
    return user, boost


def main() -> int:
    from app.services import content_engine, photos as photo_service
    from app.services import llm

    # ------------------------------------------------------------------ ranking
    section("the PHOTO INDEX is ordered by what sells the house")
    db, _ = make_temp_db()
    _, boost = seed(db, [
        ("laundry.jpg", "laundry", "2", ["POST: yes", "ROOM: laundry", "SOCIAL: 2"]),
        ("hero.jpg", "front exterior", "9", ["POST: yes", "ROOM: front exterior", "SOCIAL: 9"]),
        ("closet.jpg", "closet", "1", ["POST: no", "ROOM: closet", "SOCIAL: 1"]),
        ("kitchen.jpg", "kitchen", "8", ["POST: yes", "ROOM: kitchen", "SOCIAL: 8"]),
        ("untagged.jpg", "", None, []),
    ])
    from app.db.session import Asset
    assets = db.query(Asset).filter(Asset.boost_id == boost.id).all()
    index = content_engine.build_photo_index(assets)
    order = [line.split(" | ")[0] for line in index.split(" ;; ")]
    check("the hero exterior leads the index", order[0] == "hero.jpg", str(order))
    check("the kitchen follows it", order[1] == "kitchen.jpg", str(order))
    check("a POST: no detail shot is pushed to the back", order[-1] == "closet.jpg", str(order))
    check("every photo is still in the index", len(order) == 5, str(order))
    check("the ordering note is prepended for the planner",
          content_engine.index_for_prompt("x") .startswith("ORDERED STRONGEST-SELLING"),
          content_engine.index_for_prompt("x")[:40])
    check("an empty index stays empty for the planner",
          content_engine.index_for_prompt("") == "", repr(content_engine.index_for_prompt("")))

    # ------------------------------------------------------------- no repeats
    section("photo assignment never falls back to upload order")
    gallery = [{"url": "/uploads/hero.jpg", "score": 9},
               {"url": "/uploads/kitchen.jpg", "score": 8},
               {"url": "/uploads/laundry.jpg", "score": 2}]
    plan = [{"day": i, "photoFile": "NEEDS PHOTO"} for i in range(1, 4)]
    images, picked = content_engine.post_image_urls(plan, {}, gallery)
    check("the strongest photo is used first", images[0] == "/uploads/hero.jpg", str(images))
    check("no photo repeats while the gallery has an unused one",
          len(set(images)) == 3, str(images))
    check("every pick is reported", picked == 3, str(picked))

    small = [{"url": "/uploads/a.jpg", "score": 9}, {"url": "/uploads/b.jpg", "score": 8}]
    long_plan = [{"day": i, "photoFile": ""} for i in range(1, 7)]
    imgs, _ = content_engine.post_image_urls(long_plan, {}, small)
    check("a small gallery cycles instead of leaving blanks", all(imgs), str(imgs))
    check("the same photo is never on two posts in a row",
          all(imgs[i] != imgs[i + 1] for i in range(len(imgs) - 1)), str(imgs))

    named = [{"day": 1, "photoFile": "kitchen.jpg"}, {"day": 2, "photoFile": "kitchen.jpg"}]
    imgs2, picked2 = content_engine.post_image_urls(
        named, {"kitchen.jpg": "/uploads/kitchen.jpg"}, gallery)
    check("the plan's own photo is honoured", imgs2[0] == "/uploads/kitchen.jpg", str(imgs2))
    check("a photo the plan names twice is not posted twice",
          imgs2[1] != imgs2[0], str(imgs2))

    # --------------------------------------------------------- calendar repair
    section("a calendar short by four posts is filled, not shipped short")
    plan10 = {"posts": [{"day": d, "slot": 1, "kind": "static", "photoFile": "NEEDS PHOTO",
                         "caption": f"Day {d} copy.\nA | 555 | LIC 1 | B | Equal Housing Opportunity"}
                        for d in range(1, 11)]}
    normalised, missing = content_engine._normalise_calendar(plan10, 14, 1)
    check("ten posts normalise to ten", len(normalised["posts"]) == 10, str(len(normalised["posts"])))
    check("the four missing days are named", missing == [(11, 1), (12, 1), (13, 1), (14, 1)], str(missing))

    dupes = {"posts": [{"day": 1, "slot": 1}, {"day": 1, "slot": 1}, {"day": 99, "slot": 3}]}
    normalised2, missing2 = content_engine._normalise_calendar(dupes, 14, 1)
    check("a duplicate slot is dropped, not persisted twice",
          len(normalised2["posts"]) == 2, str(len(normalised2["posts"])))
    check("an out-of-range day is clamped onto the calendar",
          all(1 <= p["day"] <= 14 for p in normalised2["posts"]), str(normalised2["posts"]))

    # ---------------------------------------------------- the fill call itself
    section("the follow-up call writes only the empty slots")
    seen = {}

    async def fake_chat_json(system, user, **kwargs):
        seen["user"] = user
        return {"posts": [{"day": 11, "slot": 1, "kind": "static", "photoFile": "hero.jpg",
                           "caption": "Eleven.\nA | 555 | LIC 1 | B | Equal Housing Opportunity"},
                          {"day": 99, "slot": 1, "kind": "static", "photoFile": "hero.jpg",
                           "caption": "Not asked for."}]}

    real_chat_json = llm.chat_json
    llm.chat_json = fake_chat_json
    try:
        notes: list = []
        plan_holder = {"posts": list(plan10["posts"])}
        added = asyncio.run(content_engine._fill_missing_posts(
            plan_holder, [(11, 1), (12, 1), (13, 1), (14, 1)], days=14, per_day=1,
            photo_index="hero.jpg | 1 | front exterior | 9", closing_line="CLOSING",
            address="9 Ridge Way", agent="A", brand_json="{}", facts="3 bed",
            notes="", engine_notes=notes))
    finally:
        llm.chat_json = real_chat_json
    check("the reply for a slot that was asked for is kept", added == 1, str(added))
    check("a slot nobody asked for is not added", len(plan_holder["posts"]) == 11,
          str(len(plan_holder["posts"])))
    check("the prompt names every empty slot", "day 14 slot 1" in seen.get("user", ""),
          seen.get("user", "")[:120])
    check("the build says the model came up short", any("11" in n or "10" in n for n in notes),
          str(notes))

    # ------------------------------------------------------- broken photo files
    section("a photo that stops mid-file is not planned onto a post")
    whole = b"\xff\xd8\xff\xe0" + b"\x00" * 5000 + b"\xff\xd9"
    truncated = b"\xff\xd8\xff\xe0" + b"\x00" * 5000
    padded = b"\xff\xd8\xff\xe0" + b"\x01" * 5000 + b"\xff\xd9" + b"\x00" * 900_000
    check("a whole JPEG passes", photo_service.looks_incomplete(whole, "ok.jpg") is False)
    check("a truncated JPEG is caught", photo_service.looks_incomplete(truncated, "cut.jpg") is True)
    check("a truncated PNG is caught",
          photo_service.looks_incomplete(b"\x89PNG\r\n\x1a\n" + b"\x00" * 99, "cut.png") is True)
    check("video and unknown types are not judged",
          photo_service.looks_incomplete(b"\x00\x00\x00\x18ftypmp42", "tour.mp4") is False)
    # 37 photos in the real gallery arrived as a complete JPEG padded with NUL bytes out to
    # exactly 3 MiB. That is not damage: the picture is whole and must still be planned.
    check("NUL padding after a whole JPEG is not damage",
          photo_service.looks_incomplete(padded, "padded.jpg") is False)
    check("the padding is trimmed off the bytes",
          photo_service.clean_image_bytes(padded) == padded[:-900_000],
          str(len(photo_service.clean_image_bytes(padded))))
    check("a truncated JPEG that is also padded is still caught",
          photo_service.looks_incomplete(b"\xff\xd8\xff\xe0" + b"\x01" * 900 + b"\x00" * 4000,
                                         "cut-padded.jpg") is True)

    # -------------------------------------------- the whole build, short model
    section("a real build keeps the 14-post promise when the model answers 10")
    db2, tmp2 = make_temp_db()
    user2, boost2 = seed(db2, [
        ("hero.jpg", "front exterior", "9", ["POST: yes", "SOCIAL: 9"]),
        ("kitchen.jpg", "kitchen", "8", ["POST: yes", "SOCIAL: 8"]),
        ("living.jpg", "living room", "7", ["POST: yes", "SOCIAL: 7"]),
        ("bed.jpg", "primary bedroom", "6", ["POST: yes", "SOCIAL: 6"]),
        ("bath.jpg", "bathroom", "2", ["POST: no", "SOCIAL: 2"]),
    ])
    # Give one photo a full, whole JPEG so it is not filtered as a partial file.
    from app.db.session import Asset as AssetRow
    for row in db2.query(AssetRow).filter(AssetRow.boost_id == boost2.id).all():
        if row.filename == "hero.jpg":
            row.data = b"\xff\xd8\xff\xe0" + b"\x00" * 4000 + b"\xff\xd9"
    db2.query(AssetRow).filter(AssetRow.boost_id == boost2.id,
                               AssetRow.filename == "kitchen.jpg").first().data = (
        b"\xff\xd8\xff\xe0" + b"\x01" * 4000 + b"\xff\xd9")
    db2.commit()

    # The model returns ten posts for a fourteen-day campaign; the follow-up returns the rest.
    state = {"plan": 0}

    async def fake_json(system, user, **kwargs):
        if "completing a Real Estate Boost campaign" in system:
            return {"posts": [{"day": d, "slot": 1, "kind": "static", "photoFile": "hero.jpg",
                               "caption": f"Filled day {d}.\nA | 555 | LIC 1 | B | "
                                          "Equal Housing Opportunity"} for d in (11, 12, 13, 14)]}
        state["plan"] += 1
        return {"summary": "A home.", "propertyStory": {"thesis": "t", "differentiators": [],
                                                        "angles": []},
                "storyArc": "s",
                "posts": [{"day": d, "slot": 1, "kind": "static", "photoFile": "hero.jpg",
                           "caption": f"Day {d}.\nA | 555 | LIC 1 | B | Equal Housing Opportunity"}
                          for d in range(1, 11)],
                "missingInfo": [], "needsVerification": [], "complianceFlags": []}

    openings = {"agent_name": "Dana Rivers", "phone": "555-0142", "license": "DRE 1",
                "brokerage": "Rivers & Co", "facts": "4 bed, 3 bath."}
    llm.chat_json = fake_json
    try:
        result = asyncio.run(content_engine.build_campaign(boost2, db2, openings=openings))
    finally:
        llm.chat_json = real_chat_json
    check("the build reports 14 posts created", result["posts_created"] == 14,
          str(result["posts_created"]))
    from app.db.session import Post
    rows = db2.query(Post).filter(Post.boost_id == boost2.id).all()
    check("14 Post rows are persisted", len(rows) == 14, str(len(rows)))
    check("every day 1..14 has a post", sorted(p.day for p in rows) == list(range(1, 15)),
          str(sorted(p.day for p in rows)))
    check("the plan carries 14 posts", len(result["plan"]["posts"]) == 14,
          str(len(result["plan"]["posts"])))
    check("the build says the model came up short and was completed",
          any("instead of 14" in n for n in result["notes"]), str(result["notes"])[:300])

    print()
    if FAILS:
        print(f"{FAILS} CHECK(S) FAILED")
        return 1
    print("ALL GALLERY SELECTION TESTS PASSED")
    return 0


# ── a portal URL carries the address the Trulia fallback needs ────────────────────────────
# Zillow and Redfin answer a datacenter IP with a bot wall, so the only route that still
# serves the gallery is the same property on Trulia, found by address. The address has to
# come from somewhere, and every portal spells it out in the URL path.

from app.services.photos import address_from_url

PORTAL_URLS = [
    ("https://www.zillow.com/homedetails/4422-Clay-St-Redding-CA-96003/15238205_zpid/",
     "4422 Clay St, Redding, CA 96003"),
    ("https://www.redfin.com/CA/Redding/1354-Harpole-Rd-96002/home/139453215",
     "1354 Harpole Rd, Redding, CA 96002"),
    ("https://www.realtor.com/realestateandhomes-detail/6495-Mojave-Ct_Anderson_CA_96007_M12345-67890",
     "6495 Mojave Ct, Anderson, CA 96007"),
]
for url, want in PORTAL_URLS:
    got = address_from_url(url)
    assert got == want, f"{url}\n   want {want!r}\n   got  {got!r}"
print(f"ok   {len(PORTAL_URLS)} portal URLs give up their address")
# A URL with no address in it must not invent one, or the Trulia fallback searches for a
# street that does not exist and the import looks like a wall rather than an empty field.
assert address_from_url("https://www.trulia.com/CA/Anderson/") == ""
assert address_from_url("https://example.com/") == ""
print("ok   a URL with no address returns nothing")

if __name__ == "__main__":
    sys.exit(main())
