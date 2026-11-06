"""OpenAI client for the Resmara content engine.

Two call shapes, matching handoff doc 10 section 4 exactly:

  * chat_json(...)      -> POST {OPENAI_BASE}/chat/completions with
                           response_format {"type": "json_object"}, returns the
                           parsed JSON object. Raises LLMError on any failure.
  * responses_text(...) -> POST {OPENAI_BASE}/responses (the Responses API), returns
                           the first `message` item's first content[].text.

Base URL: OPENAI_BASE_URL env var, default https://api.openai.com/v1. It is read at
call time (not via settings) so tests can point it at a local mock server without
touching app/core/config.py.

Offline mode
------------
When llm_available() is False (settings.SIMULATE is on, or there is no
OPENAI_API_KEY) every function returns a DETERMINISTIC offline fixture instead of
making a network call. The fixtures are shaped exactly like the real outputs (a
valid brand object, a valid campaign plan of days*per_day posts, a photo-tag line,
...) so the whole pipeline can run and be tested with no network. Callers must
surface source == "offline"; nothing here ever pretends the result was real AI.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from app.core.config import settings

log = logging.getLogger("resmara.llm")

DEFAULT_BASE = "https://api.openai.com/v1"

# The engine can run against ANY OpenAI-compatible endpoint, not just OpenAI:
# RESMARA_ENGINE_BASE_URL / RESMARA_ENGINE_API_KEY win over OPENAI_BASE_URL /
# OPENAI_API_KEY. Switching provider (paid OpenAI <-> a free local model) is therefore an
# .env edit, not a code change. Two things differ on a non-OpenAI endpoint and both are
# handled below: there is no /responses endpoint, and there is no web_search tool.
ENGINE_BASE_ENV = "RESMARA_ENGINE_BASE_URL"
ENGINE_KEY_ENV = "RESMARA_ENGINE_API_KEY"
ENGINE_NUM_CTX_ENV = "RESMARA_ENGINE_NUM_CTX"
DEFAULT_LOCAL_NUM_CTX = 32768


class LLMError(Exception):
    """Any OpenAI-compatible call failure (transport, HTTP status, unparseable body)."""


# ---------------------------------------------------------------------------
# Availability + base URL
# ---------------------------------------------------------------------------
def engine_base() -> str:
    """Base URL of the engine. RESMARA_ENGINE_BASE_URL, else OPENAI_BASE_URL, else OpenAI."""
    return (os.getenv(ENGINE_BASE_ENV) or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE).rstrip("/")


def openai_base() -> str:
    """Kept for older callers/tests: the engine base URL."""
    return engine_base()


def engine_key() -> str:
    """Key for the engine. RESMARA_ENGINE_API_KEY, else the OpenAI key."""
    return os.getenv(ENGINE_KEY_ENV) or getattr(settings, "OPENAI_API_KEY", "") or ""


# How long a single model call may take. A free local model grinds through a 14-day plan
# far slower than a hosted one, and the old flat 180s turned a slow-but-working build into
# an opaque "request failed" 502.
ENGINE_TIMEOUT_ENV = "RESMARA_ENGINE_TIMEOUT"
DEFAULT_LOCAL_TIMEOUT = 900.0
DEFAULT_HOSTED_TIMEOUT = 180.0

# Output cap for a non-OpenAI endpoint: a small model left uncapped will ramble for
# thousands of tokens, which reads as a hang. 0 disables the cap.
ENGINE_MAX_TOKENS_ENV = "RESMARA_ENGINE_MAX_TOKENS"
ENGINE_REASONING_ENV = "RESMARA_ENGINE_REASONING"
DEFAULT_LOCAL_MAX_TOKENS = 8192
# A hosted reasoning model on a compatible endpoint spends the budget on its trace before it
# writes a single character of `content`. Measured on ollama.com 2026-11-06: the 14-day plan
# (asked for 40k) came back with content="" and finish_reason="length" at an 8k cap, while the
# same call returned the full plan at 32k. Small models keep the old, cheap cap.
DEFAULT_COMPAT_MAX_TOKENS = 32000


def default_timeout() -> float:
    try:
        configured = float(os.getenv(ENGINE_TIMEOUT_ENV) or 0)
    except ValueError:
        configured = 0
    if configured > 0:
        return configured
    return DEFAULT_LOCAL_TIMEOUT if is_local_base() else DEFAULT_HOSTED_TIMEOUT


def _host(base: str) -> str:
    match = re.match(r"^[a-z]+://([^/]+)", base or "")
    return (match.group(1) if match else "").lower()


def is_local_base() -> bool:
    """True for an endpoint on this machine (a local model needs no key and wants num_ctx)."""
    host = _host(engine_base())
    return host.startswith(("127.0.0.1", "localhost", "0.0.0.0", "[::1]"))


def is_openai_native() -> bool:
    return _host(engine_base()).endswith("api.openai.com")


def web_search_supported() -> bool:
    """Only OpenAI's own Responses API searches the web for us. Never claim it elsewhere."""
    return is_openai_native()


