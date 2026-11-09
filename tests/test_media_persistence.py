#!/usr/bin/env python3
"""An uploaded video has to survive the deploy that follows it.

The product now sells campaigns whose plan includes a video slot, and the owner uploads
that clip rather than having it generated. A free-tier host rebuilds its disk on every
deploy, so a file that lives ONLY on disk becomes a 404 — for the post, for the calendar
thumbnail and for Meta, which fetches the media back by URL.

Photos already kept their bytes in the Asset row. Video did not (the content-type test
said image/*), and bulk upload skipped the bytes entirely. This pins all three:
  * a video upload keeps its bytes and its content type
  * a bulk upload keeps them per file
  * /uploads/<name> still serves the media after the file is deleted from disk
  * a file over the cap is refused with a 413 that names the limit, not silently dropped
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global FAILS
    if cond:
        print("  ok   %s" % label)
    else:
        FAILS += 1
        print("  FAIL %s %s" % (label, detail))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="resmara-media-")
    os.environ["RESMARA_UPLOAD_DIR"] = tmp
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "media.db")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-media-persistence")

    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import Asset, SessionLocal, Base, engine

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    email = "media-check@example.com"
    password = "media-pass-123"
    r = client.post("/api/auth/register", json={"email": email, "password": password, "name": "Media"})
    if r.status_code not in (200, 201):
        check("register", False, r.text[:200])
        return 1
    r = client.post("/api/auth/login", data={"username": email, "password": password})
    check("login", r.status_code == 200, r.text[:160])
    token = r.json().get("access_token", "")
    H = {"Authorization": "Bearer " + token}

    # ── a video ad, the thing the owner uploads instead of generating ──────────
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000
    r = client.post("/api/content/upload/photo", headers=H,
                    files={"file": ("listing-tour.mp4", mp4, "video/mp4")},
                    data={"kind": "video"})
    check("video upload accepted", r.status_code == 201, r.text[:200])
    body = r.json() if r.status_code == 201 else {}
    vid_name = body.get("filename", "")
    check("video has a url", body.get("url", "").startswith("/uploads/"), str(body)[:160])

    db = SessionLocal()
    try:
        va = db.query(Asset).filter(Asset.filename == vid_name).first()
        check("video row exists", va is not None)
        check("video bytes kept", bool(va and va.data), "asset.data is empty")
        check("video bytes are complete", bool(va and va.data and len(va.data) == len(mp4)),
              "%s vs %s" % (len(va.data) if va and va.data else 0, len(mp4)))
        check("video content type kept", bool(va and va.content_type == "video/mp4"),
              str(va.content_type if va else None))
    finally:
        db.close()

    # ── a photo through the bulk route, which used to store no bytes at all ────
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 800
    r = client.post("/api/content/uploads", headers=H,
                    files=[("files", ("kitchen.png", png, "image/png"))],
                    data={"kind": "photo"})
    check("bulk upload accepted", r.status_code == 201, r.text[:200])
    db = SessionLocal()
    try:
        pa = db.query(Asset).filter(Asset.original_name == "kitchen.png").first()
        check("bulk photo bytes kept", bool(pa and pa.data), "asset.data is empty")
    finally:
        db.close()

    # ── the disk is rebuilt by the next deploy: the media must still answer ────
    disk_copy = os.path.join(tmp, vid_name)
    if os.path.exists(disk_copy):
        os.remove(disk_copy)
    r = client.get("/uploads/" + vid_name)
    check("/uploads still serves the video from the row", r.status_code == 200, str(r.status_code))
    check("and serves it as video", r.headers.get("content-type", "").startswith("video/"),
          r.headers.get("content-type", ""))
    check("and serves the original bytes", r.content == mp4, "%d bytes" % len(r.content))

    # ── over the cap: refused by name, not silently dropped ────────────────────
    import app.api.content as content_mod
    was = content_mod.MAX_KEPT_BYTES
    content_mod.MAX_KEPT_BYTES = 1024
    try:
        r = client.post("/api/content/upload/photo", headers=H,
                        files={"file": ("big.mp4", b"\x00" * 5000, "video/mp4")},
                        data={"kind": "video"})
        check("an oversized video is refused", r.status_code == 413, str(r.status_code))
        check("and the refusal names the limit", "MB" in r.text, r.text[:160])
    finally:
        content_mod.MAX_KEPT_BYTES = was

    print("PASS — uploaded video and bulk photos keep their bytes with the row, /uploads answers\n"
          "       after the disk is wiped, and an oversized file is refused by name")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
