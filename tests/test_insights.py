"""Hermetic tests for app/services/insights.py (spec §9 organic, §10 paid).

Run:
    cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_insights.py

Plain-assert style (the repo convention): one line per check, exits non-zero on
failure. Writes only to a temp sqlite DB and a temp uploads dir; points
settings.GRAPH_API_BASE at a local mock Graph server and records every request.
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

# Temp workspace: prefer the Hermes scratch dir, stay portable if it is absent.
_SCRATCH = "/Users/dan/.hermes/profiles/dev/cache/scratch"
if not os.path.isdir(_SCRATCH):
    _SCRATCH = tempfile.gettempdir()
TMP = tempfile.mkdtemp(prefix="resmara_insights_", dir=_SCRATCH)


# ---------------------------------------------------------------------------
# local mock Graph server
# ---------------------------------------------------------------------------
class MockGraph:
    def __init__(self):
        self.log = []
        self.routes = []
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

# Point config at the mock BEFORE importing the app modules.
os.environ["GRAPH_API_BASE"] = MOCK.url
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TMP, "test.db")
os.environ["UPLOAD_DIR"] = os.path.join(TMP, "uploads")
os.environ["RESMARA_SIMULATE"] = "0"
os.makedirs(os.environ["UPLOAD_DIR"], exist_ok=True)

from app.core.config import settings  # noqa: E402

settings.GRAPH_API_BASE = MOCK.url
settings.SIMULATE = False

from app.db.session import Base, engine, SessionLocal, User, AdAccount, Boost, Post, Ad  # noqa: E402
from app.services import insights  # noqa: E402

Base.metadata.create_all(bind=engine)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}  {detail}")
        FAILS.append(name)


FROM = "2026-11-01T00:00:00"
TO = "2026-11-15T00:00:00"

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
db = SessionLocal()
user = User(email="insights@test.com", hashed_password="x", name="I")
db.add(user)
db.commit()
acct = AdAccount(user_id=user.id, platform="meta", advertiser_id="act_123",
                 access_token="test_token_abc", page_id="PAGE1", ig_user_id="IG1",
                 is_active=True, budget=50.0)
db.add(acct)
db.commit()
boost = Boost(user_id=user.id, ad_account_id=acct.id,
              address="123 Main St, Austin TX 78701", go_live_date="2026-11-01",
              campaign_days=14, ad_budget_usd=50.0)
db.add(boost)
db.commit()

p_ig = Post(boost_id=boost.id, day=1, kind="static", caption="ig", image_url="/uploads/a.jpg",
            client_status="approved", publish_status="posted", publish_target="instagram",
            ig_media_id="IGMEDIA1", publish_at="2026-11-02T10:00:00")
p_fb = Post(boost_id=boost.id, day=2, kind="static", caption="fb", image_url="/uploads/b.jpg",
            client_status="approved", publish_status="posted", publish_target="facebook",
            fb_post_id="12345", publish_at="2026-11-03T10:00:00")
db.add(p_ig)
db.add(p_fb)
db.add(Ad(boost_id=boost.id, kind="photo", primary_text="ad"))
db.commit()

# ---------------------------------------------------------------------------
# mock responses
# ---------------------------------------------------------------------------
IG_MEDIA = "IGMEDIA1"
FB_ID = "PAGE1_12345"


def is_ig_media(e):
    return e["path"] == f"/{IG_MEDIA}"


def is_ig_insights(e):
    return e["path"] == f"/{IG_MEDIA}/insights"


def is_fb_post(e):
    return e["path"] == f"/{FB_ID}"


def is_fb_reactions(e):
    return e["path"] == f"/{FB_ID}/reactions"


def is_fb_comments(e):
    return e["path"] == f"/{FB_ID}/comments"


MOCK.add_route(is_ig_media, lambda e: (200, {"permalink": "https://instagram.com/p/abc/"}))
MOCK.add_route(is_ig_insights, lambda e: (200, {"data": [
    {"name": "reach", "values": [{"value": 1000}]},
    {"name": "likes", "values": [{"value": 40}]},
    {"name": "comments", "values": [{"value": 5}]},
    {"name": "shares", "values": [{"value": 3}]},
    {"name": "saved", "values": [{"value": 7}]},
    {"name": "views", "values": [{"value": 2500}]},
]}))
MOCK.add_route(is_fb_post, lambda e: (200, {"permalink_url": "https://fb.com/p/1",
                                            "shares": {"count": 4}}))
MOCK.add_route(is_fb_reactions, lambda e: (200, {"summary": {"total_count": 11}, "data": [{}]}))
MOCK.add_route(is_fb_comments, lambda e: (200, {"data": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]}))
MOCK.add_route(lambda e: e["path"] == f"/act_123/insights" and e["query"].get("breakdowns") is None,
               lambda e: (200, {"data": [
                   {"campaign_name": "123 main \u00b7 Real Estate Boost", "campaign_id": "c1",
                    "spend": "10.00", "impressions": "5000", "reach": "3000", "clicks": "4",
                    "inline_link_clicks": "3", "cpc": "2.5", "ctr": "0.08", "frequency": "1.67"},
                   {"campaign_name": "456 oak ave \u00b7 Real Estate Boost", "campaign_id": "c2",
                    "spend": "999.00", "impressions": "9999", "reach": "9999", "clicks": "99",
                    "inline_link_clicks": "99", "cpc": "10", "ctr": "1", "frequency": "1"},
               ]}))
MOCK.add_route(lambda e: e["path"] == f"/act_123/insights" and e["query"].get("breakdowns") == "publisher_platform",
               lambda e: (200, {"data": [
                   {"campaign_name": "123 main \u00b7 Real Estate Boost",
                    "publisher_platform": "facebook", "reach": "2000"},
                   {"campaign_name": "123 main \u00b7 Real Estate Boost",
                    "publisher_platform": "instagram", "reach": "1000"},
                   {"campaign_name": "456 oak ave \u00b7 Real Estate Boost",
                    "publisher_platform": "facebook", "reach": "7777"},
               ]}))


# ---------------------------------------------------------------------------
def main():
    print("=== street_key ===")
    check("street_key lowercases first two words",
          insights.street_key("123 Main St, Austin TX 78701") == "123 main",
          insights.street_key("123 Main St, Austin TX 78701"))
    check("street_key tolerates short/empty", insights.street_key("") == ""
          and insights.street_key("A") == "a")

    print("\n=== availability / not-connected honesty ===")
    import asyncio

    check("organic_available True with a real token",
          asyncio.run(insights.organic_available(acct)) is True)
    no_tok = AdAccount(user_id=user.id, platform="meta", advertiser_id="act_999",
                       access_token="", page_id="P", ig_user_id="I", is_active=True)
    db.add(no_tok)
    db.commit()
    check("organic_available False with empty token",
          asyncio.run(insights.organic_available(no_tok)) is False)
    sim_tok = AdAccount(user_id=user.id, platform="meta", advertiser_id="act_998",
                        access_token="sim_token", page_id="P", ig_user_id="I", is_active=True)
    db.add(sim_tok)
    db.commit()
    check("organic_available False with a sim placeholder token",
          asyncio.run(insights.organic_available(sim_tok)) is False)

    before = len(MOCK.log)
    unavailable = asyncio.run(insights.organic_results(db, boost, no_tok, FROM, TO))
    check("unconnected account -> source=unavailable", unavailable["source"] == "unavailable")
    check("unconnected account -> no invented number",
          unavailable["summary"]["reach"] == 0 and unavailable["posts"] == []
          and "reason" in unavailable)
    check("unconnected account -> no network call", len(MOCK.log) == before)

    print("\n=== §9 organic results ===")
    res = asyncio.run(insights.organic_results(db, boost, acct, FROM, TO))
    check("source is meta", res["source"] == "meta")
    by = {p["platform"]: p for p in res["posts"]}
    check("two posts measured", len(res["posts"]) == 2, str(len(res["posts"])))

    ig = by.get("instagram", {})
    check("IG reach/likes/comments/shares/saved/views aggregated",
          (ig.get("reach"), ig.get("likes"), ig.get("comments"), ig.get("shares"),
           ig.get("saved"), ig.get("views")) == (1000, 40, 5, 3, 7, 2500), str(ig))
    check("IG permalink recorded", ig.get("url") == "https://instagram.com/p/abc/")

    fb = by.get("facebook", {})
    check("FB reactions/comments/shares aggregated",
          (fb.get("reactions"), fb.get("comments"), fb.get("shares")) == (11, 3, 4), str(fb))
    check("FB reach deliberately null (spec §9)",
          fb.get("reach") is None and any("Facebook reach" in n for n in res["notes"]))
    check("FB post id is page_prefixed", fb.get("post_id") == FB_ID)

    check("summary.measured == 2", res["summary"]["measured"] == 2)
    check("summary.posts == 2", res["summary"]["posts"] == 2)
    check("summary.reach == 1000 (IG only)", res["summary"]["reach"] == 1000,
          str(res["summary"]["reach"]))
    # interactions = IG(40+5+3+7) + FB(11+3+4) = 55 + 18 = 73
    check("summary.interactions == 73", res["summary"]["interactions"] == 73,
          str(res["summary"]["interactions"]))

    print("\n=== exact Graph paths / metrics (from the recorded log) ===")
    ig_media_calls = MOCK.find(path=f"/{IG_MEDIA}")
    check("GET /{ig_media_id}?fields=permalink",
          len(ig_media_calls) == 1 and ig_media_calls[0]["query"].get("fields") == "permalink"
          and ig_media_calls[0]["method"] == "GET", str(ig_media_calls))
    ig_ins = [e for e in MOCK.find(path=f"/{IG_MEDIA}/insights")
              if e["query"].get("metric") == "reach,likes,comments,shares,saved,views"]
    check("GET /{ig_media_id}/insights?metric=reach,likes,comments,shares,saved,views",
          len(ig_ins) == 1, str(MOCK.find(path=f"/{IG_MEDIA}/insights")))
    fb_post_calls = MOCK.find(path=f"/{FB_ID}")
    check("GET /{post_id}?fields=permalink_url,shares",
          len(fb_post_calls) == 1
          and fb_post_calls[0]["query"].get("fields") == "permalink_url,shares",
          str(fb_post_calls))
    fb_react = MOCK.find(path=f"/{FB_ID}/reactions")
    check("GET /{post_id}/reactions?summary=total_count",
          len(fb_react) == 1 and fb_react[0]["query"].get("summary") == "total_count")
    fb_comm = MOCK.find(path=f"/{FB_ID}/comments")
    check("GET /{post_id}/comments?filter=stream&limit=500",
          len(fb_comm) == 1 and fb_comm[0]["query"].get("filter") == "stream"
          and fb_comm[0]["query"].get("limit") == "500", str(fb_comm))

    print("\n=== a 500 on one post must not abort the run ===")
    bad = Post(boost_id=boost.id, day=3, kind="static", caption="bad",
               client_status="approved", publish_status="posted", publish_target="instagram",
               ig_media_id="BADMEDIA", publish_at="2026-11-04T10:00:00")
    db.add(bad)
    db.commit()
    import httpx  # noqa: F401
    MOCK.add_route(lambda e: e["path"] == "/BADMEDIA",
                   lambda e: (500, {"error": {"message": "boom"}}))
    res2 = asyncio.run(insights.organic_results(db, boost, acct, FROM, TO))
    check("run still returns source=meta after a 500", res2["source"] == "meta")
    check("two posts still measured", res2["summary"]["measured"] == 2,
          str(res2["summary"]["measured"]))
    check("the failing post is recorded, not silently dropped",
          len(res2["errors"]) == 1 and res2["errors"][0]["post_id"] == bad.id
          and "500" in res2["errors"][0]["error"], str(res2["errors"]))

    print("\n=== §10 ad numbers (substring street match) ===")
    adres = asyncio.run(insights.ad_numbers(db, boost, FROM, TO))
    check("source is meta", adres["source"] == "meta", str(adres.get("reason")))
    names = [c["campaign_name"] for c in adres["matched_campaigns"]]
    check("exactly one campaign matched (street substring)",
          len(names) == 1 and "123 main" in names[0].lower(), str(names))
    check("decoy campaign on another street is NOT included",
          all("456 oak" not in n.lower() for n in names), str(names))
    check("totals come from the matched campaign only",
          (adres["spend"], adres["impressions"], adres["reach"], adres["clicks"],
           adres["link_clicks"]) == (10, 5000, 3000, 4, 3), str(adres))
    check("derived cpc/ctr/frequency", adres["cpc"] == 2.5 and adres["ctr"] == 0.08
          and adres["frequency"] == 1.6667, str((adres["cpc"], adres["ctr"], adres["frequency"])))
    check("platform split facebook/instagram",
          adres["split"] == {"facebook": 2000, "instagram": 1000}, str(adres["split"]))

    ad_row = db.query(Ad).filter(Ad.boost_id == boost.id).first()
    check("reach written back onto the Ad row", ad_row.reach == 3000, str(ad_row.reach))

    totals_call = [e for e in MOCK.find(path="/act_123/insights")
                   if e["query"].get("breakdowns") is None]
    check("ad call uses level=campaign, time_range, spec fields, limit=100",
          len(totals_call) == 1
          and totals_call[0]["query"].get("level") == "campaign"
          and totals_call[0]["query"].get("limit") == "100"
          and totals_call[0]["query"].get("fields") == insights.AD_FIELDS
          and _json.loads(totals_call[0]["query"].get("time_range"))["since"] == FROM,
          str(totals_call))
    split_call = [e for e in MOCK.find(path="/act_123/insights")
                  if e["query"].get("breakdowns") == "publisher_platform"]
    check("split call uses fields=reach,campaign_name with publisher_platform breakdown",
          len(split_call) == 1
          and split_call[0]["query"].get("fields") == "reach,campaign_name",
          str(split_call))

    print("\n=== ad numbers when Meta is not connected ===")
    before = len(MOCK.log)
    # Point the boost at the tokenless account and re-run.
    boost.ad_account_id = no_tok.id
    db.commit()
    ad_unavail = asyncio.run(insights.ad_numbers(db, boost, FROM, TO))
    check("unconnected ad account -> source=unavailable",
          ad_unavail["source"] == "unavailable" and "reason" in ad_unavail
          and ad_unavail["spend"] is None, str(ad_unavail))
    check("unconnected ad account -> no network call", len(MOCK.log) == before)

    print("\n=== recorded Graph requests (proof) ===")
    for e in MOCK.log:
        keys = {k: e["query"][k] for k in ("fields", "metric", "summary", "filter", "limit",
                                           "level", "breakdowns") if k in e["query"]}
        print(f"  {e['method']:4} {e['path']}  {keys}")

    db.close()
    MOCK.stop()

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED: {FAILS}")
        sys.exit(1)
    print("ALL INSIGHTS TESTS PASSED")


if __name__ == "__main__":
    main()