def engine_info() -> dict:
    """What is actually answering, for /api/status and the build response."""
    return {
        "base": engine_base(),
        "host": _host(engine_base()),
        "provider": "openai" if is_openai_native() else "openai-compatible",
        "local": is_local_base(),
        "web_search": web_search_supported(),
    }


def llm_available() -> bool:
    """True when a real call can be made: not simulating, and either a key or a local endpoint."""
    if bool(getattr(settings, "SIMULATE", False)):
        return False
    return bool(engine_key()) or is_local_base()


# ---------------------------------------------------------------------------
# Low-level transport
# ---------------------------------------------------------------------------
def _for_provider(payload: dict) -> dict:
    """Translate the OpenAI-specific fields for a non-OpenAI endpoint.

    A compatible server usually rejects (or ignores) `max_completion_tokens`,
    `reasoning_effort` and `response_format`, and a local model needs the context window
    raised or a long calendar prompt is silently truncated to a few thousand tokens.
    """
    sent = dict(payload)
    if is_openai_native():
        return sent
    if "max_completion_tokens" in sent:
        sent.setdefault("max_tokens", sent.pop("max_completion_tokens"))
    asked_for_thinking = bool(sent.pop("reasoning_effort", None) or sent.pop("reasoning", None))
    if is_local_base() and not asked_for_thinking:
        # Ollama treats reasoning_effort "none" as "do not think". A reasoning model otherwise
        # spends its whole output budget in the trace and hands back an empty `content` (the
        # vision tag step then reported zero tags on a perfectly good photo). Measured on
        # gemma4:e4b-mlx 2026-11-04: "none" -> the answer, no trace; "think": false on the
        # OpenAI-compatible route is ignored.
        sent["reasoning_effort"] = "none"
    # Same trap on a hosted compatible endpoint: glm-5.3 burned its entire 32k budget on trace
    # and returned content="" with finish_reason="length" (60k made no difference). Turning the
    # trace off is not the answer either — with reasoning_effort "none" it answered in 122k
    # characters of prose instead of JSON. Pick a model that answers before it thinks:
    # deepseek-v4.1-flash returns the 14-day plan in one stop (measured 2026-11-06).
    reasoning = os.getenv(ENGINE_REASONING_ENV)
    if reasoning and not is_openai_native():
        sent["reasoning_effort"] = reasoning
    if is_local_base():
        num_ctx = int(os.getenv(ENGINE_NUM_CTX_ENV) or DEFAULT_LOCAL_NUM_CTX)
        sent["options"] = {**(sent.get("options") or {}), "num_ctx": num_ctx}
    try:
        cap = int(os.getenv(ENGINE_MAX_TOKENS_ENV) or 0) or (
            DEFAULT_LOCAL_MAX_TOKENS if is_local_base() else DEFAULT_COMPAT_MAX_TOKENS
        )
    except ValueError:
        cap = DEFAULT_COMPAT_MAX_TOKENS
    if cap > 0:
        for key in ("max_tokens", "max_completion_tokens"):
            if isinstance(sent.get(key), int) and sent[key] > cap:
                sent[key] = cap
    return sent


