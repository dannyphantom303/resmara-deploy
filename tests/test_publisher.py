"""Hermetic tests for app/services/publisher.py (spec §11 Social \u00b7 Publisher).

Run:
    cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_publisher.py

Plain-assert style (repo convention). Uses a temp sqlite DB, a temp uploads
dir, and a local mock Graph server that records every request and can read the
DB at request time (to prove the claim committed 'posting' BEFORE the network).
"""
import http.server
import json as _json
import os
import sys
import tempfile
import threading
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_SCRATCH = "/Users/dan/.hermes/profiles/dev/cache/scratch"
if not os.path.isdir(_SCRATCH):
    _SCRATCH = tempfile.gettempdir()
TMP = tempfile.mkdtemp(prefix="resmara_publisher_", dir=_SCRATCH)


class MockGraph:
    def __init__(self):
        self.log = []
        self.routes = []
        self.probe = {}          # responder can read the DB mid-request
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                parsed = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                entry = {"method": self.command, "path": parsed.path, "query": query,
                         "body": body, "content_type": self.headers.get("Content-Type", "")}
                outer.log.append(entry)
                status, payload = outer.route(entry)
                data = _json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._handle()

            def do_POST(self):
                self._handle()

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def add_route(self, matcher, responder):
        self.routes.append((matcher, responder))

    def route(self, entry):
        for matcher, responder in self.routes:
            if matcher(entry):
                return responder(entry) if callable(responder) else responder
        return 200, {"data": []}

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()

    def find(self, path=None, method=None):
        return [e for e in self.log
                if (path is None or path == e["path"])
                and (method is None or e["method"] == method)]


MOCK = MockGraph().start()

os.environ["GRAPH_API_BASE"] = MOCK.url
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TMP, "test.db")
os.environ["UPLOAD_DIR"] = os.path.join(TMP, "uploads")
os.environ["RESMARA_SIMULATE"] = "0"
os.makedirs(os.environ["UPLOAD_DIR"], exist_ok=True)

from app.core.config import settings  # noqa: E402

settings.GRAPH_API_BASE = MOCK.url
settings.SIMULATE = False
settings.PUBLIC_BASE_URL = "https://example.test/resmara"

from app.db.session import Base, engine, SessionLocal, User, AdAccount, Boost, Post  # noqa: E402
from app.services import publisher  # noqa: E402

Base.metadata.create_all(bind=engine)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}  {detail}")
        FAILS.append(name)


NOW = "2026-11-10T12:00:00"
PAST = "2026-11-05T10:00:00"
FUTURE = "2026-11-20T10:00:00"

# real media files
for fname, data in (("photo.jpg", b"\xff\xd8\xffJPEGBYTES"), ("pic.png", b"\x89PNG\r\n")):
    with open(os.path.join(settings.UPLOAD_DIR, fname), "wb") as fh:
        fh.write(data)

# ---------------------------------------------------------------------------
import asyncio  # noqa: E402

db = SessionLocal()
user = User(email="pub@test.com", hashed_password="x", name="P")
db.add(user)
db.commit()
acct = AdAccount(user_id=user.id, platform="meta", advertiser_id="act_123",
                 access_token="test_token", page_id="PAGE1", ig_user_id="IG1",
                 is_active=True, budget=50.0)
db.add(acct)
db.commit()
boost = Boost(user_id=user.id, ad_account_id=acct.id, address="123 Main St",
              go_live_date="2026-11-01", campaign_days=14, ad_budget_usd=50.0)
db.add(boost)
db.commit()


def new_post(**kw):
    base = dict(boost_id=boost.id, day=1, kind="photo", caption="Caption",
                hashtags="#tag", image_url="/uploads/photo.jpg",
                client_status="approved", publish_status="scheduled",
                publish_target="facebook", publish_at=PAST)
    base.update(kw)
    p = Post(**base)
    db.add(p)
    db.commit()
    return p


def fresh(post_id):
    db.expire_all()
    return db.query(Post).filter(Post.id == post_id).first()


# --- mock routes -----------------------------------------------------------
def photos_route(e):
    # read the DB *during* the request to prove the claim committed 'posting'
    sess = SessionLocal()
    try:
        pid = MOCK.probe.get("post_id")
        row = sess.query(Post).filter(Post.id == pid).first() if pid else None
        MOCK.probe.setdefault("states", []).append(row.publish_status if row else None)
    finally:
        sess.close()
    return 200, {"id": "fb_real_9"}


MOCK.add_route(lambda e: e["path"] == "/PAGE1/photos" and e["method"] == "POST", photos_route)
MOCK.add_route(lambda e: e["path"] == "/IG1/media" and e["method"] == "POST",
               lambda e: (200, {"id": "creation_1"}))
MOCK.add_route(lambda e: e["path"] == "/IG1/media_publish" and e["method"] == "POST",
               lambda e: (200, {"id": "ig_real_7"}))


