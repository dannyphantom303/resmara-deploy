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

    Order of trust: og:image (the page's own hero and the most reliable single image),
    the MLS gallery in structured data, then <img>/<picture> tags in document order. Logos,
    icons and tracking pixels are dropped by name, and anything that is not a raster image
    is skipped.

    This is the generic path. Movoto and Trulia bury nothing useful in meta tags — on a
    52-photo Movoto listing every meta/tag heuristic together found 3 URLs — so
    ``discover`` prefers the site adapters below and only lands here for other hosts.
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


# ---------------------------------------------------------------------------
# Site adapters.
#
# Listing galleries are not in og:image or <img> tags — they are in inline JSON. Movoto
# keeps a `__INITIAL_STATE__` blob, Trulia publishes JSON-LD. Reading that JSON is the
# difference between 3 photos and all of them, so each site gets an explicit parser and a
# testable pure function.
# ---------------------------------------------------------------------------

_INITIAL_STATE_RE = re.compile(
    r'<script[^>]*id=["\']__INITIAL_STATE__["\'][^>]*>(.*?)</script>', re.I | re.S)
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S)
_ZILLOW_HASH_RE = re.compile(r"zillowstatic/fp/([a-z0-9]+)", re.I)


def _json_blobs(html: str) -> list:
    out = []
    for block in _LD_RE.findall(html or ""):
        try:
            out.append(json.loads(block.strip()))
        except (ValueError, TypeError):
            continue
    return out


