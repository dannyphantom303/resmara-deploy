"""Hermetic tests for app.services.ad_platforms.

Starts a local mock Graph API server (http.server in a thread on 127.0.0.1:0),
points the Meta client at it, and proves with real assertions that create_campaign
issues exactly 4 POSTs in the right order with the right paths, that ids are
threaded into the later payloads, that housing is a special ad category, that all
objects are PAUSED, that budget is in cents, that a 400 raises PlatformError with
no fake ids, and that simulated mode makes zero HTTP requests.

Run:  cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_ad_platforms.py
"""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

from app.core.config import settings
from app.services.ad_platforms import (
    MetaAdsClient,
    TikTokAdsClient,
    GoogleAdsClient,
    PlatformError,
    build_boost_configs,
    street_key,
    get_platform_client,
    is_simulated_account,
)

# ---------------------------------------------------------------------------
# Mock Graph server
# ---------------------------------------------------------------------------

REQUESTS = []          # every request the mock receives
FORCE_ERROR = {"on": False}
CANON = {              # the ids the mock hands back
    "campaign": "120210000001",
    "adset": "120210000002",
    "creative": "120210000003",
    "ad": "120210000004",
}


class MockGraphHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output clean
        pass

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"_raw": raw.decode("utf-8", "replace")}
        parsed = urlparse(self.path)
        entry = {
            "method": self.command,
            "path": parsed.path,
            "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
            "body": body,
        }
        REQUESTS.append(entry)
        return entry

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        entry = self._record()
        if FORCE_ERROR["on"]:
            self._send(400, {"error": {"message": "Invalid parameter",
                                       "type": "OAuthException", "code": 100}})
            return
        path = entry["path"]
        if path.endswith("/campaigns"):
            self._send(200, {"id": CANON["campaign"]})
        elif path.endswith("/adsets"):
            self._send(200, {"id": CANON["adset"]})
        elif path.endswith("/adcreatives"):
            self._send(200, {"id": CANON["creative"]})
        elif path.endswith("/ads"):
            self._send(200, {"id": CANON["ad"]})
        else:
            self._send(200, {"id": "120210000099", "success": True})

    def do_GET(self):
        entry = self._record()
        if entry["path"].startswith("/act_"):
            self._send(200, {"id": entry["path"].lstrip("/"), "account_id": "123456789",
                             "name": "Mock Account", "currency": "USD", "account_status": 1})
        else:
            self._send(200, {"id": entry["path"].lstrip("/"), "name": "Mock Campaign",
                             "status": "PAUSED", "effective_status": "PAUSED",
                             "objective": "OUTCOME_TRAFFIC"})


def start_server():
    server = HTTPServer(("127.0.0.1", 0), MockGraphHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ---------------------------------------------------------------------------
# Tiny assertion harness (prints one line per check)
# ---------------------------------------------------------------------------

PASSED = 0
FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}  {detail}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def real_meta_account():
    return SimpleNamespace(
        platform="meta", advertiser_id="123456789", access_token="EAABsbCS1iHgBO7real",
        budget=5000.0, currency="USD", is_active=True, page_id="111222333",
        ig_user_id="444555666", token_expires_at=None,
    )


def real_meta_account_with_prefix():
    """The shape Meta actually hands back: /me/adaccounts ids already carry act_."""
    return SimpleNamespace(
        platform="meta", advertiser_id="act_777888999", access_token="EAABsbCS1iHgBO7real",
        budget=5000.0, currency="USD", is_active=True, page_id="111222333",
        ig_user_id="444555666", token_expires_at=None,
    )


