"""Post publisher for Resmara (handoff spec §11 "Social \u00b7 Publisher").

Publishes approved, due posts to the boost's Facebook Page and/or Instagram
business account.

Discipline this module enforces:
  * Only ``client_status == "approved"`` AND ``publish_status == "scheduled"``
    AND ``publish_at <= now`` posts, on a boost whose ad account is active.
  * CLAIM before publishing: re-check the post is still approved, flip
    ``publish_status`` to ``"posting"`` and COMMIT \u2014 before any network call.
    This is the idempotency / withdraw guard (spec §11 step 5.1): a post that
    was edited or withdrawn, or one left in ``"posting"`` by a crash, is never
    published by a later run.
  * Defaults to NOT spending money, and never publishes a post that is not
    currently approved.

Call shapes (spec §11 step 5.2):
  FB photo  POST /{page_id}/photos   multipart source=<file bytes>, message
  FB video  POST /{page_id}/videos   multipart source=<file bytes>, description
  FB text   POST /{page_id}/feed     message
  IG feed   POST /{ig_user_id}/media?image_url&caption  -> creation_id
            POST /{ig_user_id}/media_publish?creation_id

Instagram FETCHES the image itself (Graph has no direct upload for IG feed
posts), so the ``image_url`` handed to Instagram must be publicly reachable.
For a local ``/uploads/<file>`` path we build it from ``settings.PUBLIC_BASE_URL``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.db.session import AdAccount, Boost, Event, Post

log = logging.getLogger("resmara.publisher")

GRAPH_TIMEOUT = 60.0

# Verbatim wording from spec §11 step 3 (Instagram feed accepts one JPG only).
IG_JPG_MESSAGE = (
    "Instagram feed posts need one JPG picture. "
    "Replace the file with a JPG, then get it approved again."
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _token(ad_account: Any) -> str:
    return (getattr(ad_account, "access_token", None) or "").strip()


def _is_simulated(ad_account: Any) -> bool:
    """SIMULATE on, or no usable token \u2014 makes NO network call."""
    if settings.SIMULATE:
        return True
    token = _token(ad_account)
    if not token:
        return True
    low = token.lower()
    return low.startswith("sim") or low.startswith("demo")


def _url(path: str) -> str:
    return settings.graph_base.rstrip("/") + "/" + path.lstrip("/")


def _classify(post: Post) -> str:
    """'video' | 'text' | 'photo' for a post row."""
    kind = (getattr(post, "kind", "") or "").lower()
    if kind in ("video", "reel", "post_video"):
        return "video"
    if kind in ("text", "caption", "update"):
        return "text"
    return "photo" if post.image_url else "text"


def _message(post: Post) -> str:
    caption = post.caption or ""
    hashtags = post.hashtags or ""
    if hashtags:
        return f"{caption}\n\n{hashtags}".strip()
    return caption


def _ext(image_url: Optional[str]) -> str:
    if not image_url:
        return ""
    return os.path.splitext(image_url.split("?", 1)[0])[1].lower()


def ig_feed_supported(post: Post) -> bool:
    """Instagram feed accepts ONLY a single .jpg / .jpeg image (spec §11)."""
    return _ext(post.image_url) in (".jpg", ".jpeg")


def public_media_url(image_url: Optional[str]) -> Optional[str]:
    """Publicly reachable URL for an image, as Instagram must fetch it."""
    if not image_url:
        return None
    if image_url.startswith(("http://", "https://")):
        return image_url
    return settings.PUBLIC_BASE_URL.rstrip("/") + "/" + image_url.lstrip("/")


def local_media_path(image_url: Optional[str]) -> Optional[str]:
    """Absolute path under UPLOAD_DIR for a local ``/uploads/<file>`` URL.

    Rejects any path traversal (``../``): only the basename is ever used, and
    the resolved path must stay inside UPLOAD_DIR.
    """
    if not image_url:
        return None
    path = image_url.split("?", 1)[0].split("#", 1)[0]
    segments = path.split("/")
    if ".." in segments:
        raise ValueError(f"refusing unsafe media path: {image_url}")
    name = os.path.basename(path)
    if not name or name in (".", ".."):
        raise ValueError(f"no file name in media path: {image_url}")
    base = os.path.abspath(settings.UPLOAD_DIR)
    full = os.path.abspath(os.path.join(base, name))
    if os.path.commonpath([full, base]) != base:
        raise ValueError("media path escapes the upload directory")
    return full


# ---------------------------------------------------------------------------
# per-platform publish calls
# ---------------------------------------------------------------------------
async def _publish_facebook(client: httpx.AsyncClient, post: Post, kind: str,
                            page_id: str, message: str, token: str) -> Optional[str]:
    if not page_id:
        raise RuntimeError("No Facebook Page id configured for this account")

    if kind == "text":
        resp = await client.post(_url(f"/{page_id}/feed"),
                                 data={"message": message, "access_token": token})
        resp.raise_for_status()
        return (resp.json() or {}).get("id")

    path = local_media_path(post.image_url)
    if not path or not os.path.exists(path):
        raise RuntimeError(f"media file not found for post {post.id}: {post.image_url}")
    with open(path, "rb") as fh:
        content = fh.read()
    files = {"source": (os.path.basename(path), content)}
    if kind == "video":
        resp = await client.post(
            _url(f"/{page_id}/videos"),
            data={"description": message, "access_token": token}, files=files)
    else:
        resp = await client.post(
            _url(f"/{page_id}/photos"),
            data={"message": message, "access_token": token}, files=files)
    resp.raise_for_status()
    return (resp.json() or {}).get("id")


async def _publish_instagram(client: httpx.AsyncClient, post: Post, ig_id: str,
                             message: str, token: str) -> Optional[str]:
    if not ig_id:
        raise RuntimeError("No Instagram account id configured for this account")
    # Instagram FETCHES the image, so the URL must be publicly reachable.
    image_url = public_media_url(post.image_url)
    if not image_url:
        raise RuntimeError(f"no image for Instagram post {post.id}")

    # spec §11: POST /{ig-id}/media?image_url&caption  then  .../media_publish?creation_id
    resp = await client.post(_url(f"/{ig_id}/media"),
                             params={"image_url": image_url, "caption": message,
                                     "access_token": token})
    resp.raise_for_status()
    creation_id = (resp.json() or {}).get("id")
    if not creation_id:
        raise RuntimeError("Instagram did not return a creation id")

    resp2 = await client.post(_url(f"/{ig_id}/media_publish"),
                              params={"creation_id": creation_id, "access_token": token})
    resp2.raise_for_status()
    return (resp2.json() or {}).get("id")


# ---------------------------------------------------------------------------
# publish a single post
# ---------------------------------------------------------------------------
async def publish_post(post: Post, boost: Boost, ad_account: Any, db) -> Dict[str, Any]:
    """Publish one post to its target(s).

    Returns a dict with ``status`` in ``posted`` / ``failed``. ``simulated`` is
    True when no network call was made.
    """
    target = (post.publish_target or "both").lower()
    do_fb = target in ("facebook", "both")
    do_ig = target in ("instagram", "both")
    kind = _classify(post)
    message = _message(post)

    if ad_account is None:
        return {"status": "failed", "state": "failed",
                "error": "No Meta account connected for this boost"}

    # Supported-type check runs BEFORE any claim/network so a wrong file is
    # refused outright, never silently posted (spec §11 step 3).
    if do_ig:
        if kind == "video":
            return {"status": "failed", "state": "failed", "refused": True,
                    "error": "Instagram Reels are not published by this scheduler yet"}
        if not ig_feed_supported(post):
            return {"status": "failed", "state": "failed", "refused": True,
                    "error": IG_JPG_MESSAGE}

    # SIMULATED MODE: no network call at all. Defaults to NOT spending money.
    if _is_simulated(ad_account):
        return {
            "simulated": True,
            "status": "posted",
            "state": "posted",
            "fb_post_id": f"fb_sim_{post.id}" if do_fb else None,
            "ig_media_id": f"ig_sim_{post.id}" if do_ig else None,
        }

    token = _token(ad_account)
    page_id = (getattr(ad_account, "page_id", None) or settings.META_PAGE_ID or "").strip()
    ig_id = (getattr(ad_account, "ig_user_id", None) or settings.META_IG_ID or "").strip()

    fb_post_id: Optional[str] = None
    ig_media_id: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
            if do_fb:
                fb_post_id = await _publish_facebook(client, post, kind, page_id, message, token)
            if do_ig:
                ig_media_id = await _publish_instagram(client, post, ig_id, message, token)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "state": "failed", "error": str(exc),
                "fb_post_id": fb_post_id, "ig_media_id": ig_media_id}

    return {"simulated": False, "status": "posted", "state": "posted",
            "fb_post_id": fb_post_id, "ig_media_id": ig_media_id}


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------
def _due_posts(db, now: str, limit: int, boost_id: Optional[int] = None) -> List[Post]:
    """Approved + scheduled + due posts on a boost whose ad account is active.

    ``boost_id`` narrows it to one campaign (the operator's "publish now" button);
    the scheduler omits it and gets every due post.
    """
    q = (
        db.query(Post)
        .join(Boost, Post.boost_id == Boost.id)
        .join(AdAccount, Boost.ad_account_id == AdAccount.id)
        .filter(Post.client_status == "approved")
        .filter(Post.publish_status == "scheduled")
        .filter(Post.publish_at.isnot(None))
        .filter(Post.publish_at <= now)
        .filter(AdAccount.is_active == True)  # noqa: E712
    )
    if boost_id is not None:
        q = q.filter(Post.boost_id == boost_id)
    return q.limit(limit).all()


def claim_post(db, post_id: int) -> Optional[Post]:
    """Atomically claim a post for publishing.

    Returns the post with ``publish_status='posting'`` committed, or None when
    it is no longer approved + scheduled (withdrawn, edited, or already
    claimed). This is the guard the spec requires before any network call.
    """
    db.expire_all()  # read current committed state, not a stale identity-map copy
    fresh = db.query(Post).filter(Post.id == post_id).first()
    if (fresh is None
            or fresh.client_status != "approved"
            or fresh.publish_status != "scheduled"):
        return None
    fresh.publish_status = "posting"
    db.commit()
    return fresh


async def publish_due(db, now: Optional[str] = None, *, limit: int = 50,
                      boost_id: Optional[int] = None) -> Dict[str, Any]:
    """Publish every approved, due post. Safe to run repeatedly.

    ``boost_id`` limits the run to one campaign.
    """
    now = now or datetime.utcnow().isoformat()

    result: Dict[str, Any] = {"checked": 0, "posted": 0, "failed": 0, "skipped": 0,
                              "details": []}

    for post in _due_posts(db, now, limit, boost_id=boost_id):
        result["checked"] += 1

        # CLAIM first: flip to 'posting' and commit before touching the network.
        claimed = claim_post(db, post.id)
        if claimed is None:
            result["skipped"] += 1
            result["details"].append({"post_id": post.id, "status": "skipped",
                                      "reason": "not approved+scheduled at claim time"})
            continue

        boost = db.query(Boost).filter(Boost.id == claimed.boost_id).first()
        ad_account = None
        if boost is not None and boost.ad_account_id:
            ad_account = db.query(AdAccount).filter(AdAccount.id == boost.ad_account_id).first()

        try:
            published = await publish_post(claimed, boost, ad_account, db)
        except Exception as exc:  # noqa: BLE001 - a crash still marks the post
            published = {"status": "failed", "state": "failed", "error": str(exc)}

        if published.get("status") == "posted":
            claimed.publish_status = "posted"
            if published.get("fb_post_id"):
                claimed.fb_post_id = published["fb_post_id"]
            if published.get("ig_media_id"):
                claimed.ig_media_id = published["ig_media_id"]
            claimed.last_error = None
            # One event per published post: this is what the operator's activity graph
            # counts, and it records whether a real network call happened or not.
            db.add(Event(boost_id=claimed.boost_id, event_type="post_published",
                         payload={"post_id": claimed.id, "day": claimed.day,
                                  "target": claimed.publish_target,
                                  "simulated": bool(published.get("simulated"))}))
            db.commit()
            result["posted"] += 1
            result["details"].append({
                "post_id": claimed.id, "status": "posted",
                "simulated": bool(published.get("simulated")),
                "fb_post_id": claimed.fb_post_id,
                "ig_media_id": claimed.ig_media_id,
            })
        else:
            claimed.publish_status = published.get("state") or "failed"
            claimed.last_error = published.get("error")
            db.commit()
            result["failed"] += 1
            result["details"].append({"post_id": claimed.id,
                                      "status": claimed.publish_status,
                                      "error": claimed.last_error})

    return result