def _without_optional_extras(payload: dict) -> dict:
    """Second attempt for a server that refused our optional fields."""
    sent = dict(payload)
    for key in ("response_format", "options"):
        sent.pop(key, None)
    return sent


async def _post(path: str, payload: dict, *, timeout: float | None = None) -> dict:
    timeout = timeout or default_timeout()
    url = engine_base() + path
    headers = {"Content-Type": "application/json"}
    key = engine_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    sent = _for_provider(payload)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=sent, headers=headers)
            if resp.status_code in (400, 404, 422):
                # Optional OpenAI-only fields are the usual cause; ask once more without them.
                relaxed = _without_optional_extras(sent)
                if relaxed != sent:
                    retry = await client.post(url, json=relaxed, headers=headers)
                    if retry.status_code < 400:
                        return retry.json()
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:  # pragma: no cover - network path
        body = exc.response.text[:500] if exc.response is not None else ""
        raise LLMError(f"HTTP {exc.response.status_code} from {url}: {body}") from exc
    except Exception as exc:  # pragma: no cover - network path
        raise LLMError(
            f"request to {url} failed after {timeout:.0f}s: {type(exc).__name__}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Chat Completions -> JSON object
# ---------------------------------------------------------------------------
async def chat_json(
    system: str,
    user: str,
    *,
    model: str,
    max_completion_tokens: int = 4000,
    reasoning_effort: str | None = None,
) -> dict:
    """Chat Completions call forced to a JSON object. Raises LLMError on failure."""
    if not llm_available():
        return _offline_chat_fixture(system, user)

    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_completion_tokens": max_completion_tokens,
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    data = await _post("/chat/completions", payload)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"chat_json: unexpected response shape: {str(data)[:300]}") from exc
    parsed = _json_object(content)
    if parsed is None:
        # A small free model sometimes answers with prose first, or stops mid-object when it hits
        # its output cap. Retry once with an explicit format demand (cheap) before failing the
        # step, and keep the error short - the raw reply used to be dumped into the UI verbatim.
        retry = dict(payload)
        retry["temperature"] = 0
        retry["messages"] = [
            {
                "role": "system",
                "content": system
                + "\n\nReturn ONE valid JSON object and nothing else: no markdown fences, no"
                " commentary, no text before or after it. Close every brace and quote.",
            },
            {"role": "user", "content": user},
        ]
        try:
            data = await _post("/chat/completions", retry)
            second = data["choices"][0]["message"]["content"]
        except (LLMError, KeyError, IndexError, TypeError):
            second = ""
        parsed = _json_object(second)
        if parsed is None:
            seen = (second or str(content) or "").strip().replace("\n", " ")[:180]
            raise LLMError(
                f"chat_json: the model did not return valid JSON after a retry (model={model})."
                f" It answered: {seen!r}"
            )
    return parsed


def _json_object(text) -> dict | None:
    """Parse a JSON object out of a model reply.

    Small free models wrap JSON in ```json fences or add a sentence before it, so strip
    fences and, if that fails, take the outermost {...} span before giving up.
    """
    if not isinstance(text, str):
        return text if isinstance(text, dict) else None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
    for candidate in (cleaned,):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(cleaned[start:end + 1])
        except ValueError:
            return None
        if isinstance(value, dict):
            return value
    return None


# ---------------------------------------------------------------------------
# Responses API -> plain text
# ---------------------------------------------------------------------------
async def _chat_completion_text(prompt: str, *, model: str, timeout: float = 240.0) -> str:
    """One-shot chat/completions call returning the text (no web search, no tools)."""
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    data = await _post("/chat/completions", payload, timeout=timeout)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"chat: unexpected response shape: {str(data)[:300]}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("chat: model returned an empty reply")
    return content