def test_boost():
    return SimpleNamespace(
        address="123 Main St, Austin TX 78701",
        ad_budget_usd=50.0,
        plan={"ad": {
            "primary_text": "Just listed! Stunning 4BR/3BA in Austin with a pool and updated kitchen. "
                            "Open house this weekend — schedule your private tour today!",
            "headline": "Stunning 4BR Austin Home",
            "description": "Open house Sat & Sun",
            "link": "https://resmara.example/listing/123",
            "cta_button": "Learn More",
            "objective": "OUTCOME_TRAFFIC",
        }},
        ad_brief={},
        brand_profile={"page_id": "111222333"},
        property_facts="4BR/3BA, 2400sqft, pool",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def main():
    global PASSED, FAILED
    settings.SIMULATE = False  # real-token accounts must go over the wire

    server, base_url = start_server()
    # Also prove the settings.GRAPH_API_BASE path works (one client uses it).
    settings.GRAPH_API_BASE = base_url
    print(f"Mock Graph server listening at {base_url}")

    acct = real_meta_account()
    boost = test_boost()

    # --- street_key + simulated-account detection -------------------------
    print("\n[street_key / sim detection]")
    check("street_key lowercases first two words", street_key("123 Main St, Austin TX") == "123 main",
          street_key("123 Main St, Austin TX"))
    check("street_key tolerates empty", street_key("") == "")
    check("real token is not simulated", is_simulated_account(acct) is False)
    check("'sim_token_prototype' is simulated",
          is_simulated_account(SimpleNamespace(access_token="sim_token_prototype")) is True)
    check("empty token is simulated",
          is_simulated_account(SimpleNamespace(access_token="")) is True)

    # --- build_boost_configs ---------------------------------------------
    print("\n[build_boost_configs]")
    configs = build_boost_configs(boost, page_id="111222333", budget_usd=50.0)
    camp = configs["campaign"]
    adset = configs["adset"]
    creative = configs["adcreative"]
    ad = configs["ad"]
    check("campaign name uses street key", camp["name"] == "123 main · Real Estate Boost", camp["name"])
    check("campaign objective from plan", camp["objective"] == "OUTCOME_TRAFFIC")
    check("campaign status PAUSED", camp["status"] == "PAUSED")
    check("special_ad_categories == ['HOUSING']", camp["special_ad_categories"] == ["HOUSING"],
          camp["special_ad_categories"])
    check("campaign daily_budget is cents", camp["daily_budget"] == 5000, camp["daily_budget"])
    check("adset billing_event IMPRESSIONS", adset["billing_event"] == "IMPRESSIONS")
    check("adset optimization_goal LINK_CLICKS", adset["optimization_goal"] == "LINK_CLICKS")
    check("adset status PAUSED", adset["status"] == "PAUSED")
    check("adset targeting age 18-65", adset["targeting"]["age_min"] == 18 and adset["targeting"]["age_max"] == 65)
    # CBO: the budget rides on the campaign. Sending it on both is refused by Meta with
    # "Can't Set Ad Set and Campaign Budget" (subcode 1885621).
    check("the ad set carries no budget of its own", "daily_budget" not in adset, str(adset.get("daily_budget")))
    # Meta 400s "Bid Amount Required For The Bid Strategy Provided" (subcode 1815857) when
    # an ad set names no bid strategy. Verified live: a HOUSING ad set is refused even with
    # LOWEST_COST_WITHOUT_CAP until bid_amount is present, and accepted with
    # LOWEST_COST_WITH_BID_CAP + bid_amount.
    check("adset names a bid strategy", adset.get("bid_strategy") == "LOWEST_COST_WITH_BID_CAP",
          str(adset.get("bid_strategy")))
    check("adset carries a bid cap in cents", isinstance(adset.get("bid_amount"), int) and adset["bid_amount"] > 0,
          str(adset.get("bid_amount")))
    check("ad status PAUSED", ad["status"] == "PAUSED")
    link_data = creative["object_story_spec"]["link_data"]
    check("creative message <= 125 chars", len(link_data["message"]) <= 125, len(link_data["message"]))
    check("creative headline <= 40 chars", len(link_data["name"]) <= 40, len(link_data["name"]))
    check("creative description <= 30 chars", len(link_data["description"]) <= 30, len(link_data["description"]))
    check("creative cta type LEARN_MORE", link_data["call_to_action"]["type"] == "LEARN_MORE")
    check("creative page_id threaded", creative["object_story_spec"]["page_id"] == "111222333")
    check("notes list is present", isinstance(configs["notes"], list) and len(configs["notes"]) > 0)

    # --- advertiser_id already carries the act_ prefix -------------------
    # Meta returns ad account ids as "act_<digits>" from /me/adaccounts, and that is what
    # gets stored. Prefixing again builds "act_act_123" -> Graph 400 "does not exist".
    print("\n[advertiser_id prefix normalisation]")
    prefixed = MetaAdsClient(real_meta_account_with_prefix())
    check("an id that already has act_ is not prefixed twice", prefixed._act_id == "777888999",
          prefixed._act_id)
    REQUESTS.clear()
    pc = MetaAdsClient(real_meta_account_with_prefix(), base_url=base_url)
    asyncio.run(pc.create_campaign(configs))
    paths2 = [r["path"].lstrip("/") for r in REQUESTS]
    check("  ...and the request path has exactly one act_", all(p.startswith("act_777888999/") for p in paths2),
          str(paths2))
    check("  ...with no act_act_ anywhere", not any("act_act_" in p for p in paths2), str(paths2))

    # --- create_campaign happy path --------------------------------------
    print("\n[create_campaign — real HTTP to mock]")
    REQUESTS.clear()
    client = MetaAdsClient(acct, base_url=base_url)
    result = asyncio.run(client.create_campaign(configs))

    paths = [r["path"].lstrip("/") for r in REQUESTS]
    print("  recorded POST paths:", paths)
    print("  recorded methods   :", [r["method"] for r in REQUESTS])
    expected = [
        "act_123456789/campaigns",
        "act_123456789/adsets",
        "act_123456789/adcreatives",
        "act_123456789/ads",
    ]
    check("exactly 4 requests", len(REQUESTS) == 4, len(REQUESTS))
    check("all requests are POST", all(r["method"] == "POST" for r in REQUESTS))
    check("paths in exact order", paths == expected, paths)
    check("result has campaign/adset/creative/ad",
          all(k in result for k in ("campaign", "adset", "creative", "ad")))
    check("result.simulated is False", result["simulated"] is False)
    check("campaign id surfaced", result["campaign"]["id"] == "120210000001")

    # threading: campaign_id -> adset, adset_id + creative_id -> ad
    adset_body = REQUESTS[1]["body"]
    ad_body = REQUESTS[3]["body"]
    check("adset body carries campaign_id", adset_body.get("campaign_id") == "120210000001", adset_body.get("campaign_id"))
    check("ad body carries adset_id", ad_body.get("adset_id") == "120210000002", ad_body.get("adset_id"))
    check("ad body carries creative.creative_id",
          ad_body.get("creative", {}).get("creative_id") == "120210000003", ad_body.get("creative"))
    check("adset body status PAUSED", adset_body.get("status") == "PAUSED")
    check("ad body status PAUSED", ad_body.get("status") == "PAUSED")
    check("campaign body status PAUSED", REQUESTS[0]["body"].get("status") == "PAUSED")
    check("campaign body daily_budget cents", REQUESTS[0]["body"].get("daily_budget") == 5000)
    check("campaign body special_ad_categories HOUSING",
          REQUESTS[0]["body"].get("special_ad_categories") == ["HOUSING"])
    check("adcreative message <= 125 chars on the wire",
          len(REQUESTS[2]["body"]["object_story_spec"]["link_data"]["message"]) <= 125)
    check("creative posted before ad (order)", paths.index("act_123456789/adcreatives") < paths.index("act_123456789/ads"))
    check("access_token sent as query param", REQUESTS[0]["query"].get("access_token") == acct.access_token)

    # --- settings.GRAPH_API_BASE path ------------------------------------
    print("\n[settings.GRAPH_API_BASE fallback]")
    REQUESTS.clear()
    settings_client = MetaAdsClient(acct)  # no base_url -> uses settings.graph_base
    status = asyncio.run(settings_client.get_campaign_status("120210000001"))
    check("get_campaign_status hit the mock", len(REQUESTS) == 1 and REQUESTS[0]["method"] == "GET", REQUESTS)
    check("get_campaign_status returned status", status.get("status") == "PAUSED", status)

    REQUESTS.clear()
    paused = asyncio.run(settings_client.pause_campaign("120210000001"))
    check("pause_campaign POSTed status=PAUSED",
          len(REQUESTS) == 1 and REQUESTS[0]["body"].get("status") == "PAUSED", REQUESTS)
    check("pause_campaign returned dict", isinstance(paused, dict))

    REQUESTS.clear()
    acct_info = asyncio.run(settings_client.get_ad_account("123456789"))
    check("get_ad_account GETs act_<id>",
          REQUESTS[0]["path"].lstrip("/") == "act_123456789" and "fields" in REQUESTS[0]["query"], REQUESTS)
    check("get_ad_account returned currency", acct_info.get("currency") == "USD")

    # --- error path: 400 -> PlatformError, no fake ids --------------------
    print("\n[error path — 400 from mock]")
    REQUESTS.clear()
    FORCE_ERROR["on"] = True
    raised = None
    try:
        asyncio.run(client.create_campaign(configs))
    except PlatformError as exc:
        raised = exc
    finally:
        FORCE_ERROR["on"] = False
    check("400 raised PlatformError", isinstance(raised, PlatformError), type(raised).__name__)
    if raised is not None:
        check("PlatformError carries status_code 400", raised.status_code == 400, raised.status_code)
        check("PlatformError carries the Graph error body",
              isinstance(raised.body, dict) and raised.body.get("error", {}).get("code") == 100, raised.body)
        check("PlatformError names the first failing path",
              raised.path == "act_123456789/campaigns", raised.path)
    check("no fake ids returned on failure", raised is not None)
    check("only the first POST was attempted before the 400", len(REQUESTS) == 1, len(REQUESTS))

    # --- simulated mode: ZERO http requests ------------------------------
    print("\n[simulated mode — zero http]")
    REQUESTS.clear()
    sim_acct = SimpleNamespace(
        platform="meta", advertiser_id="123456789", access_token="sim_token_prototype",
        budget=5000.0, currency="USD", is_active=True, page_id="p", ig_user_id="i",
        token_expires_at=None,
    )
    sim_client = MetaAdsClient(sim_acct, base_url=base_url)
    sim_result = asyncio.run(sim_client.create_campaign(configs))
    check("simulated result flagged", sim_result.get("simulated") is True, sim_result)
    check("simulated result carries ids",
          sim_result["campaign"]["id"].startswith("sim_") and sim_result["ad"]["id"].startswith("sim_"))
    check("simulated create_campaign made ZERO requests", len(REQUESTS) == 0, len(REQUESTS))

    asyncio.run(sim_client.get_campaign_status("x"))
    asyncio.run(sim_client.pause_campaign("x"))
    asyncio.run(sim_client.get_ad_account("x"))
    check("simulated status/pause/get made ZERO requests", len(REQUESTS) == 0, len(REQUESTS))

    # settings.SIMULATE alone forces simulated even with a real token
    REQUESTS.clear()
    settings.SIMULATE = True
    try:
        forced = asyncio.run(MetaAdsClient(acct, base_url=base_url).create_campaign(configs))
    finally:
        settings.SIMULATE = False
    check("settings.SIMULATE=True forces simulated", forced.get("simulated") is True)
    check("settings.SIMULATE=True made ZERO requests", len(REQUESTS) == 0, len(REQUESTS))

    # --- factory ----------------------------------------------------------
    print("\n[get_platform_client]")
    check("meta -> MetaAdsClient", isinstance(get_platform_client(acct), MetaAdsClient))
    check("tiktok -> TikTokAdsClient",
          isinstance(get_platform_client(SimpleNamespace(platform="tiktok")), TikTokAdsClient))
    check("google-ads -> GoogleAdsClient",
          isinstance(get_platform_client(SimpleNamespace(platform="google-ads")), GoogleAdsClient))
    try:
        get_platform_client(SimpleNamespace(platform="applovin"))
        bad = None
    except ValueError as exc:
        bad = exc
    check("unsupported platform raises ValueError", isinstance(bad, ValueError), bad)

    # --- tiktok / google are real clients, not stubs ----------------------
    print("\n[tiktok / google simulated short-circuit]")
    REQUESTS.clear()
    tt = asyncio.run(TikTokAdsClient(sim_acct, base_url=base_url).create_campaign(
        {"campaign": {}, "adgroup": {}, "ad": {}}))
    gg = asyncio.run(GoogleAdsClient(sim_acct, base_url=base_url).create_campaign(
        {"campaign": {}, "ad_group": {}, "ad_copy": {}}))
    check("tiktok simulated flagged", tt.get("simulated") is True)
    check("google simulated flagged", gg.get("simulated") is True)
    check("tiktok+google simulated made ZERO requests", len(REQUESTS) == 0, len(REQUESTS))

    server.shutdown()

    # --- summary ----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"{PASSED} passed, {FAILED} failed")
    if FAILED:
        print("SOME AD PLATFORM TESTS FAILED")
        sys.exit(1)
    print("ALL AD PLATFORM TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
