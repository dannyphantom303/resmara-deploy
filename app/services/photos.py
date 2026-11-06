"""Bring real listing photos into a campaign.

The content engine can write captions from the property facts alone, but it cannot
invent the gallery: posts only get an image when the plan names a photo that exists as
an Asset. This module turns either a listing page (scraped for its gallery) or a list of
direct image URLs into Asset rows, so the PHOTO INDEX the engine reads is built from the
agent's real photos.

Extraction is a pure function (``extract_image_urls``) so it is testable without the
network; only ``discover`` and ``import_from_urls`` touch HTTP.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from urllib.parse import urljoin, urlparse

import httpx

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_BYTES = 12 * 1024 * 1024
DEFAULT_LIMIT = 10
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Chrome on a listing page is full of furniture: logos, sprites, agent headshots and
# tracking pixels all sit next to the photos. Drop the obvious ones by name.
_SKIP_HINTS = (
    "logo", "sprite", "favicon", "avatar", "headshot", "badge", "placeholder",
    "spacer", "pixel", "icon-", "/icons/", "1x1", "transparent", "loading",
)

_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_LD_RE = re.compile(r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _attrs(tag: str) -> dict:
    out = {}
    for m in _ATTR_RE.finditer(tag):
        name = m.group(1).lower()
        value = next((g for g in (m.group(2), m.group(3), m.group(4)) if g is not None), "")
        out[name] = value.strip()
    return out


def _srcset_best(srcset: str) -> str:
    """Largest candidate in a srcset ("a.jpg 1x, b.jpg 2x" / "a.jpg 640w, b.jpg 1280w")."""
    best, best_score = "", -1.0
    for part in (srcset or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        score = 1.0
        if len(bits) > 1:
            m = re.match(r"([0-9.]+)([wx])", bits[1])
            if m:
                score = float(m.group(1))
        if score > best_score:
            best, best_score = url, score
    return best


def _looks_like_image(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    path = urlparse(url).path.lower()
    if os.path.splitext(path)[1] in IMAGE_EXTS:
        return True
    # Many MLS/CDN galleries carry the format in the query string instead of the path.
    return bool(re.search(r"\.(jpe?g|png|webp)(?:$|[?&])", url.lower()))


def _is_furniture(url: str) -> bool:
    low = url.lower()
    return any(hint in low for hint in _SKIP_HINTS)


def _walk_json_images(node, out: list) -> None:
    if isinstance(node, str):
        return
    if isinstance(node, list):
        for item in node:
            _walk_json_images(item, out)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key.lower() in ("image", "images", "thumbnailurl", "contenturl") and value:
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict):
                        for k in ("url", "contentUrl", "@id"):
                            if isinstance(item.get(k), str):
                                out.append(item[k])
            elif isinstance(value, dict):
                for k in ("url", "contentUrl", "@id"):
                    if isinstance(value.get(k), str):
                        out.append(value[k])
        else:
            _walk_json_images(value, out)


def extract_image_urls(html: str, base_url: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Gallery URLs from a listing page, best first, absolute and de-duplicated.

    Order of trust: og:image (the page's own hero), structured data (the MLS gallery),
    then <img>/<picture> tags in document order. Logos, icons and tracking pixels are
    dropped by name, and anything that is not a raster image is skipped.
    """
    html = html or ""
    found: list[str] = []

    for tag in _META_RE.findall(html):
        a = _attrs(tag)
        key = (a.get("property") or a.get("name") or "").lower()
        if key in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
            if a.get("content"):
                found.append(a["content"])

    for block in _LD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        _walk_json_images(data, found)

    for tag in _IMG_RE.findall(html):
        a = _attrs(tag)
        for key in ("src", "data-src", "data-lazy-src", "data-original", "data-image"):
            if a.get(key):
                found.append(a[key])
                break
        if a.get("srcset"):
            best = _srcset_best(a["srcset"])
            if best:
                found.append(best)

    out: list[str] = []
    seen: set[str] = set()
    for raw in found:
        url = urljoin(base_url, raw.strip())
        if not url.startswith(("http://", "https://")):
            continue
        if not _looks_like_image(url) or _is_furniture(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= max(1, int(limit)):
            break
    return out


def guess_ext(url: str, content_type: str = "") -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in CONTENT_TYPE_EXT:
        return CONTENT_TYPE_EXT[ctype]
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in IMAGE_EXTS:
        return ".jpg" if ext == ".jpeg" else ext
    return ""


def source_name(url: str, ext: str) -> str:
    """A name a human would recognise in the photo index ('front-of-house.jpg')."""
    stem = os.path.splitext(os.path.basename(urlparse(url).path))[0]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return (stem or "listing-photo") + ext


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=15.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,image/*,*/*"},
    )


async def discover(listing_url: str, limit: int = DEFAULT_LIMIT, client: httpx.AsyncClient | None = None) -> list[str]:
    """Fetch a listing page and return the image URLs on it."""
    own = client is None
    client = client or _client()
    try:
        resp = await client.get(listing_url, headers={"Accept": "text/html,*/*"})
        resp.raise_for_status()
        return extract_image_urls(resp.text, str(resp.url), limit=limit)
    finally:
        if own:
            await client.aclose()


async def import_from_urls(
    db,
    *,
    user_id: int,
    boost_id: int | None,
    urls: list[str],
    upload_dir: str,
    limit: int = DEFAULT_LIMIT,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Download image URLs into uploads/ and record one Asset per stored photo.

    Returns {'imported': n, 'skipped': [...], 'assets': [{'asset_id', 'url', 'name', 'bytes'}]}.
    A URL that 404s, is not an image, or is larger than MAX_BYTES is skipped with a reason
    instead of failing the batch — a gallery with one dead link should still import.
    """
    from app.db.session import Asset  # local import keeps this module import-light

    os.makedirs(upload_dir, exist_ok=True)
    own = client is None
    client = client or _client()
    imported: list[dict] = []
    skipped: list[dict] = []
    seen_urls: set[str] = set()
    try:
        existing = {
            (a.original_name or "").lower()
            for a in db.query(Asset).filter(Asset.boost_id == boost_id).all()
        } if boost_id is not None else set()
        for url in urls:
            if len(imported) >= max(1, int(limit)):
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                resp = await client.get(url, headers={"Accept": "image/*"})
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                ext = guess_ext(url, content_type)
                if not ext:
                    skipped.append({"url": url, "reason": f"not an image ({content_type or 'no content-type'})"})
                    continue
                data = resp.content
                if not data:
                    skipped.append({"url": url, "reason": "empty response"})
                    continue
                if len(data) > MAX_BYTES:
                    skipped.append({"url": url, "reason": f"too large ({len(data) // 1024} KB)"})
                    continue
            except httpx.HTTPError as exc:
                skipped.append({"url": url, "reason": f"download failed: {exc.__class__.__name__}"})
                continue

            name = source_name(url, ext)
            if name.lower() in existing:
                skipped.append({"url": url, "reason": "already imported"})
                continue
            filename = f"{uuid.uuid4().hex}{ext}"
            with open(os.path.join(upload_dir, filename), "wb") as fh:
                fh.write(data)
            asset = Asset(
                user_id=user_id,
                boost_id=boost_id,
                filename=filename,
                url=f"/uploads/{filename}",
                original_name=name,
                kind="photo",
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)
            existing.add(name.lower())
            imported.append({"asset_id": asset.id, "url": asset.url, "name": name, "bytes": len(data)})
    finally:
        if own:
            await client.aclose()
    return {"imported": len(imported), "skipped": skipped, "assets": imported}
