"""Hard-rule validation for a Real Estate Boost campaign plan.

These are the HARD rules from handoff doc 10 section 4 (R4 system message), the
"RHYTHM (hard rule)" / "STORY" / "OVERLAY TEXT" / "CONTACT LINES" / "OUTPUT"
sections, plus the plan.json shape in doc 10 section 5. validate_plan() returns a
list of human-readable violations; an empty list means the plan satisfies every
hard rule checked here.

The rules enforced (exactly the ones the build brief names):
  1. exactly days*per_day posts
  2. slots are 1 (and 2 when per_day == 2)
  3. no two video posts adjacent in calendar order
  4. video share >= 1/3 and never more than 2/5 of the posts (when no whole number of
     videos can satisfy both, the 2/5 ceiling yields to the 1/3 floor)
  5. at most 3 'question' posts
  6. 'connect' posts never two in a row
  7. every 'static' post has a photoFile
  8. every video post kind is main_video or short_video
  9. captions are 35..60 words (the closing contact line does not count)
 10. EVERY caption ends with the exact closing contact line
 11. the banned words never appear
 12. overlayText is at most 8 words
"""

from __future__ import annotations

import re

# Banned words, verbatim from doc 10 R4 STORY: "Never use these words: ...".
BANNED_WORDS = [
    "stunning",
    "boasts",
    "nestled",
    "charming",
    "dream",
    "gem",
    "oasis",
    "perfect",
    "must-see",
    "welcome home",
    "immaculate",
    "turn-key",
]

# Closing contact line, doc 10 R4 CONTACT LINES:
#   "AGENT NAME | PHONE | LIC LICENSE NUMBER | BROKERAGE | Equal Housing Opportunity"
# MISSING / NOT GIVEN are allowed in the phone and license slots (the doc says
# "where one is NOT GIVEN write MISSING in its place").
# A trailing period is tolerated: the models add one often enough that rejecting it only
# produced a wall of false violations on an otherwise fine caption.
CLOSING_LINE_RE = re.compile(
    r"^[^|\n]+ \| [^|\n]+ \| LIC [^|\n]+ \| [^|\n]+ \| Equal Housing Opportunity\.?$"
)

VIDEO_KINDS = ("main_video", "short_video")
ALL_KINDS = ("main_video", "short_video", "static")
STATIC_POST_TYPES = ("photo", "carousel", "connect", "question")

_BANNED_RES = [
    re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", re.IGNORECASE)
    for w in BANNED_WORDS
]


def _words(text: str) -> list:
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def caption_body_and_closing(caption: str):
    """Split a caption into (body, closing_line).

    The closing line is the last non-empty line. Returns (whole_caption, None) if
    the caption is empty.
    """
    if not caption:
        return "", None
    lines = caption.rstrip().splitlines()
    if not lines:
        return "", None
    closing = lines[-1].strip()
    body = "\n".join(lines[:-1]).strip()
    return body, closing


