"""Plain-assert test suite for app.services.plan_rules.validate_plan.

Run with:
    cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_plan_rules.py

No pytest in this venv, so this is a script: it prints one line per check and
exits 1 if any check fails. It builds a known-good 14-post plan (per_day=1) that
satisfies every hard rule, proves the validator finds ZERO violations on it, then
breaks one hard rule at a time and proves the validator catches each class.
"""

import copy
import json
import sys

from app.services.plan_rules import BANNED_WORDS, CLOSING_LINE_RE, validate_plan

FAILS = []


def check(cond, label):
    if cond:
        print(f"ok   - {label}")
    else:
        print(f"FAIL - {label}")
        FAILS.append(label)


# ---------------------------------------------------------------------------
# A known-good 14-post plan (days=14, per_day=1).
# ---------------------------------------------------------------------------
CLOSING = "Dana Rivers | 555-0142 | LIC DRE 01987654 | Rivers & Co Realty | Equal Housing Opportunity"
BODY = ("Morning light moves across this room and it is the best part of the day, "
        "coffee in hand and nowhere to be. By evening the whole place fills with "
        "friends and nobody wants to leave. It is the kind of spot that quietly "
        "becomes the heart of the home and stays that way.")
OVERLAY = "Where summer actually happens"
VIDEO_POS = [0, 3, 6, 8, 11]          # 5 videos, no two adjacent, 5/14 within [1/3, 2/5]
STATIC_TYPES = ["photo", "carousel", "photo", "question", "photo", "connect", "photo", "question", "photo"]


def good_plan():
    total = 14
    posts = []
    si = vi = 0
    for i in range(total):
        day = i + 1
        if i in VIDEO_POS:
            kind = "main_video" if vi == 0 else "short_video"
            posts.append({
                "day": day, "slot": 1, "kind": kind, "videoFileId": f"vid{vi + 1}",
                "postType": "", "photoFiles": [], "title": f"Video {i + 1}",
                "kicker": "THE TOUR" if vi == 0 else "WHERE THE DAY STARTS",
                "overlayText": "", "photoFile": "", "photoRoom": "",
                "caption": BODY + "\n" + CLOSING,
                "hashtags": ["#realestate", "#justlisted", "#tour"],
                "cta": "Message me for a private showing.", "notes": "video post",
            })
            vi += 1
        else:
            posts.append({
                "day": day, "slot": 1, "kind": "static", "videoFileId": "",
                "postType": STATIC_TYPES[si % len(STATIC_TYPES)], "photoFiles": [],
                "title": f"Post {i + 1}", "kicker": "THE ARRIVAL",
                "overlayText": OVERLAY, "photoFile": f"photo{si + 1}.jpg",
                "photoRoom": "living room", "caption": BODY + "\n" + CLOSING,
                "hashtags": ["#realestate", "#justlisted", "#home"],
                "cta": "Call or text me anytime.", "notes": "static post",
            })
            si += 1
    return {
        "summary": "Two sentences about the home.",
        "propertyStory": {"thesis": "t", "differentiators": ["1", "2", "3", "4", "5"],
                          "angles": ["a", "b", "c"]},
        "storyArc": "Front door to back fence.",
        "posts": posts,
        "ad": {"name": "Boost", "objective": "Traffic", "specialAdCategory": "HOUSING",
               "totalBudgetUsd": 50, "durationDays": 14, "locationRule": "15 mi",
               "audienceNotes": "none", "placements": "feeds", "primaryText": "hook",
               "headline": "h", "description": "d", "ctaButton": "Learn more",
               "creativeDays": [1, 2, 3]},
        "needsVerification": [], "missingInfo": [], "complianceFlags": [],
        "requiredOverlayLines": [CLOSING],
    }


def which(violations, needle):
    """Return the violations that mention `needle` (case-insensitive)."""
    return [v for v in violations if needle.lower() in v.lower()]


# ---------------------------------------------------------------------------
# 0. sanity: the fixture itself is clean, and the constants exist.
# ---------------------------------------------------------------------------
check(len(BANNED_WORDS) == 12, "BANNED_WORDS exposes the doc's 12 banned words")
check(bool(CLOSING_LINE_RE.match(CLOSING)), "CLOSING_LINE_RE matches the doc's closing-line form")
check(bool(CLOSING_LINE_RE.match(
    "Dana Rivers | MISSING | LIC MISSING | Rivers & Co Realty | Equal Housing Opportunity")),
    "CLOSING_LINE_RE accepts MISSING in the phone and license slots")

good = good_plan()
base_viol = validate_plan(good, 14, 1)
check(base_viol == [], f"known-good plan has zero violations (got {base_viol!r})")


# ---------------------------------------------------------------------------
# 1. exactly days*per_day posts
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
p["posts"].pop()
check(bool(which(validate_plan(p, 14, 1), "post count")), "catches wrong post count")

p = copy.deepcopy(good)
p["posts"] = None
check(validate_plan(p, 14, 1) == ["plan.posts is missing or not an array"],
      "catches a missing/!array posts field")