async def responses_text(
    input_text: str,
    *,
    model: str,
    reasoning_effort: str = "low",
    tools: list | None = None,
) -> str:
    """Responses API call. Returns the first message item's first content[].text."""
    if not llm_available():
        return _offline_text_fixture(input_text, model=model)

    if not is_openai_native():
        # A compatible endpoint has no /responses and no web_search. Run the same prompt
        # through chat/completions and say so once in the log: the caller must not report
        # "researched the public listing" when no search happened.
        if tools:
            log.warning(
                "web_search requested but %s has no search tool - answering from model "
                "knowledge only (no live listing research)", engine_info()["host"],
            )
        text = await _chat_completion_text(input_text, model=model, timeout=240.0)
        return text

    payload: dict = {"model": model, "input": input_text}
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if tools:
        payload["tools"] = tools

    data = await _post("/responses", payload)

    # The handoff doc: "the scenario takes the first `message` item's first
    # `content[].text`". Walk the output array for the first message item.
    output = data.get("output") if isinstance(data, dict) else None
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for chunk in item.get("content", []) or []:
                if isinstance(chunk, dict) and chunk.get("text"):
                    return chunk["text"]
    # Convenience field some Responses responses carry.
    if isinstance(data, dict) and data.get("output_text"):
        return data["output_text"]
    raise LLMError(f"responses_text: no message text in response: {str(data)[:300]}")


# ---------------------------------------------------------------------------
# Generic chat completion -> plain text (used by image tagging)
# ---------------------------------------------------------------------------
async def chat_text(
    system: str,
    user: str,
    *,
    model: str,
    images: list | None = None,
    max_completion_tokens: int = 400,
    reasoning_effort: str | None = None,
) -> str:
    """Chat Completions call returning the message content as plain text.

    `images` is a list of image URLs attached to the user message as
    {"type":"image_url",...} content parts (so a vision model can see the photo).
    """
    if not llm_available():
        return _offline_tag_line(user, images=images)

    if images:
        user_content: list = [{"type": "text", "text": user}]
        for url in images:
            user_content.append({"type": "image_url", "image_url": {"url": url}})
        user_msg = {"role": "user", "content": user_content}
    else:
        user_msg = {"role": "user", "content": user}

    payload: dict = {
        "model": model,
        "messages": [{"role": "system", "content": system}, user_msg],
        "max_completion_tokens": max_completion_tokens,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    data = await _post("/chat/completions", payload)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"chat_text: unexpected response shape: {str(data)[:300]}") from exc


# ===========================================================================
# Deterministic offline fixtures
# ===========================================================================
_BANNED = ("stunning", "boasts", "nestled", "charming", "dream", "gem", "oasis",
           "perfect", "must-see", "welcome home", "immaculate", "turn-key")

_CAPTION_BODIES = (
    "Morning light moves across this room and it is the best part of the day, "
    "coffee in hand and nowhere to be. By evening the whole place fills with "
    "friends and nobody wants to leave. It is the kind of spot that quietly "
    "becomes the heart of the home and stays that way.",
    "There is a rhythm to the days here that is hard to explain and easy to feel. "
    "Slow mornings, long afternoons, and evenings that stretch out on the porch. "
    "This is the corner of the house where the whole family ends up, and where "
    "the good conversations happen without anyone planning them.",
    "You will know this room the moment you walk in. It is where the first coffee "
    "of the day gets made, where homework and dinner and late talks all land, and "
    "where the seasons show up through the windows. It holds the ordinary days "
    "better than almost anywhere else in the home.",
)

_OVERLAYS = ("Where summer actually happens", "The coffee corner",
             "Everyone ends up out here", "Still the best room in the house",
             "A quiet start to the day", "Room to spread out")

_KICKERS = ("THE ARRIVAL", "WHERE THE DAY STARTS", "THE TOUR", "15 SECONDS THE KITCHEN",
            "THE HEART OF THE HOME", "THE EVENING ROOM")

_CTAS = ("Message me for a private showing.", "Call or text me anytime.",
         "Ask me for a walk-through.", "Drop a question below.",
         "Send me a note and I will show you round.")