# ---------------------------------------------------------------------------
def main():
    global boost

    print("=== a not-yet-due post is NOT published ===")
    p_future = new_post(day=1, publish_at=FUTURE)
    r = asyncio.run(publisher.publish_due(db, now=NOW))
    check("future post excluded", r["checked"] == 0 and r["posted"] == 0, str(r))
    check("future post still scheduled", fresh(p_future.id).publish_status == "scheduled")

    print("\n=== an unapproved post is NOT published ===")
    p_pending = new_post(day=2, client_status="pending", publish_at=PAST)
    r = asyncio.run(publisher.publish_due(db, now=NOW))
    check("pending post excluded", r["posted"] == 0 and r["checked"] == 0, str(r))
    check("pending post untouched",
          fresh(p_pending.id).publish_status == "scheduled"
          and fresh(p_pending.id).client_status == "pending")

    print("\n=== approved + due post published ONCE ===")
    p_ok = new_post(day=3, publish_target="facebook", image_url="/uploads/photo.jpg")
    MOCK.probe["post_id"] = p_ok.id
    MOCK.probe["states"] = []
    before = len(MOCK.log)
    r = asyncio.run(publisher.publish_due(db, now=NOW))
    check("one post published", r["checked"] == 1 and r["posted"] == 1, str(r))
    row = fresh(p_ok.id)
    check("marked posted with the mock's ref", row.publish_status == "posted"
          and row.fb_post_id == "fb_real_9", str((row.publish_status, row.fb_post_id)))
    fb_calls = MOCK.find(path="/PAGE1/photos", method="POST")
    check("exactly one FB photos POST", len(fb_calls) == 1)
    check("FB photos POST is multipart with a message",
          "multipart/form-data" in fb_calls[0]["content_type"]
          and b"Caption" in fb_calls[0]["body"] and b"#tag" in fb_calls[0]["body"],
          fb_calls[0]["content_type"])

    print("\n=== claim sets publish_status='posting' BEFORE the network call ===")
    check("DB read at request time saw 'posting'",
          MOCK.probe["states"] == ["posting"], str(MOCK.probe["states"]))

    print("\n=== idempotency: a second run does NOT double-publish ===")
    r2 = asyncio.run(publisher.publish_due(db, now=NOW))
    check("second run publishes nothing", r2["checked"] == 0 and r2["posted"] == 0, str(r2))
    check("still exactly one FB photos POST total",
          len(MOCK.find(path="/PAGE1/photos", method="POST")) == 1)
    check("fb_post_id unchanged", fresh(p_ok.id).fb_post_id == "fb_real_9")

    print("\n=== a post already 'posting' (crash mid-flight) is NOT republished ===")
    p_posting = new_post(day=4, publish_at=PAST, publish_status="posting")
    r = asyncio.run(publisher.publish_due(db, now=NOW))
    check("posting post excluded", r["checked"] == 0 and r["posted"] == 0, str(r))
    check("posting post stays 'posting'", fresh(p_posting.id).publish_status == "posting")
    check("no new FB call", len(MOCK.find(path="/PAGE1/photos", method="POST")) == 1)

    print("\n=== a post that flips to change_requested before the claim is skipped ===")
    p_flip = new_post(day=5, publish_at=PAST)
    # simulate: it matched selection, then the client withdrew it before the claim
    p_flip.client_status = "change_requested"
    db.commit()
    original = publisher._due_posts
    publisher._due_posts = lambda db_, now_, limit_, boost_id=None: [p_flip]  # selection already happened
    try:
        before = len(MOCK.log)
        r = asyncio.run(publisher.publish_due(db, now=NOW))
    finally:
        publisher._due_posts = original
    check("withdrawn post skipped, nothing posted",
          r["skipped"] == 1 and r["posted"] == 0, str(r))
    check("withdrawn post never claimed",
          fresh(p_flip.id).publish_status == "scheduled")
    check("withdrawn post caused no network call", len(MOCK.log) == before)

    print("\n=== a .png Instagram feed post is REFUSED with the spec wording ===")
    before = len(MOCK.log)
    p_png = new_post(day=6, publish_target="instagram", image_url="/uploads/pic.png")
    r = asyncio.run(publisher.publish_due(db, now=NOW))
    row = fresh(p_png.id)
    check("png post failed, not posted", r["failed"] == 1 and r["posted"] == 0, str(r))
    check("png post carries the spec wording", row.last_error == publisher.IG_JPG_MESSAGE,
          repr(row.last_error))
    check("wording matches the spec verbatim",
          publisher.IG_JPG_MESSAGE == ("Instagram feed posts need one JPG picture. "
                                       "Replace the file with a JPG, then get it approved again."))
    check("png post marked failed", row.publish_status == "failed")
    check("no Instagram call for the png", len(MOCK.find(path="/IG1/media")) == 0)
    check("no network call at all for the png", len(MOCK.log) == before)

    print("\n=== an Instagram .jpg feed post publishes via a public URL ===")
    p_igjpg = new_post(day=7, publish_target="instagram", image_url="/uploads/photo.jpg")
    r = asyncio.run(publisher.publish_due(db, now=NOW))
    row = fresh(p_igjpg.id)
    check("ig post published", r["posted"] == 1 and row.publish_status == "posted", str(r))
    check("ig_media_id from the mock's media_publish", row.ig_media_id == "ig_real_7",
          str(row.ig_media_id))
    media_calls = MOCK.find(path="/IG1/media", method="POST")
    check("IG media called with a PUBLIC image_url",
          media_calls and media_calls[0]["query"].get("image_url")
          == "https://example.test/resmara/uploads/photo.jpg"
          and media_calls[0]["query"].get("caption") == "Caption\n\n#tag",
          str(media_calls[0]["query"]) if media_calls else "none")
    pub_calls = MOCK.find(path="/IG1/media_publish", method="POST")
    check("IG media_publish called with creation_id",
          pub_calls and pub_calls[0]["query"].get("creation_id") == "creation_1",
          str(pub_calls))

    db.close()
    MOCK.stop()

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED: {FAILS}")
        sys.exit(1)
    print("ALL PUBLISHER TESTS PASSED")


if __name__ == "__main__":
    main()