# ---------------------------------------------------------------------------
# 2. slots
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
p["posts"][0]["slot"] = 2
check(bool(which(validate_plan(p, 14, 1), "slots")), "catches a slot that is not 1 when per_day=1")

# per_day=2 needs slot 1 and 2 on every day
p2 = good_plan()
p2["posts"] = []
for day in range(1, 15):
    for slot in (1, 2):
        post = copy.deepcopy(good["posts"][0])
        post.update({"day": day, "slot": slot, "kind": "static", "photoFile": "x.jpg",
                     "overlayText": OVERLAY, "postType": "photo"})
        p2["posts"].append(post)
# make video share valid: 10 videos of 28 -> 10/28 in [1/3,2/5]
for i in range(0, 28, 3):
    p2["posts"][i]["kind"] = "main_video" if i == 0 else "short_video"
p2["posts"][1]["slot"] = 5   # break a slot
check(bool(which(validate_plan(p2, 14, 2), "slots")), "catches a bad slot when per_day=2")


# ---------------------------------------------------------------------------
# 3. no two video posts adjacent
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
p["posts"][1]["kind"] = "short_video"   # posts 0 and 1 both video
check(bool(which(validate_plan(p, 14, 1), "adjacent")), "catches two adjacent video posts")


# ---------------------------------------------------------------------------
# 4. video share
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
for post in p["posts"]:
    post["kind"] = "static"
    post["photoFile"] = post["photoFile"] or "x.jpg"
check(bool(which(validate_plan(p, 14, 1), "below 1/3")), "catches too few videos (below 1/3)")

p = copy.deepcopy(good)
for i, post in enumerate(p["posts"]):
    post["kind"] = "main_video" if i == 0 else "short_video"
check(bool(which(validate_plan(p, 14, 1), "above 2/5")), "catches too many videos (above 2/5)")


# ---------------------------------------------------------------------------
# 5. at most 3 question posts
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
statics = [x for x in p["posts"] if x["kind"] == "static"]
for s in statics[:4]:
    s["postType"] = "question"
check(bool(which(validate_plan(p, 14, 1), "at most 3")), "catches more than 3 question posts")


# ---------------------------------------------------------------------------
# 6. connect posts never two in a row
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
p["posts"][1]["postType"] = "connect"
p["posts"][2]["postType"] = "connect"
check(bool(which(validate_plan(p, 14, 1), "in a row")), "catches two connect posts in a row")


# ---------------------------------------------------------------------------
# 7. every static post has a photoFile
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
for s in p["posts"]:
    if s["kind"] == "static":
        s["photoFile"] = ""
        break
check(bool(which(validate_plan(p, 14, 1), "missing a photoFile")), "catches a static post with no photoFile")


# ---------------------------------------------------------------------------
# 8. video kinds
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
for s in p["posts"]:
    if s["kind"] in ("main_video", "short_video"):
        s["kind"] = "reel"
        break
check(bool(which(validate_plan(p, 14, 1), "invalid kind")), "catches an invalid video kind")


# ---------------------------------------------------------------------------
# 9/10. caption length + closing line
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
p["posts"][0]["caption"] = "Too short a caption here.\n" + CLOSING
check(bool(which(validate_plan(p, 14, 1), "35..60")), "catches a caption that is too short")

p = copy.deepcopy(good)
p["posts"][0]["caption"] = (" ".join(["word"] * 70)) + "\n" + CLOSING
check(bool(which(validate_plan(p, 14, 1), "35..60")), "catches a caption that is too long")

p = copy.deepcopy(good)
p["posts"][0]["caption"] = BODY   # no closing line
check(bool(which(validate_plan(p, 14, 1), "closing line")), "catches a caption with no closing line")

p = copy.deepcopy(good)
p["posts"][0]["caption"] = BODY + "\nDana Rivers | 555-0142 | DRE 0198 | Rivers & Co | EHO"
check(bool(which(validate_plan(p, 14, 1), "closing line")), "catches a malformed closing line")


# ---------------------------------------------------------------------------
# 11. banned words
# ---------------------------------------------------------------------------
for word in BANNED_WORDS:
    p = copy.deepcopy(good)
    p["posts"][0]["caption"] = ("This is a " + word + " home. ") + BODY + "\n" + CLOSING
    if not which(validate_plan(p, 14, 1), "banned word"):
        check(False, f"catches banned word {word!r}")
        break
else:
    check(True, "catches every one of the 12 banned words")


# ---------------------------------------------------------------------------
# 12. overlayText <= 8 words
# ---------------------------------------------------------------------------
p = copy.deepcopy(good)
p["posts"][1]["overlayText"] = "this overlay text has way too many words here"
check(bool(which(validate_plan(p, 14, 1), "at most 8")), "catches an overlayText over 8 words")


# ---------------------------------------------------------------------------
print()
if FAILS:
    print(f"{len(FAILS)} CHECK(S) FAILED")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL PLAN RULES TESTS PASSED")