def _initial_state(html: str) -> dict:
    m = _INITIAL_STATE_RE.search(html or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _next_data(html: str) -> dict:
    """The Next.js props blob Trulia (and every other modern listing site) renders from."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def movoto_photo_urls(html: str, size: str = "l") -> list[str]:
    """Every gallery photo on a Movoto detail page, in the order the listing shows them.

    Movoto's size suffixes: "" original (2048px), "_l" 1920px, "_r" 960px, "_p" 480px
    thumbnail. "l" is the bandwidth/quality sweet spot; "p" — which is what the card
    thumbnail field holds — is a tile, not a photo.
    """
    state = _initial_state(html)
    page = state.get("pageData") or {}
    out: list[str] = []
    for category in page.get("categorizedPhotos") or []:
        for photo in (category or {}).get("photos") or []:
            url = (photo or {}).get("url")
            if not isinstance(url, str):
                continue
            suffix = ((photo.get("images") or {}).get(size) or "")
            out.append(url.replace(".webp", suffix) if suffix and url.endswith(".webp") else url)
    return list(dict.fromkeys(u for u in out if _looks_like_image(u)))


def movoto_listings(html: str) -> list[dict]:
    """The listings on a Movoto city page (price, beds, baths, sqft, detail path)."""
    page = (_initial_state(html).get("pageData") or {})
    rows = []
    for item in page.get("listings") or []:
        path = (item or {}).get("path")
        if not isinstance(path, str):
            continue
        rows.append({
            "address": ((item.get("geo") or {}).get("address") or "").strip(),
            "city": (item.get("geo") or {}).get("city"),
            "zip": (item.get("geo") or {}).get("zipcode"),
            "price": item.get("listPrice"), "beds": item.get("bed"), "baths": item.get("bath"),
            "sqft": item.get("sqftTotal"), "photo_count": item.get("photoCount"),
            "url": urljoin("https://www.movoto.com/", path),
        })
    return rows


def trulia_photo_urls(html: str, full_res: bool = True) -> list[str]:
    """Trulia gallery photos, upgraded to Zillow's CDN original when possible.

    Trulia is a Next.js app: the gallery is ``props.homeDetails.media.photos[].url.large``
    inside ``__NEXT_DATA__`` (JSON-LD carries only one hero image, so it is the fallback).
    Photos are served at 1024px from ``/pictures/thumbs_5/zillowstatic/fp/<hash>-full.jpg``;
    the same hash on ``photos.zillowstatic.com`` returns the 3000×2250 original with no
    Referer required, and Trulia's robots.txt explicitly allows the thumbs path.
    """
    urls: list[str] = []

    data = _next_data(html)
    if data:
        home = ((data.get("props") or {}).get("homeDetails") or {})
        media = home.get("media") or {}
        for photo in media.get("photos") or []:
            url = (photo or {}).get("url") if isinstance(photo, dict) else None
            if isinstance(url, dict):
                urls.append(url.get("large") or url.get("thumbnail") or "")
            elif isinstance(url, str):
                urls.append(url)

    found: list[str] = []
    for blob in _json_blobs(html):
        _walk_json_images(blob, found)
    urls.extend(found)

    out: list[str] = []
    for url in urls:
        if not url or _is_furniture(url):
            continue
        m = _ZILLOW_HASH_RE.search(url)
        if m and full_res:
            out.append(f"https://photos.zillowstatic.com/fp/{m.group(1)}-full.jpg")
        elif _looks_like_image(url):
            out.append(url)
    return list(dict.fromkeys(out))


def trulia_listings(html: str) -> list[dict]:
    """Listings on a Trulia city page, taken from JSON-LD (the page has no listing links)."""
    rows: list[dict] = []

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            offers = node.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            url = (offer or {}).get("url") if isinstance(offer, dict) else None
            if isinstance(url, str) and "/home/" in url:
                offered = node.get("itemOffered") if isinstance(node.get("itemOffered"), dict) else node
                rows.append({
                    "url": url,
                    "price": (offer or {}).get("price"),
                    "beds": offered.get("numberOfBedrooms"),
                    "baths": offered.get("numberOfBathroomsTotal"),
                    "sqft": ((offered.get("floorSize") or {}).get("value")
                             if isinstance(offered.get("floorSize"), dict) else None),
                    "address": ((offered.get("address") or {}).get("streetAddress")
                                if isinstance(offered.get("address"), dict) else None),
                })
            for value in node.values():
                visit(value)

    for blob in _json_blobs(html):
        visit(blob)
    seen, out = set(), []
    for row in rows:
        if row["url"] in seen:
            continue
        seen.add(row["url"])
        out.append(row)
    return out


def _street_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def match_listing(rows: list[dict], address: str = "", zipcode: str = "") -> dict | None:
    """Find the listing for the same property as ``address`` ('1234 Elm St, Redding, CA').

    Matches on the house number plus at least two street words, in either the row's own
    address or its URL slug — that is what lets a Zillow link be re-resolved on Trulia,
    where 'St' and 'Street' must still be the same house.
    """
    tokens = _street_tokens(address)
    if not tokens:
        return None
    number = tokens[0] if tokens[0].isdigit() else ""
    street = tokens[1:4]
    if not number and len(street) < 2:
        return None
    want_zip = (zipcode or "").strip()

    for row in rows:
        address_tokens = set(_street_tokens(row.get("address") or ""))
        slug = re.sub(r"[^a-z0-9]+", "-", (row.get("url") or "").lower())
        has_number = (number and (number in address_tokens or number in slug)) if number else True
        hits = sum(1 for t in street if t in address_tokens or t in slug)
        if has_number and hits >= min(2, len(street) or 2):
            if want_zip and want_zip not in slug and want_zip not in (row.get("address") or ""):
                continue
            return row
    return None


def address_from_listing_url(url: str) -> tuple[str, str, str]:
    """(address, state, zip) guessed from a listing URL, for the Trulia fallback."""
    path = urlparse(url).path
    slug = path.strip("/").split("/")[-2] if path.strip("/").count("/") >= 1 else path.strip("/")
    slug = slug.replace("_zpid", "")
    parts = [p for p in slug.split("-") if p]
    address = " ".join(parts[:4])
    state = next((p for p in parts if re.fullmatch(r"[A-Z]{2}", p)), "")
    zipcode = next((p for p in parts if re.fullmatch(r"\d{5}", p)), "")
    return address, state, zipcode


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


_CHROME_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _trulia_city_url(address: str, zipcode: str) -> str:
    """Best guess at a Trulia city page for an address ('1234 Elm St, Redding, CA')."""
    m = re.search(r",\s*([^,]+),\s*([A-Z]{2})\b", address or "")
    if not m:
        return ""
    city = re.sub(r"[^A-Za-z ]+", "", m.group(1)).strip().replace(" ", "-")
    return f"https://www.trulia.com/{m.group(2)}/{city}/"


async def discover(listing_url: str, limit: int = DEFAULT_LIMIT, client: httpx.AsyncClient | None = None,
                   address: str = "", zipcode: str = "", trace: list | None = None) -> list[str]:
    """Gallery photo URLs for a listing, using the site that actually still serves them.

    One fetch per page, no headless browser. Which source is used is decided by host:

      * movoto.com — the listing's own ``__INITIAL_STATE__`` gallery (all photos, 1920px)
      * trulia.com — JSON-LD gallery upgraded to the 3000px Zillow CDN original
      * anything else (zillow, realtor, redfin, homes.com, an MLS page) — that page is
        tried first, and if it is walled or yields nothing, the same property is looked up
        on Trulia by address. Those hosts block server-side fetches outright; Trulia is
        the same inventory without the wall.

    Returns [] rather than raising when a page yields nothing, so the caller can explain
    the options instead of surfacing an httpx status code.
    """
    own = client is None
    client = client or _client()
    host = _host(listing_url)

    def note(url, outcome):
        # A wall is worth reporting: "Movoto answered 403 from our IP" is a fixable fact,
        # an empty photo list is not.
        if trace is not None:
            trace.append({"url": url, "outcome": outcome})

    try:
        try:
            resp = await client.get(listing_url, headers=_CHROME_HEADERS)
            note(listing_url, resp.status_code)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPError as exc:
            note(listing_url, getattr(getattr(exc, "response", None), "status_code", None) or exc.__class__.__name__)
            html = ""

        if "movoto.com" in host and html:
            photos = movoto_photo_urls(html)
            if photos:
                return photos[:limit]
            rows = movoto_listings(html)                    # a city page, not a listing
            match = match_listing(rows, address, zipcode)
            if match:
                detail = await client.get(match["url"], headers=_CHROME_HEADERS)
                detail.raise_for_status()
                return movoto_photo_urls(detail.text)[:limit]

        if "trulia.com" in host and html:
            # 1024px thumbs, not the 3000px originals: a Facebook or Instagram post is
            # 1080px wide, so the original is ~8x the bytes for detail nobody sees, and on a
            # free database every campaign's gallery is stored as bytes.
            photos = trulia_photo_urls(html, full_res=False)
            if photos:
                return photos[:limit]

        if html:
            generic = extract_image_urls(html, str(resp.url), limit=limit)
            if generic:
                return generic

        # Walled or empty: same property, friendlier host.
        city_url = _trulia_city_url(address, zipcode)
        if city_url and "trulia.com" not in host:
            city = await client.get(city_url, headers=_CHROME_HEADERS)
            note(city_url, city.status_code)
            if city.status_code == 200:
                match = match_listing(trulia_listings(city.text), address, zipcode)
                if match:
                    detail = await client.get(match["url"], headers=_CHROME_HEADERS)
                    detail.raise_for_status()
                    return trulia_photo_urls(detail.text, full_res=False)[:limit]
        return []
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
        rows = db.query(Asset).filter(Asset.boost_id == boost_id).all() if boost_id is not None else []
        existing = {(a.original_name or "").lower(): a for a in rows}
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
                # Same photo as before. If its bytes were lost (an asset imported before images
                # were stored with the row, or a wiped disk), this is the chance to repair it.
                old = existing[name.lower()]
                if not getattr(old, "data", None):
                    old.data = data
                    old.content_type = content_type or None
                    db.commit()
                    imported.append({"asset_id": old.id, "url": old.url, "name": name,
                                     "bytes": len(data), "restored": True})
                else:
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
                data=data,
                content_type=content_type or None,
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)
            existing[name.lower()] = asset
            imported.append({"asset_id": asset.id, "url": asset.url, "name": name, "bytes": len(data)})
    finally:
        if own:
            await client.aclose()
    return {"imported": len(imported), "skipped": skipped, "assets": imported}
