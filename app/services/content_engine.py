"""Resmara content engine - the AI campaign pipeline (handoff doc 10).

Pipeline, in doc order:
    R1  research the property on public pages   (Responses API, web_search)
    R2  learn the agent's brand                  (Chat Completions -> JSON)
    R3  current best post styles + this brand    (Responses API, web_search)
    R4  draft the whole campaign plan            (Chat Completions -> JSON)
then validate_plan() records any hard-rule violations, and the plan is persisted
onto the Boost / Post / Ad rows.

Everything the prompts need comes from the Boost row plus `openings` (a plain dict
the HTTP layer can pass straight through) falling back to
boost.ad_brief['agent_card'], then boost.property_facts for the facts. Resmara has
no monday.com ticket; those are the two places the "agent card" fields live:

    agent_name, phone, license, brokerage, instagram, website, property_website,
    facts, notes, video_transcript

`facts` maps to the doc's Property Facts (trusted over research); `notes` maps to
the doc's "AI Notes / TEAM CORRECTIONS FOR THE AI" (they override everything).
AGENT PHONE / AGENT LICENSE NUMBER / BROKERAGE come only from those sources: when
one is absent the closing line writes MISSING in that slot (doc 10) and the field
is reported in missing_info. Nothing here ever invents an ad spend or a metric.

Offline: when llm.llm_available() is False the whole pipeline still runs on the
deterministic fixtures in app.services.llm and the result carries source="offline".
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.core.config import settings
from app.db.session import Ad, Asset, Post
from app.services import llm, prompts
from app.services.plan_rules import CLOSING_LINE_RE, caption_body_and_closing, validate_plan

# The agent-card keys the pipeline understands (doc 10 inputs, reshaped for Resmara).
AGENT_CARD_KEYS = (
    "agent_name", "phone", "license", "brokerage", "instagram", "website",
    "property_website", "facts", "notes", "video_transcript",
    # optional extras the HTTP layer may also pass through:
    "services", "video_library", "per_day", "page_head", "page_text",
    "property_page_text",
)

# The doc-14 ROOM values (used only for a sanity check on offline tagging).
_DOC_ROOMS = {
    "front exterior", "rear exterior", "aerial", "street view", "kitchen",
    "living room", "dining room", "primary bedroom", "other bedroom", "bathroom",
    "laundry", "garage", "office", "backyard", "pool", "view", "detail",
    "floor plan", "other",
}

_TAG_KEYS = ("POST", "ROOM", "FEATURE", "SCALE", "SOCIAL", "WHY")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _first(*values):
    """First value that is neither None nor an empty string / empty list."""
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        if isinstance(v, (list, dict)) and len(v) == 0:
            continue
        return v
    return ""


def _clamp_days(value, default: int = 14) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = default
    return max(7, min(60, days))


def _clamp_per_day(value) -> int:
    try:
        per_day = int(value)
    except (TypeError, ValueError):
        per_day = 1
    return 2 if per_day >= 2 else 1


def _agent_card(boost, openings):
    """Resolve the agent card from openings -> ad_brief.agent_card -> property_facts."""
    card: dict = {}
    brief = getattr(boost, "ad_brief", None) or {}
    if isinstance(brief, dict):
        ac = brief.get("agent_card") or {}
        if isinstance(ac, dict):
            card.update(ac)
    if isinstance(openings, dict):
        card.update({k: v for k, v in openings.items() if k in AGENT_CARD_KEYS})
    # facts fall back to boost.property_facts last.
    if not card.get("facts"):
        card["facts"] = getattr(boost, "property_facts", None) or ""
    return card


def _trunc(text, limit: int) -> str:
    text = text or ""
    return text[:limit]


# ---------------------------------------------------------------------------
# PHOTO INDEX (doc 10 section 2, built from the Asset rows)
# ---------------------------------------------------------------------------
def build_photo_index(assets) -> str:
    """One line per photo Asset, fields in the doc's order, joined by ' ;; '.

    Line:  file name | id | room | social score | shape | what is visible (SEE) | STORY detail
    with any tags appended. Only kind == 'photo' rows are included; references,
    headshots and designs are skipped. Returns '' when there are no photos.
    """
    lines = []
    for a in assets or []:
        if getattr(a, "kind", "photo") != "photo":
            continue
        parts = [
            str(getattr(a, "filename", "") or ""),
            str(getattr(a, "id", "") or ""),
            str(getattr(a, "room", "") or ""),
            str(getattr(a, "social_score", "") or ""),
            str(getattr(a, "shape", "") or ""),
            str(getattr(a, "see", "") or ""),
            str(getattr(a, "story", "") or ""),
        ]
        line = " | ".join(parts)
        tags = getattr(a, "tags", None) or []
        if tags:
            line = line + " | " + " ".join(str(t) for t in tags)
        original = str(getattr(a, "original_name", "") or "")
        if original and original != parts[0]:
            # Human-readable hint; the first field stays the unique name photoFile matches on.
            line = line + " | upload: " + original
        lines.append(line)
    return " ;; ".join(lines)


def _asset_url_map(assets) -> dict:
    """filename -> url (and original_name -> url) for image_url matching."""
    m: dict = {}
    for a in assets or []:
        if getattr(a, "filename", None):
            m[a.filename] = a.url
        if getattr(a, "original_name", None):
            m.setdefault(a.original_name, a.url)
    return m


# ---------------------------------------------------------------------------
# Photo tagging (doc 14 verbatim prompt)
# ---------------------------------------------------------------------------
def _parse_tag_line(line: str) -> dict:
    out: dict = {}
    for seg in (line or "").split("|"):
        if ":" not in seg:
            continue
        k, v = seg.split(":", 1)
        out[k.strip().upper()] = v.strip()
    return out


def _tags_from_parsed(parsed: dict) -> list:
    tags = []
    for key in _TAG_KEYS:
        if key in parsed and parsed[key] != "":
            tags.append(f"{key}: {parsed[key]}")
    return tags


def _uploads_dir() -> Path:
    """Absolute uploads directory, whatever the app was started from."""
    d = Path(settings.UPLOAD_DIR)
    return d if d.is_absolute() else (Path(__file__).resolve().parents[2] / d)


_CLOSING_HINT_RE = re.compile(r"equal housing opportunity", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


def _split_inline_contact(caption: str):
    """(copy, contact_line) when the contact line shares a line with the copy, else None.

    A small model likes to write the whole caption on one line, ending it with
    "<agent> | <phone> | LIC <licence> | <brokerage> | Equal Housing Opportunity". The contact
    line is always the last four pipe-separated fields, so walk back four pipes and then cut that
    first field at its last sentence end: everything before it is copy, everything after belongs to
    the contact line. The copy is preserved word for word; only whitespace moves.
    """
    if not isinstance(caption, str):
        return None
    text = caption.strip()
    if "\n" in text or not _CLOSING_HINT_RE.search(text):
        return None
    pipes = [i for i, ch in enumerate(text) if ch == "|"]
    if len(pipes) < 4:
        return None
    last_four = pipes[-4:]
    earlier = [p for p in pipes if p < last_four[0]]
    field_start = earlier[-1] + 1 if earlier else 0
    # The contact line's first field (the agent slot) is glued to the end of the copy, so split
    # that one field at its last sentence end.
    field = text[field_start:last_four[0]]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(field)]
    if not ends:
        return None
    cut = field_start + ends[-1]
    copy = text[:cut].strip()
    contact = text[cut:].strip()
    if not copy or "|" not in contact:
        return None
    return copy, contact


def _normalise_closing_lines(plan: dict, closing_line: str) -> int:
    """Make every caption end with this campaign's own closing contact line.

    The prompt asks the model to end each caption with "<agent> | <phone> | LIC <licence> |
    <brokerage> | Equal Housing Opportunity"; a small model instead writes the instruction's
    placeholders back ("NAME ON THE TICKET | PHONE NOT GIVEN | LICENSE NUMBER NOT GIVEN | ...").
    The documented rule is that a value that was not given prints MISSING in its slot, so this
    swaps such a line for the one the engine builds from the agent card, and appends it when the
    caption has none. Only the contact line is touched - the copy is never rewritten.

    Returns how many captions were changed.
    """
    posts = plan.get("posts") if isinstance(plan, dict) else None
    if not isinstance(posts, list) or not closing_line:
        return 0
    changed = 0
    for post in posts:
        if not isinstance(post, dict):
            continue
        caption = post.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            continue
        inline = _split_inline_contact(caption)
        if inline:
            # Copy and contact line on one line: keep the copy, rebuild the contact line.
            post["caption"] = inline[0] + "\n" + closing_line
            changed += 1
            continue
        body, closing = caption_body_and_closing(caption)
        if closing and CLOSING_LINE_RE.match(closing.strip()):
            continue
        looks_like_contact_line = bool(closing) and (
            bool(_CLOSING_HINT_RE.search(closing)) or closing.count("|") >= 3
        )
        if looks_like_contact_line:
            post["caption"] = (body + "\n" if body else "") + closing_line
        else:
            post["caption"] = caption.rstrip() + "\n" + closing_line
        changed += 1
    return changed


_INLINE_CLOSING_RE = re.compile(
    r"\s+(?=\S[^|\n]*\s\|\s[^|\n]*\s\|\s*LIC\b)", re.IGNORECASE
)


def _split_inline_closing(plan: dict, agent: str = "") -> int:
    """Move a closing contact line that shares a line with the copy onto its own line.

    A small model often writes "prose ... AGENT | PHONE | LIC 123 | BROKERAGE | Equal Housing
    Opportunity." as ONE line. The spec wants the closing line on its own line, and the
    validator read that single line as a caption body of zero words. This is a mechanical
    format fix: no words are added, removed or reordered.

    Returns how many captions were split.
    """
    posts = plan.get("posts") if isinstance(plan, dict) else None
    if not isinstance(posts, list):
        return 0
    name = (agent or "").strip()
    split = 0
    for post in posts:
        if not isinstance(post, dict):
            continue
        caption = post.get("caption")
        if not isinstance(caption, str) or "\n" in caption:
            continue
        if not CLOSING_LINE_RE.match(caption.strip()):
            continue
        # Only the agent's own name tells us where the copy ends and the contact line begins; the
        # model wraps prose, agent, phone, licence and brokerage into the same pipe-fields, so
        # without a name any other cut would move real copy onto the closing line. No name, no
        # edit - validate_plan() then reports the shared line for a human to fix.
        cut = caption.rfind(name) if name else -1
        if cut <= 0:
            continue
        post["caption"] = caption[:cut].rstrip() + "\n" + caption[cut:].strip()
        split += 1
    return split


def _as_int(value):
    """A model-supplied number as an int, or None when it is not a single number.

    The plan is written by an LLM: a free local model in particular will occasionally answer
    a day (or one entry of ad.creativeDays) with a list or a range. That used to raise
    TypeError inside the build and reach the client as an opaque 502.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        return int(match.group()) if match else None
    return None