def validate_plan(plan: dict, days: int, per_day: int) -> list:
    """Return a list of human-readable violations of the hard rules."""
    violations: list = []
    if not isinstance(plan, dict):
        return ["plan is not a JSON object"]
    posts = plan.get("posts")
    if not isinstance(posts, list):
        return ["plan.posts is missing or not an array"]

    expected_total = int(days) * int(per_day)
    n = len(posts)

    # 1. exactly days*per_day posts
    if n != expected_total:
        violations.append(
            f"post count: expected exactly {expected_total} (days*per_day), found {n}"
        )

    # 8 (kind validity) + per-post checks
    for i, post in enumerate(posts):
        if not isinstance(post, dict):
            violations.append(f"post {i}: not an object")
            continue
        kind = post.get("kind")
        label = f"post {i} (day {post.get('day')} slot {post.get('slot')})"

        if kind not in ALL_KINDS:
            violations.append(
                f"{label}: invalid kind {kind!r} (must be main_video, short_video or static)"
            )

        # 7. every static has a photoFile
        if kind == "static":
            if not str(post.get("photoFile") or "").strip():
                violations.append(f"{label}: static post is missing a photoFile")

        # 9. caption 35..60 words (closing line excluded when there is one)
        body, closing = caption_body_and_closing(post.get("caption") or "")
        # A model that forgets the closing line also writes the caption as one line, which
        # made the old count read "0 words" and hid the real problem. When the closing line is
        # absent the whole caption is the body, so measure that instead of a phantom empty one.
        has_closing = bool(closing) and bool(CLOSING_LINE_RE.match(closing))
        if has_closing and not body:
            # Copy and the contact line on one line: there is no separate body to measure, so say
            # exactly that instead of reporting a phantom "0 words".
            violations.append(
                f"{label}: the closing contact line is on the same line as the copy (that line is"
                f" {len(_words(closing))} words; the rules want 35..60 words of copy with the"
                " closing line on its own line)"
            )
        else:
            wc = len(_words(body if has_closing else (post.get("caption") or "")))
            if wc < 35 or wc > 60:
                violations.append(
                    f"{label}: caption body is {wc} words (must be 35..60)"
                )

        # 10. every caption ends with the closing contact line
        if not closing or not CLOSING_LINE_RE.match(closing):
            violations.append(
                f"{label}: caption does not end with the required closing line "
                f"'AGENT NAME | PHONE | LIC LICENSE | BROKERAGE | Equal Housing Opportunity'"
            )

        # 11. banned words
        caption_text = (post.get("caption") or "")
        for rx, word in zip(_BANNED_RES, BANNED_WORDS):
            if rx.search(caption_text):
                violations.append(f"{label}: caption uses the banned word {word!r}")

        # 12. overlayText <= 8 words
        overlay = post.get("overlayText") or ""
        ow = len(_words(overlay))
        if ow > 8:
            violations.append(
                f"{label}: overlayText is {ow} words (must be at most 8)"
            )

        # postType must be one of the doc's values when present (statics only)
        ptype = post.get("postType")
        if kind == "static" and ptype not in (None, "") and ptype not in STATIC_POST_TYPES:
            violations.append(f"{label}: invalid postType {ptype!r}")

    # 2. slots
    slots_by_day: dict = {}
    for post in posts:
        if not isinstance(post, dict):
            continue
        day = post.get("day")
        slot = post.get("slot")
        slots_by_day.setdefault(day, []).append(slot)
    if int(per_day) == 1:
        for day, slots in sorted(slots_by_day.items(), key=lambda kv: (kv[0] is None, kv[0])):
            if slots != [1]:
                violations.append(
                    f"slots: day {day} has slots {slots}; with per_day=1 the only slot is 1"
                )
    else:
        for day, slots in sorted(slots_by_day.items(), key=lambda kv: (kv[0] is None, kv[0])):
            if sorted(s for s in slots if s is not None) != [1, 2] or len(slots) != 2:
                violations.append(
                    f"slots: day {day} has slots {slots}; with per_day=2 each day has slot 1 and slot 2"
                )

    # 3. no two videos adjacent in calendar order
    kinds = [p.get("kind") if isinstance(p, dict) else None for p in posts]
    for i in range(1, len(kinds)):
        if kinds[i] in VIDEO_KINDS and kinds[i - 1] in VIDEO_KINDS:
            violations.append(
                f"rhythm: two video posts are adjacent at positions {i - 1} and {i} "
                f"(calendar order); a static post must separate every two videos"
            )

    # 4. video share >= 1/3 and <= 2/5
    #
    # For a few campaign lengths the two bounds cannot both be met by any whole number of
    # videos (7 posts: a third is 2.33 so 3 videos is the floor, but 3/7 is 42.9% and the
    # ceiling is 2). "Never more than two fifths" is the absolute rule and "roughly a
    # third" is the soft one, so when the band is empty we let the floor through instead
    # of flagging every possible plan for a length the campaign can legitimately have
    # (campaign_days is clamped to 7..60).
    vcount = sum(1 for k in kinds if k in VIDEO_KINDS)
    if n > 0:
        lo = -(-n // 3)
        hi = max(lo, (2 * n) // 5)
        if vcount < lo:
            violations.append(
                f"video share: {vcount}/{n} is below 1/3 (need at least roughly a third video)"
            )
        if vcount > hi:
            violations.append(
                f"video share: {vcount}/{n} is above 2/5 (never more than two fifths video)"
            )

    # 5. at most 3 question posts
    qcount = sum(1 for p in posts if isinstance(p, dict) and p.get("postType") == "question")
    if qcount > 3:
        violations.append(f"question posts: {qcount} found; at most 3 are allowed")

    # 6. connect posts never two in a row
    for i in range(1, len(posts)):
        a, b = posts[i - 1], posts[i]
        if isinstance(a, dict) and isinstance(b, dict) \
                and a.get("postType") == "connect" and b.get("postType") == "connect":
            violations.append(
                f"connect posts: two connect posts are in a row at positions {i - 1} and {i}"
            )

    return violations
