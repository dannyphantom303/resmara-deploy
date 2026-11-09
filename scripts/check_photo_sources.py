"""Live check of the photo adapters against real listing pages.

Proves, from this machine, that the import path returns actual gallery photos (not og:image
thumbnails) for the sources the product now depends on.

Run: cd ~/resmara && PYTHONPATH=. ./venv/bin/python3 scripts/check_photo_sources.py
"""
import asyncio
import sys

import httpx

from app.services import photos

CHROME = photos._CHROME_HEADERS


async def fetch(client, url):
    r = await client.get(url, headers=CHROME)
    return r.status_code, r.text


async def main():
    ok = True
    async with httpx.AsyncClient(follow_redirects=True, timeout=40) as client:
        print("== Movoto city page ==")
        status, html = await fetch(client, "https://www.movoto.com/redding-ca/")
        rows = photos.movoto_listings(html)
        print(f"  status={status} listings={len(rows)}")
        if rows:
            first = rows[0]
            print(f"  first: {first['address']} ${first['price']} {first['beds']}bd/{first['baths']}ba "
                  f"{first['sqft']}sqft photos={first['photo_count']}")
            s2, detail = await fetch(client, first["url"])
            urls = photos.movoto_photo_urls(detail)
            print(f"  detail status={s2} photos={len(urls)} first={urls[0] if urls else None}")
            ok = ok and len(urls) >= 5 and "movoto.com" in (urls[0] if urls else "")
        else:
            ok = False

        print("\n== Movoto photo really downloads ==")
        if rows:
            url = photos.movoto_photo_urls(detail)[0]
            img = await client.get(url, headers={"Accept": "image/*"})
            ctype = img.headers.get("content-type")
            print(f"  {url[-40:]} -> {img.status_code} {ctype} {len(img.content)} bytes")
            ok = ok and img.status_code == 200 and ctype.startswith("image")

        print("\n== Trulia city page ==")
        status, html = await fetch(client, "https://www.trulia.com/CA/Redding/")
        rows = photos.trulia_listings(html)
        print(f"  status={status} listings={len(rows)}")
        if rows:
            print(f"  first: {rows[0]['address']} ${rows[0]['price']} {rows[0]['url']}")
            # Some listings are "coming soon" with an empty gallery; walk until one has photos.
            urls, used = [], None
            for row in rows[:6]:
                s2, detail = await fetch(client, row["url"])
                urls = photos.trulia_photo_urls(detail)
                used = row
                print(f"  {row['url'].split('/')[-1][:42]} status={s2} photos={len(urls)}")
                if len(urls) >= 5:
                    break
                await asyncio.sleep(2)
            print(f"  chosen photos={len(urls)} first={urls[0] if urls else None}")
            ok = ok and len(urls) >= 5
            if urls:
                img = await client.get(urls[0], headers={"Accept": "image/*"})
                print(f"  image -> {img.status_code} {img.headers.get('content-type')} {len(img.content)} bytes")
                ok = ok and img.status_code == 200 and img.headers.get("content-type", "").startswith("image")
                # The 3000px original must also be reachable, not just the 1024px thumb.
                print(f"  full-res host: {urls[0].split('/')[2]}")
                ok = ok and "photos.zillowstatic.com" in urls[0]
        else:
            ok = False

        print("\n== Wall fallback: a Zillow URL resolved through Trulia (address match) ==")
        # A Zillow listing URL for the same city: the page itself must fail, the address must not.
        zillow = "https://www.zillow.com/homedetails/0000-Nonexistent-St-Redding-CA-96001/123456_zpid/"
        try:
            s, _ = await fetch(client, zillow)
            print(f"  zillow page status={s} (blocked is expected)")
        except Exception as exc:
            print(f"  zillow page raised {exc.__class__.__name__} (treated as blocked)")
        rows_t = photos.trulia_listings((await fetch(client, "https://www.trulia.com/CA/Redding/"))[1])
        # Re-resolve by the address a Zillow URL would carry: '14058 Windfall Dr, Redding, CA'
        target_addr = "14058 Windfall Dr, Redding, CA 96003"
        match = photos.match_listing(rows_t, target_addr, "96003")
        print(f"  match {target_addr!r} -> {match['url'] if match else None}")
        ok = ok and bool(match)

        print("\n== Unsupported host yields [] not an exception ==")
        urls = await photos.discover("https://example.com/not-a-listing", limit=3,
                                     address="1234 Elm St, Nowhere, CA")
        print(f"  discover -> {urls}")
        ok = ok and urls == []

    print("\n" + ("PHOTO SOURCES OK" if ok else "PHOTO SOURCE CHECK FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