def _image_content_url(asset, root: str) -> str:
    """A URL the vision model can actually fetch.

    Local uploads go out inline as a data URL. The public /uploads path sits behind the
    Command Center session gate, so handing that URL to the model gets it a redirect to a
    login page instead of the photo - the model then answers about nothing, or the call
    times out, and the tag step reports 'tagged: 0' on a photo that is perfectly fine. A
    data URL needs no public exposure and no token, and keeps the photo on this machine
    apart from the single model request.
    """
    name = str(getattr(asset, "filename", "") or "")
    if name:
        path = _uploads_dir() / name
        try:
            if path.is_file():
                raw = path.read_bytes()
                if len(raw) <= 8 * 1024 * 1024:
                    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        except OSError:
            pass  # fall through to the URL form
    url = str(getattr(asset, "url", "") or "")
    if url.startswith("/") and root:
        return root + url
    return url


async def tag_assets(assets, *, base_url: str = "", db=None) -> dict:
    """Tag Asset rows with the doc-14 photo-tagging prompt.

    Each Asset image is sent to the vision model as an image_url content part so
    the model can actually see the photo. Fills room, social_score, shape, see,
    story and tags, and sets tagged_by='ai'. One failing photo never aborts the
    batch. Returns {'tagged': N, 'source': 'openai'|'offline', 'errors': [...]}.
    """
    assets = list(assets or [])
    root = (base_url or settings.PUBLIC_BASE_URL or "").rstrip("/")
    # Name the engine that actually saw the photo. "openai" used to be hard-coded whenever any
    # model was reachable, which mislabelled a local vision model as OpenAI.
    info = llm.engine_info() or {}
    if not llm.llm_available():
        source = "offline"
    elif llm.is_openai_native():
        source = "openai"
    else:
        source = info.get("host") or info.get("provider") or "custom"
    tagged = 0
    errors = []

    for a in assets:
        try:
            image_url = _image_content_url(a, root)
            line = await llm.chat_text(
                prompts.PHOTO_TAGGING_PROMPT,
                "Tag this listing photo.",
                model=settings.OPENAI_MODEL_CHECK,
                images=[image_url] if image_url else None,
                max_completion_tokens=400,
            )
            parsed = _parse_tag_line(line)
            # Deterministic offline fixture always parses to a full tag set.
            a.room = parsed.get("ROOM", getattr(a, "room", None))
            a.social_score = parsed.get("SOCIAL", getattr(a, "social_score", None))
            a.shape = parsed.get("SHAPE", getattr(a, "shape", None))
            a.see = parsed.get("SEE", getattr(a, "see", None))
            a.story = parsed.get("STORY", getattr(a, "story", None))
            a.tags = _tags_from_parsed(parsed)
            a.tagged_by = "ai"
            # A reply that parses to nothing is not a tag. Counting it made the endpoint report
            # "tagged=1" for a photo with no room and no tags at all.
            if not (a.room or a.tags):
                errors.append({
                    "asset_id": getattr(a, "id", None),
                    "filename": getattr(a, "filename", None),
                    "error": (
                        "the vision model returned no usable tags for this photo"
                        f" (engine={info.get('host') or 'unknown'},"
                        f" model={settings.OPENAI_MODEL_CHECK}); reply began"
                        f" {(line or '')[:120]!r}"
                    ),
                })
                continue
            if db is not None:
                db.add(a)
            tagged += 1
        except Exception as exc:  # keep going: one bad photo must not stop the batch
            errors.append({
                "asset_id": getattr(a, "id", None),
                "filename": getattr(a, "filename", None),
                "error": f"{type(exc).__name__}: {exc}",
            })

    if db is not None:
        db.commit()
    return {"tagged": tagged, "source": source, "errors": errors}