_HASHTAGS = (
    ["#realestate", "#justlisted", "#homesweethome"],
    ["#realestate", "#listing", "#tour", "#newhome"],
    ["#realestate", "#dreamhome", "#forsale"],
    ["#realestate", "#justlisted", "#openhouse", "#home"],
)

_TAG_ROOMS = ("front exterior", "kitchen", "living room", "primary bedroom",
              "dining room", "backyard", "aerial", "office")


def _first_line_value(text: str, label: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(label):
            return line[len(label):].strip()
    return ""


def _caption(context: str, index: int) -> str:
    body = _CAPTION_BODIES[index % len(_CAPTION_BODIES)]
    return f"{body}\n{context}"


def _closing_line(agent: str, phone: str, license: str, brokerage: str) -> str:
    name = (agent or "").strip() or "AGENT NAME"
    ph = (phone or "").strip()
    lic = (license or "").strip()
    brok = (brokerage or "").strip()
    ph = "MISSING" if ph.upper() in ("", "NOT GIVEN") else ph
    lic = "MISSING" if lic.upper() in ("", "NOT GIVEN") else lic
    brok = "MISSING" if brok.upper() in ("", "NOT GIVEN") else brok
    return f"{name} | {ph} | LIC {lic} | {brok} | Equal Housing Opportunity"


def _video_count(total: int) -> int:
    """Roughly a third, never more than two fifths (doc 10 R4 RHYTHM hard rule)."""
    if total <= 0:
        return 0
    low = -(-total // 3)      # ceil(total/3)
    return low


def _video_positions(total: int, vcount: int) -> list:
    if vcount <= 0 or total <= 0:
        return []
    step = total / vcount
    pos: list = []
    for i in range(vcount):
        p = int(round(i * step))
        if pos and p <= pos[-1] + 1:
            p = pos[-1] + 2
        pos.append(p)
    if pos[-1] > total - 1:  # degenerate; spread from the start
        pos = [min(p, total - 1) for p in range(0, 2 * vcount, 2)][:vcount]
    return pos


def _static_types(n: int) -> list:
    """postType per static, capping question at 3 and never doubling up connect."""
    types, q, prev_connect = [], 0, False
    cycle = ["photo", "connect", "photo", "question", "photo", "carousel"]
    for i in range(n):
        t = cycle[i % len(cycle)]
        if t == "question":
            if q >= 3:
                t = "photo"
            else:
                q += 1
        if t == "connect" and prev_connect:
            t = "photo"
        types.append(t)
        prev_connect = (t == "connect")
    return types


def offline_plan_fixture(
    days: int = 14,
    per_day: int = 1,
    *,
    address: str = "",
    agent: str = "",
    phone: str = "",
    license: str = "",
    brokerage: str = "",
    photo_files: list | None = None,
    video_file_ids: list | None = None,
) -> dict:
    """A deterministic, rule-compliant plan with exactly days*per_day posts."""
    days = max(1, int(days or 14))
    per_day = 2 if int(per_day or 1) >= 2 else 1
    total = days * per_day
    photo_files = [p for p in (photo_files or []) if p]
    video_file_ids = [v for v in (video_file_ids or []) if v]

    vcount = _video_count(total)
    vpositions = set(_video_positions(total, vcount))

    closing = _closing_line(agent, phone, license, brokerage)
    missing = []
    if (phone or "").strip().upper() in ("", "NOT GIVEN"):
        missing.append("AGENT PHONE: MISSING (not given) - closing line prints MISSING.")
    if (license or "").strip().upper() in ("", "NOT GIVEN"):
        missing.append("AGENT LICENSE NUMBER: MISSING (not given) - closing line prints MISSING.")
    if (brokerage or "").strip().upper() in ("", "NOT GIVEN"):
        missing.append("BROKERAGE: MISSING (not given) - closing line prints MISSING.")

    static_types = _static_types(total - vcount)
    posts = []
    s_idx = 0
    v_idx = 0
    for i in range(total):
        day = i // per_day + 1
        slot = (i % per_day) + 1
        if i in vpositions:
            kind = "main_video" if v_idx == 0 else "short_video"
            vid = video_file_ids[v_idx % len(video_file_ids)] if video_file_ids else ""
            v_idx += 1
            posts.append({
                "day": day, "slot": slot, "kind": kind, "videoFileId": vid,
                "postType": "", "photoFiles": [], "title": f"Video {i + 1}",
                "kicker": "THE TOUR" if kind == "main_video" else _KICKERS[i % len(_KICKERS)],
                "overlayText": "", "photoFile": "", "photoRoom": "",
                "caption": _caption(closing, i), "hashtags": list(_HASHTAGS[i % len(_HASHTAGS)]),
                "cta": _CTAS[i % len(_CTAS)],
                "notes": "Video post; contact line is on the end card too.",
            })
        else:
            ptype = static_types[s_idx % len(static_types)] if static_types else "photo"
            photo = photo_files[s_idx % len(photo_files)] if photo_files else "NEEDS PHOTO"
            posts.append({
                "day": day, "slot": slot, "kind": "static", "videoFileId": "",
                "postType": ptype, "photoFiles": [], "title": f"Post {i + 1}",
                "kicker": _KICKERS[i % len(_KICKERS)],
                "overlayText": _OVERLAYS[i % len(_OVERLAYS)], "photoFile": photo,
                "photoRoom": "", "caption": _caption(closing, i),
                "hashtags": list(_HASHTAGS[i % len(_HASHTAGS)]), "cta": _CTAS[i % len(_CTAS)],
                "notes": "Static post; contact line carried by the caption.",
            })
            s_idx += 1

    creative_days = [p["day"] for p in posts if p["kind"] == "static"][:3]
    plan = {
        "summary": ("Offline fixture plan for " + (address or "the listing")
                    + ". No AI was called; RESMARA is simulating."),
        "propertyStory": {
            "thesis": "A warm, lived-in home told one room at a time.",
            "differentiators": ["Fixture one", "Fixture two", "Fixture three",
                                "Fixture four", "Fixture five"],
            "angles": ["Story of the day", "The arrival", "Where the day ends"],
        },
        "storyArc": "One walk through the home, front door to the back fence.",
        "posts": posts,
        "ad": {
            "name": (address or "Listing") + " Boost",
            "objective": "Traffic",
            "specialAdCategory": "HOUSING",
            "totalBudgetUsd": 50,
            "durationDays": days,
            "locationRule": "15 mile radius around the listing",
            "audienceNotes": "No age, gender or ZIP targeting.",
            "placements": "Facebook and Instagram feeds.",
            "primaryText": "Offline fixture ad copy, written like a short story hook.",
            "headline": "See the full story",
            "description": "A home told in order",
            "ctaButton": "Learn more",
            "creativeDays": creative_days,
        },
        "needsVerification": [],
        "missingInfo": missing,
        "complianceFlags": [],
        "requiredOverlayLines": [closing],
    }
    return plan


def offline_brand_fixture(*, agent_name: str = "", website_provided: bool = False) -> dict:
    return {
        "agentName": agent_name or "",
        "brokerage": "",
        "license": "",
        "phone": "",
        "tagline": "",
        "tone": ["warm", "plain", "personal"],
        "colors": [],
        "fonts": [],
        "logoUrl": "",
        "bio": "Offline fixture brand profile (no website was scraped).",
        "serviceAreas": [],
        "websiteProvided": bool(website_provided),
        "brandConfidence": "low",
        "notes": "Offline fixture: RESMARA_SIMULATE is on or OPENAI_API_KEY is empty.",
    }


def _offline_chat_fixture(system: str, user: str) -> dict:
    """Pick the right offline fixture by inspecting the SYSTEM prompt text.

    Classify on the system message only: the R4 user message embeds the R2 brand
    JSON (which itself contains "brandConfidence"), so a whole-blob keyword test
    would confuse the two calls.
    """
    sys_text = system or ""
    if "campaign strategist" in sys_text or "propertyStory" in sys_text:
        days = 14
        per_day = 1
        m = re.search(r"CAMPAIGN DAYS:\s*(\d+)", user or "")
        if m:
            days = int(m.group(1))
        m = re.search(r"POSTS PER DAY:\s*(\d+)", user or "")
        if m:
            per_day = int(m.group(1))
        phone = _first_line_value(user, "AGENT PHONE:")
        license = _first_line_value(user, "AGENT LICENSE NUMBER:")
        brokerage = _first_line_value(user, "BROKERAGE:")
        agent = _first_line_value(user, "AGENT:")
        address = _first_line_value(user, "ADDRESS:")
        m = re.search(r"PHOTO INDEX \([^)]*\):[ \t]*(.*)", user or "")
        idx = m.group(1) if m else ""
        photo_files = [e.split("|")[0].strip() for e in idx.split(" ;; ") if e.strip()]
        m = re.search(r"VIDEO LIBRARY \([^)]*\):[ \t]*(.*)", user or "")
        vlib = m.group(1) if m else ""
        video_ids = [e.split("|")[0].strip() for e in vlib.split(" ;; ")
                     if e.strip() and e.strip().lower() != "empty"]
        return offline_plan_fixture(
            days, per_day, address=address, agent=agent, phone=phone,
            license=license, brokerage=brokerage, photo_files=photo_files,
            video_file_ids=video_ids,
        )
    if "brand analyst" in sys_text or "brandConfidence" in sys_text:
        agent = _first_line_value(user, "AGENT NAME ON THE TICKET:")
        provided = _first_line_value(user, "WEBSITE PROVIDED:").lower().startswith("yes")
        return offline_brand_fixture(agent_name=agent, website_provided=provided)
    return {"offline": True, "note": "no offline fixture defined for this prompt"}


def _offline_text_fixture(input_text: str, *, model: str = "") -> str:
    if "Research the property at" in (input_text or ""):
        m = re.search(r"Research the property at (.+?)\.", input_text)
        addr = m.group(1) if m else "the property"
        return (
            f"Offline fixture: web search is off (no OPENAI key / simulating), so no "
            f"public pages were read for {addr}.\n"
            "Bedrooms: NOT FOUND [offline]\n"
            "Bathrooms: NOT FOUND [offline]\n"
            "STORY CONTEXT\n"
            "Offline fixture: no story context was gathered."
        )
    if "art director" in (input_text or "") or "style recipe" in (input_text or ""):
        return (
            "AGENT BRAND: offline fixture, no brand found online.\n"
            "BROKERAGE: not seen [offline]\n"
            "TREND FINDINGS\n- offline\n- offline\n- offline\n- offline\n- offline\n- offline\n"
            "COMBINED RECIPE\nNeutral palette, one clean sans, headline lower-left, "
            "copy kept short, listing photo untouched, consistent footer.\n"
            "REQUIRED OVERLAY LINES\nnone found [offline]\n"
            "CONFLICTS\nnone\n"
            "BRAND MATCH CONFIDENCE\nlow\n"
            "NOT SEEN\nEverything: web search is disabled in offline mode."
        )
    return "Offline fixture: no text was generated for this prompt."


def _offline_tag_line(user: str, images: list | None = None) -> str:
    """Deterministic offline photo-tag line in the doc-14 one-line shape."""
    src = ""
    if images:
        src = str(images[0])
    name = src.rsplit("/", 1)[-1] or "photo"
    room = _TAG_ROOMS[sum(ord(c) for c in name) % len(_TAG_ROOMS)]
    social = 7 + (sum(ord(c) for c in name) % 3)  # 7..9, deterministic
    return (
        f"ROOM: {room} | SOCIAL: {social} | SHAPE: landscape | "
        "SEE: bright open space with wide windows | "
        "STORY: A tall window and warm floor boards give this space its easy character | "
        "POST: yes | WHY: ok | FEATURE: none | SCALE: none"
    )
