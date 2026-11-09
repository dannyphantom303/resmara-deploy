#!/usr/bin/env python3
"""Listing photos must be able to reach a campaign.

The calendar only shows an image when the engine's plan names an Asset that exists, so
photo import is not a nicety: with an empty gallery every post is text. This pins the two
halves — what counts as a listing photo on a page, and what gets stored — without touching
the live internet (extraction is pure, downloads go through a mock transport).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = 0

PAGE = """
<html><head>
<meta content="https://cdn.example.test/gallery/hero-front.jpg" property="og:image">
<meta name="twitter:image" content="https://cdn.example.test/gallery/hero-front.jpg">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"SingleFamilyResidence",
 "image":["https://cdn.example.test/gallery/kitchen.jpg",
          {"@type":"ImageObject","url":"https://cdn.example.test/gallery/living-room.webp"}]}
</script>
</head><body>
<img src="/gallery/patio.png" alt="patio">
<img data-src="https://cdn.example.test/gallery/master-bed.jpeg" alt="master">
<img srcset="https://cdn.example.test/gallery/bath-small.jpg 480w, https://cdn.example.test/gallery/bath-large.jpg 1280w" alt="bath">
<img src="https://cdn.example.test/brand/logo.svg" alt="logo">
<img src="https://cdn.example.test/brand/agent-headshot.jpg" alt="agent">
<img src="https://cdn.example.test/pixel?id=3" alt="">
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="">
</body></html>
"""


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS += 1


def main() -> int:
    db = tempfile.mkdtemp(prefix="resmara_photo_import_")
    uploads = Path(db) / "uploads"
    os.environ["DATABASE_URL"] = f"sqlite:///{db}/app.db"
    os.environ["UPLOAD_DIR"] = str(uploads)
    for key in ("RESMARA_ENGINE_BASE_URL", "RESMARA_ENGINE_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(key, None)
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        del sys.modules[mod]

    import asyncio

    import httpx
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app
    from app.services import photos

    # --- extraction is a pure function: no network, no model ------------------------------
    urls = photos.extract_image_urls(PAGE, "https://listing.example.test/property/42", limit=10)
    check("og:image comes first and wins", urls and urls[0].endswith("hero-front.jpg"), str(urls[:2]))
    check("structured data is read", any("kitchen.jpg" in u for u in urls), str(urls))
    check("a relative <img> becomes absolute",
          "https://listing.example.test/gallery/patio.png" in urls, str(urls))
    check("data-src lazy images count", any("master-bed.jpeg" in u for u in urls), str(urls))
    check("srcset keeps the largest candidate",
          any("bath-large.jpg" in u for u in urls) and not any("bath-small.jpg" in u for u in urls), str(urls))
    check("logos, headshots and tracking pixels are dropped",
          not any(x in " ".join(urls) for x in ("logo", "headshot", "pixel")), str(urls))
    check("data: URIs are ignored", not any(u.startswith("data:") for u in urls), str(urls))
    check("no duplicates survive", len(urls) == len(set(urls)), str(urls))
    check("the limit is respected", len(photos.extract_image_urls(PAGE, "https://x.test", limit=2)) == 2)

    # --- site adapters: the gallery lives in inline JSON, not meta tags -------------------
    # These fixtures are the exact shapes seen on live pages: Movoto's __INITIAL_STATE__ and
    # Trulia's __NEXT_DATA__. If either shape changes, the import silently degrades to 1-3
    # photos, so the shapes are pinned here.
    MOVOTO_DETAIL = """<html><body><script id="__INITIAL_STATE__" type="application/json">
    {"pageData": {"photoCount": 3, "categorizedPhotos": [
      {"category": "Exterior", "photos": [
        {"url": "https://pi.movoto.com/p/1/abc_0_AAA.webp",
         "images": {"p": "_p.webp", "l": "_l.webp", "r": "_r.webp"}},
        {"url": "https://pi.movoto.com/p/1/def_0_BBB.webp",
         "images": {"p": "_p.webp", "l": "_l.webp", "r": "_r.webp"}}]},
      {"category": "Kitchen", "photos": [
        {"url": "https://pi.movoto.com/p/1/ghi_0_CCC.webp",
         "images": {"p": "_p.webp", "l": "_l.webp", "r": "_r.webp"}}]}]}}
    </script></body></html>"""
    mov = photos.movoto_photo_urls(MOVOTO_DETAIL)
    check("movoto keeps the whole gallery", len(mov) == 3, str(mov))
    check("movoto upgrades the 480px thumbnail suffix to 1920px",
          mov and mov[0].endswith("_l.webp") and "_p" not in mov[0], str(mov[:1]))
    check("movoto falls back to nothing rather than guessing on a broken blob",
          photos.movoto_photo_urls("<html>no state</html>") == [])

    MOVOTO_CITY = """<script id="__INITIAL_STATE__" type="application/json">
    {"pageData": {"listings": [
      {"mlsNumber": "1", "listPrice": 344900, "bed": 3, "bath": 2, "sqftTotal": 1487,
       "photoCount": 17, "path": "redding-ca/1354-harpole-rd-redding-ca-96002/pid_1/",
       "geo": {"address": "1354 Harpole Rd", "city": "Redding", "zipcode": "96002"}}]}}
    </script>"""
    city = photos.movoto_listings(MOVOTO_CITY)
    check("movoto city page yields listings", len(city) == 1 and city[0]["price"] == 344900, str(city))
    check("movoto listing URLs are absolute",
          city and city[0]["url"].startswith("https://www.movoto.com/redding-ca/"), str(city[:1]))

    TRULIA_DETAIL = """<html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props": {"homeDetails": {"media": {"totalPhotoCount": 2, "photos": [
      {"url": {"large": "https://www.trulia.com/pictures/thumbs_5/zillowstatic/fp/aaaa1111-full.jpg",
               "thumbnail": "https://www.trulia.com/pictures/thumbs_big/zillowstatic/fp/aaaa1111-full.jpg"}},
      {"url": {"large": "https://www.trulia.com/pictures/thumbs_5/zillowstatic/fp/bbbb2222-full.jpg"}}]}}}}
    </script>
    <script type="application/ld+json">{"@type":"Product","image":"https://x.test/logo.png"}</script>
    </body></html>"""
    thumbs = photos.trulia_photo_urls(TRULIA_DETAIL, full_res=False)
    check("trulia reads the Next.js gallery, not the single JSON-LD hero",
          len(thumbs) == 2 and "aaaa1111" in thumbs[0], str(thumbs))
    check("trulia drops furniture", not any("logo" in u for u in thumbs), str(thumbs))
    full = photos.trulia_photo_urls(TRULIA_DETAIL)
    check("trulia can upgrade to the 3000px CDN original",
          full and full[0].startswith("https://photos.zillowstatic.com/fp/aaaa1111-full.jpg"),
          str(full[:1]))
    check("trulia with no data yields nothing", photos.trulia_photo_urls("<html/>") == [])

    rows = [{"address": None, "url": "https://www.trulia.com/home/1354-harpole-rd-redding-ca-96002-1"},
            {"address": None, "url": "https://www.trulia.com/home/1154-echo-rd-redding-ca-96002-2"}]
    hit = photos.match_listing(rows, "1354 Harpole Road, Redding, CA", "96002")
    check("an address finds its listing across St/Road spellings",
          hit and "harpole" in hit["url"], str(hit))
    miss = photos.match_listing(rows, "999 Nowhere Ln, Redding, CA", "96002")
    check("a different address matches nothing", miss is None, str(miss))
    check("no address means no match", photos.match_listing(rows, "", "") is None)
    check("a zip mismatch is not a match",
          photos.match_listing(rows, "1354 Harpole Rd, Redding, CA", "99999") is None)

    # --- download + store, through a mock transport ---------------------------------------
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 2048
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 1024
    files = {
        "https://cdn.example.test/gallery/hero-front.jpg": (jpeg, "image/jpeg"),
        "https://cdn.example.test/gallery/kitchen.jpg": (png, "image/png"),
        "https://cdn.example.test/gallery/gone.jpg": (None, "text/html"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body, ctype = files.get(str(request.url), (None, "text/html"))
        if body is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, content=body, headers={"content-type": ctype})

    settings.SIMULATE = True
    client_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    with TestClient(app) as client:
        reg = client.post("/api/auth/register", json={
            "email": f"photos{abs(hash(db)) % 10**8}@example.com", "password": "photo-pass-12345", "name": "Photos"})
        token = client.post("/api/auth/login", data={
            "username": reg.json()["email"], "password": "photo-pass-12345"}).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        boost_id = client.post("/api/boosts", headers=h, json={
            "address": "2163 Sycamore Dr, Redding, CA", "campaign_days": 14}).json()["id"]

        from app.db.session import Asset, SessionLocal

        db_session = SessionLocal()
        try:
            result = asyncio.run(photos.import_from_urls(
                db_session, user_id=1, boost_id=boost_id,
                urls=["https://cdn.example.test/gallery/hero-front.jpg",
                      "https://cdn.example.test/gallery/kitchen.jpg",
                      "https://cdn.example.test/gallery/gone.jpg"],
                upload_dir=str(uploads), limit=10, client=client_http))
        finally:
            db_session.close()
        asyncio.run(client_http.aclose())

        check("both good photos import", result["imported"] == 2, str(result.get("skipped")))
        check("the dead link is reported, not fatal",
              any("gone.jpg" in s["url"] for s in result["skipped"]), str(result["skipped"]))
        stored = list(uploads.glob("*"))
        check("the bytes land in uploads/", len(stored) == 2, str([p.name for p in stored]))
        check("the extension follows the real content type",
              {p.suffix for p in stored} == {".jpg", ".png"}, str([p.suffix for p in stored]))

        listed = client.get(f"/api/content/assets/{boost_id}", headers=h).json()
        check("assets are readable over the API", len(listed) == 2, str(len(listed)))
        check("each asset carries a /uploads URL",
              all(a["url"].startswith("/uploads/") for a in listed), str([a["url"] for a in listed]))
        check("the name is human-readable for the photo index",
              any("hero-front" in (a.get("original_name") or "") for a in listed), str(listed))

        index = client.get(f"/api/content/photo-index/{boost_id}", headers=h).json()
        check("the engine's photo index sees them", index["assets"] == 2 and "hero-front" in index["photo_index"],
              index["photo_index"][:120])

        # Importing the same gallery twice must not double the gallery.
        db_session = SessionLocal()
        try:
            again = asyncio.run(photos.import_from_urls(
                db_session, user_id=1, boost_id=boost_id,
                urls=["https://cdn.example.test/gallery/hero-front.jpg"],
                upload_dir=str(uploads), limit=10,
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)))
        finally:
            db_session.close()
        check("a second import of the same photo is skipped", again["imported"] == 0, str(again))
        check("and says why", any("already imported" in s["reason"] for s in again["skipped"]), str(again["skipped"]))

        # --- the endpoint contract --------------------------------------------------------
        bad = client.post("/api/content/import/photos", headers=h, json={"boost_id": boost_id})
        check("no URL and no listing link is a 400", bad.status_code == 400, str(bad.status_code))
        empty = client.post("/api/content/import/photos", headers=h, json={
            "boost_id": boost_id, "urls": ["https://cdn.example.test/gallery/gone.jpg"]})
        check("an unreadable URL answers with a reason, not a 500",
              empty.status_code == 201 and empty.json()["imported"] == 0, str(empty.text[:120]))

        stranger = client.post("/api/auth/register", json={
            "email": f"stranger{abs(hash(db)) % 10**8}@example.com", "password": "photo-pass-12345", "name": "S"})
        stoken = client.post("/api/auth/login", data={
            "username": stranger.json()["email"], "password": "photo-pass-12345"}).json()["access_token"]
        stolen = client.post("/api/content/import/photos", headers={"Authorization": f"Bearer {stoken}"},
                             json={"boost_id": boost_id, "urls": ["https://cdn.example.test/gallery/kitchen.jpg"]})
        check("another user cannot import into your campaign", stolen.status_code == 404, str(stolen.status_code))

        count = SessionLocal().query(Asset).filter(Asset.boost_id == boost_id).count()
        check("nothing extra was written to the gallery", count == 2, str(count))

        # --- the photo must survive a deploy ----------------------------------------------
        # A hosted instance restarts with an empty uploads/, so the disk copy cannot be the
        # only copy: the served URL has to keep working.
        served = client.get(listed[0]["url"])
        check("a stored photo is served from disk", served.status_code == 200 and served.content, str(served.status_code))
        for path in uploads.glob("*"):
            path.unlink()
        after_wipe = client.get(listed[0]["url"])
        check("and still served after uploads/ is wiped",
              after_wipe.status_code == 200 and after_wipe.content == jpeg or after_wipe.content == png,
              f"{after_wipe.status_code} {len(after_wipe.content)}b")
        check("with the right content type", after_wipe.headers.get("content-type", "").startswith("image/"),
              str(after_wipe.headers.get("content-type")))
        missing = client.get("/uploads/does-not-exist.jpg")
        check("an unknown file is still a 404", missing.status_code == 404, str(missing.status_code))

    # --- a plan that names no photo must still fill the calendar ---------------------------
    from app.services.content_engine import post_image_urls

    gallery = ["/uploads/one.jpg", "/uploads/two.webp"]
    plan = [{"day": 1, "photoFile": "one.jpg"}, {"day": 2, "photoFile": "NEEDS PHOTO"},
            {"day": 3, "photoFile": ""}, {"day": 4}]
    images, rotated = post_image_urls(plan, {"one.jpg": "/uploads/one.jpg"}, gallery)
    check("a named photo is used as-is", images[0] == "/uploads/one.jpg", str(images))
    check("an unmatched slot takes a real gallery photo instead of nothing",
          all(u.startswith("/uploads/") for u in images), str(images))
    check("rotation spreads the gallery", images[1] != images[2], str(images))
    check("the count of rotated photos is reported", rotated == 3, str(rotated))
    empty_images, empty_rotated = post_image_urls(plan, {}, [])
    check("with no photos at all nothing is invented",
          all(u == "" for u in empty_images) and empty_rotated == 0, str(empty_images))

    print(f"{'FAILED' if FAILS else 'ok'} — listing photo import")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