# ---------------------------------------------------------------------------
# The campaign build
# ---------------------------------------------------------------------------
def _scrub_stale_video_notes(missing_info: list, plan: dict) -> list:
    """Drop the planner's 'no video posts' claim once the repair has added some.

    The model writes its missingInfo before we adjust the mix, so after a repair that
    sentence is simply false and would tell the team not to expect video on a campaign
    that now has it. Every other note is kept.
    """
    posts = plan.get("posts") if isinstance(plan, dict) else None
    has_video = any(
        isinstance(p, dict) and p.get("kind") in ("main_video", "short_video")
        for p in (posts or [])
    )
    if not has_video:
        return list(missing_info or [])
    keep = []
    for note in missing_info or []:
        if re.search(r"no video (posts|content)|has no video", str(note), re.I):
            continue
        keep.append(note)
    return keep


def _repair_video_mix(plan: dict, days: int, per_day: int):
    """Put the video posts back into the spec's rhythm before we validate.

    The doc-10 rule is a hard one: at least roughly a third of the posts are video, never
    more than two fifths, and no two videos sit next to each other. A model that returns
    3 videos out of 14 has broken the rhythm rule and, left alone, the campaign ships
    wrong. So we rebuild the kind pattern from the spec's own even spacing, keep which
    video is the hero (main_video) if the plan named one, and give any slot demoted to a
    static the plan's own placeholder when it has no photoFile (doc 10: 'NEEDS PHOTO').

    Returns (plan, repairs) - repairs is a list of human-readable notes, empty when the
    plan already followed the rule.
    """
    if not isinstance(plan, dict):
        return plan, []
    posts = plan.get("posts")
    if not isinstance(posts, list) or not posts:
        return plan, []

    n = len(posts)
    target = llm._video_count(n)
    if target <= 0:
        return plan, []

    kinds = [p.get("kind") if isinstance(p, dict) else None for p in posts]
    current = sum(1 for k in kinds if k in ("main_video", "short_video"))
    if 3 * current >= n and 5 * current <= 2 * n:
        return plan, []  # already inside the band; leave the model's choice alone

    positions = set(llm._video_positions(n, target))
    hero = next((i for i, k in enumerate(kinds) if k == "main_video"), None)
    if hero is not None and hero not in positions:
        hero = None
    repairs = [f"video mix: {current}/{n} video posts repaired to {target}/{n} "
               f"at positions {sorted(positions)}"]

    for i, post in enumerate(posts):
        if not isinstance(post, dict):
            continue
        want_video = i in positions
        is_video = kinds[i] in ("main_video", "short_video")
        if want_video and not is_video:
            post["kind"] = "main_video" if hero is None else "short_video"
            if hero is None:
                hero = i
            post.setdefault("videoFileId", "")
            post.pop("postType", None)
        elif want_video and is_video and hero is None and kinds[i] == "main_video":
            hero = i
        elif not want_video and is_video:
            post["kind"] = "static"
            post.setdefault("postType", "photo")
            if not str(post.get("photoFile") or "").strip():
                post["photoFile"] = "NEEDS PHOTO"
            post.pop("videoFileId", None)
        if want_video and is_video and post.get("kind") == "main_video" and hero not in (None, i):
            post["kind"] = "short_video"
    return plan, repairs


