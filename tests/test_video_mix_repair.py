"""The deterministic video-mix repair (doc 10 RHYTHM is a HARD rule).

Run:
    cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_video_mix_repair.py

No network, no LLM: the repair is a pure function of the plan.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.content_engine import _repair_video_mix  # noqa: E402
from app.services.plan_rules import validate_plan  # noqa: E402

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(f"{'ok  ' if ok else 'FAIL'} - {name}" + (f"  [{detail}]" if detail else ""))


def make_plan(n, video_positions=(), main_video_at=None):
    posts = []
    for i in range(n):
        if i in video_positions:
            p = {"kind": "main_video" if i == main_video_at else "short_video",
                 "videoFileId": f"v{i}", "caption": "c"}
        else:
            p = {"kind": "static", "postType": "photo", "photoFile": f"p{i}.jpg",
                 "caption": "c"}
        posts.append(p)
    return {"posts": posts}


def kinds(plan):
    return [p.get("kind") for p in plan["posts"]]


def videos(plan):
    return [k for k in kinds(plan) if k in ("main_video", "short_video")]


n = 14
target = -(-n // 3)  # ceil(n/3) = 5

print("=== too few videos is repaired up to the spec floor ===")
plan = make_plan(n, video_positions=(0, 5, 10), main_video_at=0)
plan, repairs = _repair_video_mix(plan, 14, 1)
check("video count raised to the floor", len(videos(plan)) == target, f"{len(videos(plan))} of {n}")
check("a repair is reported", len(repairs) == 1 and "5/14" in repairs[0], repairs)
check("no two videos are adjacent", not any(
    kinds(plan)[i] in ("main_video", "short_video") and kinds(plan)[i - 1] in ("main_video", "short_video")
    for i in range(1, n)))
check("exactly one main_video hero", kinds(plan).count("main_video") == 1)
check("demoted statics carry a photoFile", all(
    p.get("photoFile") for p in plan["posts"] if p.get("kind") == "static"))
check("validate_plan is then clean on the video rules",
      not [v for v in validate_plan(plan, 14, 1) if "video share" in v or "adjacent" in v],
      [v for v in validate_plan(plan, 14, 1) if "video" in v])

print("\n=== too many videos is repaired down ===")
plan2 = make_plan(10, video_positions=tuple(range(0, 10, 2)))  # 5 of 10 = half
plan2, repairs2 = _repair_video_mix(plan2, 10, 1)
check("video count brought under two fifths", len(videos(plan2)) == -(-10 // 3),
      f"{len(videos(plan2))} of 10")
check("a repair is reported", len(repairs2) == 1, repairs2)
check("the demoted posts became statics with a photo", kinds(plan2).count("static") == 6,
      kinds(plan2))

print("\n=== a length where the two bounds disagree (7 posts) still passes ===")
plan5 = make_plan(7, video_positions=(0, 3), main_video_at=0)
plan5, repairs5 = _repair_video_mix(plan5, 7, 1)
check("7-day plan repaired to the floor", len(videos(plan5)) == 3, kinds(plan5))
check("no unfixable 'above 2/5' violation is reported",
      not [v for v in validate_plan(plan5, 7, 1) if "video share" in v],
      [v for v in validate_plan(plan5, 7, 1) if "video" in v])

print("\n=== a plan already inside the band is left alone ===")
plan3 = make_plan(n, video_positions=(0, 4, 8, 12), main_video_at=0)  # 4/14 = 28.6% -> below 1/3
plan3, repairs3 = _repair_video_mix(plan3, 14, 1)
check("a below-floor plan is NOT left alone", len(repairs3) == 1, repairs3)

plan4 = make_plan(n, video_positions=(0, 3, 6, 9, 12), main_video_at=0)  # 5/14 -> in band
before = kinds(plan4)
plan4, repairs4 = _repair_video_mix(plan4, 14, 1)
check("an in-band plan is untouched", repairs4 == [] and kinds(plan4) == before, kinds(plan4))

print("\n=== the planner's stale 'no video posts' note is dropped after a repair ===")
from app.services.content_engine import _scrub_stale_video_notes  # noqa: E402

notes = ["Agent name was not given.",
         "No approved video library was provided and no video service was listed, so the "
         "campaign has no video posts.",
         "Bedrooms and price were not provided."]
plan6 = make_plan(14, video_positions=(0, 3, 6, 8, 11), main_video_at=0)
scrubbed = _scrub_stale_video_notes(notes, plan6)
check("the false 'no video posts' claim is gone", len(scrubbed) == 2 and "video" not in " ".join(scrubbed).lower(), scrubbed)
static_only = {"posts": [{"kind": "static"}]}
check("a genuinely video-free plan keeps the note",
      len(_scrub_stale_video_notes(notes, static_only)) == 3,
      _scrub_stale_video_notes(notes, static_only))

print("\n=== degenerate input is safe ===")
check("empty plan", _repair_video_mix({}, 14, 1)[1] == [])
check("no posts key", _repair_video_mix({"posts": []}, 14, 1)[1] == [])
check("not a dict", _repair_video_mix(None, 14, 1)[1] == [])

print(f"\n{sum(checks)} passed, {len(checks) - sum(checks)} failed")
print("ALL VIDEO MIX REPAIR TESTS PASSED" if all(checks) else "VIDEO MIX REPAIR TESTS FAILED")
sys.exit(0 if all(checks) else 1)
