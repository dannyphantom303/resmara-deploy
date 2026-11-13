"""The campaign's creative rules: one space per campaign, copy about the photo it carries, and an
overlay that survives the build.

These are the rules the owner actually judges the campaign by. They live here, not in a prompt:
a model asked nicely will still put two shots of the primary suite on days 3 and 9.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import content_engine as ce  # noqa: E402


class Photo:
    def __init__(self, id, filename, room, score=5, tags=None, see="", story=""):
        self.id = id
        self.filename = filename
        self.original_name = filename
        self.url = "/uploads/" + filename
        self.kind = "photo"
        self.room = room
        self.social_score = score
        self.shape = "landscape"
        self.see = see
        self.story = story
        self.tags = tags or ["ROOM: " + room, "SOCIAL: " + str(score)]
        self.data = None


GALLERY = [
    Photo(1, "a.jpg", "Kitchen", 9),
    Photo(2, "b.jpg", "Primary Bedroom", 8),
    Photo(3, "c.jpg", "Kitchen", 8),          # same room, strong: must not both run
    Photo(4, "d.jpg", "Living Room", 7),
    Photo(5, "e.jpg", "Backyard", 6),
    Photo(6, "f.jpg", "Primary Bedroom", 6),  # second primary suite
    Photo(7, "g.jpg", "Front Exterior", 7),
    Photo(8, "h.jpg", "Bathroom", 6, tags=["ROOM: Bathroom", "POST: no"]),
    Photo(9, "i.jpg", "Dining Room", 6),
]


def plan(days=6, photo_files=("a.jpg", "c.jpg", "f.jpg", "a.jpg", "b.jpg", "d.jpg")):
    return [{"day": i + 1, "slot": 1, "kind": "static", "photoFile": f,
             "caption": "Caption for " + f, "title": "", "overlayText": ""}
            for i, f in enumerate(photo_files[:days])]


def test_room_family_collapses_aliases():
    assert ce.room_family(Photo(1, "x.jpg", "Primary Bedroom")) == "primary bedroom"
    assert ce.room_family(Photo(2, "x.jpg", "Master Suite")) == "primary bedroom"
    assert ce.room_family(Photo(3, "x.jpg", "Aerial")) == "aerial"
    assert ce.room_family(Photo(4, "x.jpg", "")) == "photo-4"
    print("ok   room families collapse")


def test_no_space_repeats_while_rooms_remain():
    posts = plan()
    got = ce.assign_gallery(posts, GALLERY)
    spaces = [ce.room_family(Photo(0, "", g["room"])) if g["room"] else "" for g in got]
    used = [s for s in spaces if s]
    assert len(used) == len(set(used)), f"a space ran twice: {spaces}"
    assert all(g["url"] for g in got), "every post must carry a photo"
    # And an unusable bathroom shot never makes it onto the calendar.
    assert not any("h.jpg" in g["file"] for g in got), "a POST: no photo was used"
    print("ok   no space repeats, unusable photo skipped")


def test_repeat_only_when_the_house_runs_out_of_rooms():
    posts = plan(days=10, photo_files=tuple("a.jpg" for _ in range(10)))
    got = ce.assign_gallery(posts, GALLERY)
    assert all(g["url"] for g in got), "ten posts, so a space has to repeat, but never a blank"
    rooms = [g["room"] for g in got if g["room"]]
    # The first six use six different spaces; a repeat may only happen after that.
    assert len(set(rooms[:6])) == 6, f"the first six posts repeated a space: {rooms[:6]}"
    print("ok   repeats only once the rooms are used up")


def test_a_moved_post_is_flagged_for_new_copy():
    got = ce.assign_gallery(plan(), GALLERY)
    assert any(g["replaced"] for g in got), "a post that lost its plan photo must be rewritten"
    assert not got[0]["replaced"], "the first post keeps the photo the plan named"
    print("ok   moved posts are flagged")


def test_rewrite_falls_back_to_the_photos_own_tags():
    posts = plan()
    got = ce.assign_gallery(posts, GALLERY)

    async def boom(*a, **k):
        raise RuntimeError("model down")

    original = ce.llm.chat_json
    ce.llm.chat_json = boom
    try:
        written = asyncio.run(ce._rewrite_creative(
            posts, got, address="1 Test St", brand_json="{}", facts="3 bed",
            closing_line="Call Test Agent", engine_notes=[]))
    finally:
        ce.llm.chat_json = original
    assert written == 0
    for i, p in enumerate(posts):
        if got[i]["replaced"] and (p.get("kind") or "static") == "static":
            room = (got[i]["room"] or "").lower()
            assert room.split()[0] in p["caption"].lower(), \
                f"day {p['day']} caption does not name its own photo: {p['caption']!r}"
            assert "Call Test Agent" in p["caption"], "the closing line is missing"
            body = p["caption"].split("Call Test Agent")[0]
            assert 35 <= len(body.split()) <= 60, \
                f"day {p['day']} caption is {len(body.split())} words, outside the 35..60 rule"
            assert p["overlayText"], "the post has no text overlay"
    print("ok   failed rewrite still describes the right photo")


def test_rewrite_uses_the_model_when_it_answers():
    posts = plan()
    got = ce.assign_gallery(posts, GALLERY)
    days = [(p["day"], i) for i, p in enumerate(posts) if got[i]["replaced"]]

    async def fake(system, user, **kwargs):
        return {"posts": [{"day": d, "slot": 1, "title": "Sunlit kitchen",
                           "kicker": "THE KITCHEN", "overlayText": "Room to gather",
                           "caption": "Written for the photo on day " + str(d),
                           "hashtags": ["kitchen", "homes"]} for d, _ in days]}

    original = ce.llm.chat_json
    ce.llm.chat_json = fake
    try:
        written = asyncio.run(ce._rewrite_creative(
            posts, got, address="1 Test St", brand_json="{}", facts="3 bed",
            closing_line="Call Test Agent", engine_notes=[]))
    finally:
        ce.llm.chat_json = original
    assert written == len(days)
    i = days[0][1]
    assert posts[i]["title"] == "Sunlit kitchen"
    assert posts[i]["overlayText"] == "Room to gather"
    assert "Call Test Agent" in posts[i]["caption"], "closing line appended when the model omits it"
    print("ok   model copy lands, closing line enforced")


def test_overlay_never_exceeds_a_readable_line():
    assert ce._overlay_from("A" * 90, "Kitchen") == "A" * 42
    assert ce._overlay_from("", "Primary Bedroom") == "Primary Bedroom"
    assert ce._overlay_from("  Bright   light  ", "") == "Bright light"
    print("ok   overlay text is short and single-spaced")


def test_video_posts_keep_their_own_clip_and_use_up_no_room():
    posts = plan()
    posts[0].update(kind="short_video", photoFile="clip.mp4")
    clip = Photo(50, "clip.mp4", "")
    clip.kind = "video"
    got = ce.assign_gallery(posts, GALLERY + [clip])
    assert got[0]["file"] == "clip.mp4" and not got[0]["replaced"], \
        "a video post must keep its own clip, not borrow a photo"
    statics = [g for g in got[1:] if g["kind"] == "static" and g["room"]]
    assert len({ce.room_family(type("A", (), {"room": g["room"], "id": 0})()) for g in statics}) >= 4, \
        "the static posts must still spread across the house"
    print("ok   video posts keep their clip and leave the rooms alone")


def test_every_photo_is_used_before_any_photo_repeats():
    posts = plan(days=8, photo_files=tuple("a.jpg" for _ in range(8)))
    got = ce.assign_gallery(posts, GALLERY)          # 9 photos, one of them disliked
    urls = [g["url"] for g in got]
    assert len(set(urls)) == 8, f"a photo repeated while unused photos remained: {urls}"
    assert "h.jpg" in [g["file"] for g in got], "the disliked photo is used once the liked ones run out"
    print("ok   every photo runs before any photo repeats")


def test_a_repeated_photo_is_as_far_apart_as_the_gallery_allows():
    posts = plan(days=9, photo_files=tuple("zzz.jpg" for _ in range(9)))  # nothing named, so all fall back
    got = ce.assign_gallery(posts, GALLERY)
    urls = [g["url"] for g in got]
    seen = {}
    for i, u in enumerate(urls):
        if u in seen:
            assert i - seen[u] >= 5, f"{u} repeated {i - seen[u]} posts apart: {urls}"
        seen[u] = i
    print("ok   repeats are spread across the calendar")


def test_a_video_photo_is_never_shown_again_as_a_still():
    posts = plan(days=6)
    posts[0].update(kind="short_video", photoFile="a.jpg")   # the kitchen clip
    got = ce.assign_gallery(posts, GALLERY)
    assert got[0]["file"] == "a.jpg"
    assert all(g["file"] != "a.jpg" for g in got[1:]), \
        "the photo the video animates must not run again as a still"
    print("ok   a video's photo does not reappear as a still")


def test_an_address_is_never_the_overlay():
    assert ce._overlay_from("6495 Mojave Court", "Kitchen", "6495 Mojave Court, Anderson, CA") == "Kitchen"
    assert ce._overlay_from("1200 Elm St", "Kitchen", "") == "Kitchen"
    assert ce._overlay_from("Room to gather", "Kitchen", "") == "Room to gather"
    print("ok   an overlay is never just the address")


if __name__ == "__main__":
    test_room_family_collapses_aliases()
    test_no_space_repeats_while_rooms_remain()
    test_repeat_only_when_the_house_runs_out_of_rooms()
    test_a_moved_post_is_flagged_for_new_copy()
    test_video_posts_keep_their_own_clip_and_use_up_no_room()
    test_every_photo_is_used_before_any_photo_repeats()
    test_a_repeated_photo_is_as_far_apart_as_the_gallery_allows()
    test_a_video_photo_is_never_shown_again_as_a_still()
    test_an_address_is_never_the_overlay()
    test_rewrite_falls_back_to_the_photos_own_tags()
    test_rewrite_uses_the_model_when_it_answers()
    test_overlay_never_exceeds_a_readable_line()
    print("ALL CAMPAIGN CREATIVE TESTS PASSED")