async def build_campaign(boost, db, *, force: bool = False, base_url: str = "",
                         openings=None) -> dict:
    """Run R1 -> R2 -> R3 -> R4, validate, and persist the campaign.

    See the module docstring for where each prompt field comes from.
    """
    # Name the engine honestly: a local Ollama base is not OpenAI, and the build response feeds
    # the UI note about who drafted the calendar.
    info = llm.engine_info() or {}
    if not llm.llm_available():
        source = "offline"
    elif llm.is_openai_native():
        source = "openai"
    else:
        source = info.get("host") or info.get("provider") or "custom"
    engine = llm.engine_info()
    # engine_notes is the build's own report to the operator; `notes` below is the client's own
    # free-text note from the agent card. They used to share one name, which made the first
    # append() after the agent card was read explode on a str.
    engine_notes: list[str] = []
    if source != "offline" and not llm.web_search_supported():
        engine_notes.append(
            "Live web search is not available on this engine (" + (engine.get("host") or "unknown")
            + "), so listing facts come from the details supplied and the model's own knowledge, "
            "not from the public listing pages."
        )
    card = _agent_card(boost, openings)

    address = getattr(boost, "address", "") or ""
    agent = _first(card.get("agent_name"), "")
    phone = _first(card.get("phone"), "")
    license_ = _first(card.get("license"), "")
    brokerage = _first(card.get("brokerage"), "")
    instagram = _first(card.get("instagram"), "")
    website = _first(card.get("website"), "")
    property_website = _first(card.get("property_website"), "")
    facts = _first(card.get("facts"), "")
    notes = _first(card.get("notes"), "")
    video_transcript = _first(card.get("video_transcript"), "")
    services = _first(card.get("services"), "")
    video_library = _first(card.get("video_library"), "")
    page_head = _first(card.get("page_head"), "")
    page_text = _first(card.get("page_text"), "")
    property_page_text = _first(card.get("property_page_text"), "")
    brand_kit = _first(card.get("brand_kit"), "none")

    days = _clamp_days(getattr(boost, "campaign_days", None))
    per_day = _clamp_per_day(_first(card.get("per_day"), 1))
    total_posts = days * per_day

    # --- PHOTO INDEX from the boost's assets --------------------------------
    assets = (db.query(Asset).filter(Asset.boost_id == boost.id).all()
              if db is not None else [])
    photos = [a for a in assets if getattr(a, "kind", "photo") == "photo"]
    photo_index = build_photo_index(assets)
    no_photos = len(photos) == 0

    # --- R1: property research (Responses API, web search) ------------------
    r1_input = prompts.R1_PROPERTY_RESEARCH.format(address=address)
    research = await llm.responses_text(
        r1_input,
        model=settings.OPENAI_MODEL_RESEARCH,
        reasoning_effort="low",
        tools=[{"type": "web_search"}],
    )
    research = _trunc(research, 7000)

    # --- R2: the agent's brand (Chat Completions -> JSON) -------------------
    website_provided = f"yes - {website}" if website else "no"
    r2_user = prompts.R2_BRAND_USER.format(
        agent=agent,
        address=address,
        website_provided=website_provided,
        page_head=_trunc(page_head, 3000),
        page_text=_trunc(page_text, 6000),
        brand_kit=brand_kit or "none",
    )
    brand = await llm.chat_json(
        prompts.R2_BRAND_SYSTEM,
        r2_user,
        model=settings.OPENAI_MODEL_BRAND,
        max_completion_tokens=4000,
        reasoning_effort="low",
    )
    brand_json = brand if isinstance(brand, str) else json.dumps(brand)

    # --- R3: style recipe (Responses API, web search) -----------------------
    r3_input = prompts.R3_STYLE_RECIPE.format(
        agent=agent,
        website=website or "none",
        instagram=instagram or "not given",
        brokerage=brokerage or "not given",
        brand_json=_trunc(brand_json, 3000),
        brand_kit=brand_kit or "none",
        phone=phone or "NOT GIVEN",
        license=license_ or "NOT GIVEN",
    )
    style = await llm.responses_text(
        r3_input,
        model=settings.OPENAI_MODEL_RESEARCH,
        reasoning_effort="medium",
        tools=[{"type": "web_search"}],
    )
    style = _trunc(style, 5000)

    # --- R4: the campaign plan (Chat Completions -> JSON) -------------------
    r4_user = prompts.R4_PLAN_USER.format(
        agent=agent,
        address=address,
        go_live=_first(getattr(boost, "go_live_date", None), "not set yet"),
        services=services,
        days=days,
        per_day=per_day,
        total_posts=total_posts,
        notes=notes,
        video_library=video_library or "empty",
        brand_json=brand_json,
        style=style,
        phone=phone or "NOT GIVEN",
        photo_index=_trunc(photo_index, 110000),
        license=license_ or "NOT GIVEN",
        brokerage=brokerage or "NOT GIVEN",
        instagram=instagram or "not given",
        facts=facts or "none provided",
        ai_notes=notes or "none",
        video_transcript=_trunc(video_transcript, 12000) or "none",
        research=research,
        property_page_url=property_website,
        property_page_text=_trunc(property_page_text, 4000),
    )
    plan = await llm.chat_json(
        prompts.R4_PLAN_SYSTEM,
        r4_user,
        model=settings.OPENAI_MODEL_PLAN,
        max_completion_tokens=40000,
        reasoning_effort="medium",
    )

    # --- repair the rules models drift on, then validate --------------------
    plan, repairs = _repair_video_mix(plan, days, per_day)
    # Make the closing contact line real and on its own line BEFORE the rules are checked, so the
    # violation list describes the campaign the client will actually see.
    closing_line = llm._closing_line(agent or "MISSING", phone, license_, brokerage)
    closing_fixed = _normalise_closing_lines(plan, closing_line)
    if closing_fixed:
        engine_notes.append(
            f"{closing_fixed} caption(s) did not end with the required contact line; the engine"
            " wrote it from the agent card (a value that was not given prints MISSING)."
        )
    inline_fixed = _split_inline_closing(plan, agent=agent)
    violations = validate_plan(plan, days, per_day)
    if inline_fixed:
        engine_notes.append(
            f"{inline_fixed} caption(s) had the closing contact line on the same line as the copy;"
            " the engine moved it onto its own line."
        )

    # --- persist ------------------------------------------------------------
    missing_info = list(plan.get("missingInfo") or []) if isinstance(plan, dict) else []
    missing_info = _scrub_stale_video_notes(missing_info, plan)
    # Report a repair in plain words; the technical form stays in the API's "repairs".
    for note in repairs:
        m = re.match(r"video mix: (\d+)/(\d+) video posts repaired to (\d+)/(\d+)", note)
        if m:
            missing_info.append(
                f"Video mix adjusted from {m.group(1)} to {m.group(3)} video posts of "
                f"{m.group(4)} so the campaign keeps the spec's one-third video rhythm."
            )
        else:
            missing_info.append(note)
    if no_photos:
        missing_info.append(
            "No uploaded photos: the PHOTO INDEX sent to the planner was empty, so "
            "static posts cannot name a real listing photo."
        )
    if not getattr(boost, "go_live_date", None):
        missing_info.append(
            "No go-live date on the boost: publish times were computed from today."
        )
    missing_info = list(dict.fromkeys(m for m in missing_info if m))

    boost.brand_profile = brand
    boost.plan = plan
    boost.main_status = "Team Review"

    url_by_file = _asset_url_map(assets)

    base_date = date.today()
    if getattr(boost, "go_live_date", None):
        try:
            base_date = date.fromisoformat(str(boost.go_live_date)[:10])
        except ValueError:
            base_date = date.today()

    plan_posts = plan.get("posts") if isinstance(plan, dict) else []
    plan_posts = plan_posts if isinstance(plan_posts, list) else []
    if not plan_posts and source != "offline":
        # The engine answered but produced no calendar. Fail before anything is staged in the
        # session, so the client sees why instead of a campaign holding zero posts.
        raise llm.LLMError(
            "the content engine returned a plan with no posts; the model may have ignored the "
            "plan format - retry the build, or point RESMARA_ENGINE_* at a stronger model"
        )

    # delete-or-update posts for this boost
    if force and db is not None:
        db.query(Post).filter(Post.boost_id == boost.id).delete()
        existing: dict = {}
    else:
        existing = ({(p.day, p.slot): p for p in
                     db.query(Post).filter(Post.boost_id == boost.id).all()}
                    if db is not None else {})

    posts_created = 0
    for p in plan_posts:
        if not isinstance(p, dict):
            continue
        day = _as_int(p.get("day")) or 1
        slot = _as_int(p.get("slot")) or 1
        kind = p.get("kind") or "static"
        caption = p.get("caption") or ""
        hashtags = p.get("hashtags") or []
        hashtags_str = " ".join(
            (h if str(h).startswith("#") else "#" + str(h)) for h in hashtags
        )

        post = existing.get((day, slot))
        if post is None:
            post = Post(boost_id=boost.id, day=day, slot=slot)
            db.add(post)

        post.kind = kind
        post.caption = caption + (("\n\n" + hashtags_str) if hashtags_str else "")
        post.hashtags = hashtags_str
        post.cta = p.get("cta")
        post.image_url = url_by_file.get(p.get("photoFile"), "") or ""
        target_date = base_date + timedelta(days=day - 1)
        slot_time = time(9, 0) if slot == 1 else time(19, 0)
        post.publish_at = datetime.combine(target_date, slot_time).isoformat()
        post.publish_target = ("instagram" if kind == "short_video"
                               else "both")
        post.publish_status = "scheduled"
        post.client_status = "pending"
        posts_created += 1

    # --- one Ad row from plan['ad'] -----------------------------------------
    ad_plan = plan.get("ad") if isinstance(plan, dict) else {}
    ad_plan = ad_plan if isinstance(ad_plan, dict) else {}
    creative_days = ad_plan.get("creativeDays") or []
    kinds_by_day = {}
    for p in plan_posts:
        if isinstance(p, dict):
            day_key = _as_int(p.get("day"))
            if day_key is not None:
                kinds_by_day.setdefault(day_key, []).append(p.get("kind"))
    ad_kind = "photo"
    for d in creative_days:
        day_num = _as_int(d)
        if day_num is None:
            # A small model sometimes answers a seed here with a range or a list ("days 8-14");
            # an unhashable key used to raise TypeError and surface as a 502 on the client.
            continue
        if any(k in ("main_video", "short_video") for k in kinds_by_day.get(day_num, [])):
            ad_kind = "video"
            break

    ads = (db.query(Ad).filter(Ad.boost_id == boost.id).all()
           if db is not None else [])
    if force and ads:
        for a in ads:
            db.delete(a)
        ads = []
    ad = ads[0] if ads else (Ad(boost_id=boost.id, kind=ad_kind) if db is not None else None)
    if ad is not None:
        ad.kind = ad_kind
        ad.primary_text = ad_plan.get("primaryText")
        ad.headline = ad_plan.get("headline")
        ad.description = ad_plan.get("description")
        ad.cta_button = ad_plan.get("ctaButton") or "Learn more"
        db.add(ad)

    if db is not None:
        db.commit()
        try:
            db.refresh(boost)
        except Exception:
            pass
        ad_id = ad.id if ad is not None else None
    else:
        ad_id = None

    return {
        "source": source,
        "engine": engine,
        "notes": engine_notes,
        "brand": brand,
        "style": style,
        "plan": plan,
        "violations": violations,
        "repairs": repairs,
        "missing_info": missing_info,
        "posts_created": posts_created,
        "ad_id": ad_id,
        "model": {
            "research": settings.OPENAI_MODEL_RESEARCH,
            "brand": settings.OPENAI_MODEL_BRAND,
            "style": settings.OPENAI_MODEL_RESEARCH,
            "plan": settings.OPENAI_MODEL_PLAN,
        },
    }
