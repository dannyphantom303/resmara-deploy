"""Real ad-platform API clients for Resmara (Meta, TikTok, Google Ads).

Ported from the Creatify reverse-engineering reference
(``/Users/dan/tmg-fastapi/app/services/ad_platforms.py``). Mirrors how Creatify's
``create_and_launch_new_campaign`` endpoint stores OAuth tokens server-side and
then drives each platform's Marketing API to build the full object tree:

    Meta   POST act_<advertiser_id>/campaigns        -> campaign id
           POST act_<advertiser_id>/adsets           (campaign_id threaded in)
           POST act_<advertiser_id>/adcreatives      -> creative id
           POST act_<advertiser_id>/ads              (adset_id + creative_id threaded in)

Design rules that mirror the Creatify flow:
  * every object is created ``PAUSED`` — nothing spends money without a human;
  * real estate ads must carry ``special_ad_categories = ["HOUSING"]``;
  * daily budgets are sent to the Graph API in *cents*;
  * errors are never swallowed — a non-2xx response raises :class:`PlatformError`
    carrying the Graph error body, and no fabricated ids are ever returned.

Simulated mode (hermetic, no network): when ``settings.SIMULATE`` is true, or the
account's ``access_token`` is empty / starts with ``sim`` / ``demo`` / ``prototype``,
every method short-circuits and returns ``{"simulated": True, ...}`` payloads
without making a single HTTP request.
"""

from __future__ import annotations

import logging

import httpx
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.db.session import AdAccount

log = logging.getLogger("resmara.ad_platforms")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PlatformError(Exception):
    """Raised when a platform API call fails.

    Carries the raw platform error so callers can persist ``last_error`` and
    surface it to the operator. Never catches-and-continues silently.
    """

    def __init__(
        self,
        message: str,
        *,
        platform: str = "meta",
        status_code: Optional[int] = None,
        path: Optional[str] = None,
        body: Optional[dict] = None,
        partial: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.platform = platform
        self.status_code = status_code
        self.path = path
        self.body = body
        # Set when a multi-step create failed halfway: {"created": {...}, "deleted": [...]}.
        # A campaign with no ad underneath it is litter in the customer's ad account, and it
        # is what let six duplicate campaigns accumulate during the first live bring-up.
        self.partial = partial or {}

    @property
    def graph_error(self) -> Optional[dict]:
        """The Graph error object, if this failure carried one. Lets callers classify it."""
        if isinstance(self.body, dict) and isinstance(self.body.get("error"), dict):
            return self.body
        return None

    def graph_message(self) -> Optional[str]:
        """Pull the human-readable message out of a Meta Graph error body.

        Graph's bare ``message`` is often just "Invalid parameter"; the actionable text is
        in ``error_user_msg`` ("Choose a campaign to create this ad set.") and the numeric
        ``error_subcode`` is what Meta's docs and search results are keyed on, so carry
        both into the operator-facing error instead of dropping them.
        """
        if not isinstance(self.body, dict):
            return None
        err = self.body.get("error")
        if not isinstance(err, dict):
            return None
        parts = [str(err.get("message") or "").strip()]
        if err.get("error_user_title"):
            parts.append(str(err["error_user_title"]).strip())
        if err.get("error_user_msg"):
            parts.append(str(err["error_user_msg"]).strip())
        if err.get("error_subcode"):
            parts.append(f"subcode {err['error_subcode']}")
        return " — ".join(p for p in parts if p) or None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clip(value: Optional[str], limit: int) -> str:
    """Trim a string to ``limit`` characters (Meta rejects longer fields)."""
    return (value or "").strip()[:limit]


def _cents(usd: float) -> int:
    """USD dollars -> cents, as the Graph API expects integer minor units."""
    return int(round(float(usd) * 100))


def street_key(address: str) -> str:
    """Lowercase the first two words of an address.

    Doc 15 uses this key for campaign naming and matching (e.g.
    ``'123 Main St, Austin TX' -> '123 main'``).
    """
    words = (address or "").strip().split()
    return " ".join(words[:2]).lower()


_SIM_PREFIXES = ("sim", "demo", "prototype")


def is_simulated_account(ad_account) -> bool:
    """True when calls for this account must not hit the network."""
    if settings.SIMULATE:
        return True
    token = (getattr(ad_account, "access_token", "") or "").strip().lower()
    if not token:
        return True
    return token.startswith(_SIM_PREFIXES)


# ---------------------------------------------------------------------------
# Base client
# ---------------------------------------------------------------------------

class _BaseAdsClient:
    """Shared plumbing: token, advertiser id, timeout, simulated short-circuit."""

    def __init__(self, ad_account, *, timeout: int = 30):
        self.ad_account = ad_account
        self.access_token = getattr(ad_account, "access_token", None)
        self.advertiser_id = getattr(ad_account, "advertiser_id", None)
        self.timeout = timeout

    @property
    def simulated(self) -> bool:
        return is_simulated_account(self.ad_account)


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class MetaAdsClient(_BaseAdsClient):
    """Meta (Facebook) Marketing API client.

    OAuth scopes: pages_manage_ads, pages_read_engagement, pages_show_list,
    instagram_content_publish, instagram_basic, ads_management,
    business_management, pages_manage_metadata.

    ``base_url`` overrides ``settings.graph_base`` (tests point it at a local
    mock Graph server).
    """

    def __init__(self, ad_account, *, base_url: Optional[str] = None, timeout: int = 30):
        super().__init__(ad_account, timeout=timeout)
        self.base_url = (base_url or settings.graph_base).rstrip("/")

    @property
    def _act_id(self) -> str:
        """Bare numeric ad-account id.

        ``advertiser_id`` is stored exactly as Meta returns it from /me/adaccounts, i.e.
        already ``act_<digits>``. Prefixing that again builds ``act_act_123`` and Graph
        answers 400 "Object ... does not exist". Strip the prefix, then re-add it once.
        """
        return str(self.advertiser_id or "").removeprefix("act_")

    # -- low level ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def _post(self, path: str, data: dict) -> dict:
        url = self._url(path)
        params = {"access_token": self.access_token}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, params=params, json=data)
        return self._handle(resp, path)

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = self._url(path)
        query = {"access_token": self.access_token}
        if params:
            query.update(params)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=query)
        return self._handle(resp, path)

    async def _delete(self, object_id: str) -> dict:
        """DELETE an object by id. Used to roll back a half-created campaign chain."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.delete(self._url(f"/{object_id}"),
                                       params={"access_token": self.access_token})
        return self._handle(resp, f"/{object_id}")

    def _handle(self, resp: httpx.Response, path: str) -> dict:
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {"error": {"message": resp.text}}
            err = PlatformError(
                f"Meta Graph {resp.status_code} on {path}",
                platform="meta",
                status_code=resp.status_code,
                path=path,
                body=body,
            )
            detail = err.graph_message()
            if detail:
                err.args = (f"Meta Graph {resp.status_code} on {path}: {detail}",)
            raise err
        return resp.json()

    # -- public API --------------------------------------------------------

    async def create_campaign(self, configs: dict) -> dict:
        """Create campaign -> adset -> adcreative -> ad, in that order.

        Mirrors Creatify's ``meta_custom_configs`` structure. ``configs`` may
        carry an ``ad`` key (as produced by :func:`build_boost_configs`); if it
        does not, a minimal paused ad is derived from the campaign name.
        """
        if self.simulated:
            return {
                "campaign": {"id": "sim_meta_campaign_001"},
                "adset": {"id": "sim_meta_adset_001"},
                "creative": {"id": "sim_meta_creative_001"},
                "ad": {"id": "sim_meta_ad_001"},
                "simulated": True,
            }

        campaign_data = dict(configs.get("campaign") or {})
        adset_data = dict(configs.get("adset") or {})
        adcreative_data = dict(configs.get("adcreative") or {})
        ad_data = dict(configs.get("ad") or {})
        ad_data.setdefault("name", campaign_data.get("name", "Resmara Ad"))
        ad_data.setdefault("status", "PAUSED")

        base = f"act_{self._act_id}"
        created: dict = {}

        try:
            # 1. Campaign
            campaign_resp = await self._post(f"{base}/campaigns", campaign_data)
            campaign_id = campaign_resp.get("id")
            if not campaign_id:
                raise PlatformError(
                    "Meta did not return a campaign id", platform="meta",
                    path=f"{base}/campaigns", body=campaign_resp,
                )
            created["campaign"] = campaign_id

            # 2. Ad set (threaded under the campaign)
            adset_data["campaign_id"] = campaign_id
            adset_resp = await self._post(f"{base}/adsets", adset_data)
            adset_id = adset_resp.get("id")
            if not adset_id:
                raise PlatformError(
                    "Meta did not return an adset id", platform="meta",
                    path=f"{base}/adsets", body=adset_resp,
                )
            created["adset"] = adset_id

            # 3. Ad creative
            creative_resp = await self._post(f"{base}/adcreatives", adcreative_data)
            creative_id = creative_resp.get("id")
            if not creative_id:
                raise PlatformError(
                    "Meta did not return an adcreative id", platform="meta",
                    path=f"{base}/adcreatives", body=creative_resp,
                )
            created["creative"] = creative_id

            # 4. Ad (threaded under the ad set + creative)
            ad_data["adset_id"] = adset_id
            ad_data["creative"] = {"creative_id": creative_id}
            ad_resp = await self._post(f"{base}/ads", ad_data)
            created["ad"] = ad_resp.get("id")

        except Exception as exc:  # noqa: BLE001 - rolled back and re-raised below
            # A campaign with no ad under it is litter in the customer's ad account and, on
            # a retry, becomes a duplicate: that is exactly how six orphan campaigns piled up
            # during the first live bring-up. Delete what this call created, deepest first,
            # then re-raise carrying the ids so the caller can report what happened.
            removed = []
            for kind in ("ad", "creative", "adset", "campaign"):
                object_id = created.get(kind)
                if not object_id:
                    continue
                try:
                    await self._delete(object_id)
                    removed.append(f"{kind}:{object_id}")
                except Exception as cleanup_exc:  # noqa: BLE001 - must not mask the real error
                    log.warning("could not roll back %s %s: %s", kind, object_id, cleanup_exc)
            partial = {"created": created, "deleted": removed}
            if isinstance(exc, PlatformError):
                exc.partial = partial
                raise
            raise PlatformError(
                f"Meta campaign build failed: {exc}", platform="meta",
                path=base, partial=partial,
            ) from exc

        return {
            "campaign": campaign_resp,
            "adset": adset_resp,
            "creative": creative_resp,
            "ad": ad_resp,
            "simulated": False,
        }

    async def get_campaign_status(
        self,
        campaign_id: str,
        fields: str = "id,name,status,effective_status,objective",
    ) -> dict:
        """GET a campaign's status/effective_status (Creator pause/live mirror)."""
        if self.simulated:
            return {
                "id": f"sim_{campaign_id}", "name": "Simulated Campaign",
                "status": "PAUSED", "effective_status": "PAUSED",
                "objective": "OUTCOME_TRAFFIC", "simulated": True,
            }
        return await self._get(campaign_id, {"fields": fields})

    async def pause_campaign(self, campaign_id: str) -> dict:
        """POST status=PAUSED to a campaign (the kill switch)."""
        if self.simulated:
            return {"id": f"sim_{campaign_id}", "status": "PAUSED", "simulated": True}
        return await self._post(campaign_id, {"status": "PAUSED"})

    async def get_ad_account(self, advertiser_id: str) -> dict:
        """GET an ad account's metadata (name, currency, account_status)."""
        if self.simulated:
            return {
                "id": f"act_{self._act_id}", "account_id": self._act_id,
                "name": "Simulated Account", "currency": "USD",
                "account_status": 1, "simulated": True,
            }
        return await self._get(
            f"act_{self._act_id}",
            {"fields": "id,account_id,name,currency,account_status"},
        )


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

# Cents. What Meta accepts as a bid cap for a US housing LINK_CLICKS ad set; verified
# live, and overridable per boost via ad["bid_amount"].
_DEFAULT_BID_CAP_CENTS = 300

_CAMPAIGN_OBJECTIVE_DEFAULT = "OUTCOME_TRAFFIC"


def build_boost_configs(
    boost,
    plan: Optional[dict] = None,
    page_id: Optional[str] = None,
    budget_usd: Optional[float] = None,
) -> dict:
    """Build the real Meta payload tree from a Boost and its plan.

    ``plan['ad']`` is preferred when present, else ``boost.ad_brief``. Returns
    ``{campaign, adset, adcreative, ad, notes}``. Every object is ``PAUSED`` and
    ``special_ad_categories = ['HOUSING']`` is always set (real estate is a
    special ad category). ``notes`` lists every field that had to be defaulted.
    """
    notes: list[str] = []
    plan = plan if plan is not None else (getattr(boost, "plan", None) or {})

    ad: dict = {}
    if isinstance(plan, dict) and plan.get("ad"):
        ad = dict(plan["ad"])
    elif isinstance(getattr(boost, "ad_brief", None), dict) and boost.ad_brief:
        ad = dict(boost.ad_brief)
    elif isinstance(plan, dict) and plan:
        # A plan without an explicit 'ad' block: use it as the ad source.
        ad = dict(plan)
    else:
        notes.append("no plan/ad_brief on the boost — ad copy fields defaulted")

    street = street_key(getattr(boost, "address", ""))
    name_base = street or "resmara"

    # Budget (dollars -> cents). Nothing spends without a human: still PAUSED.
    if budget_usd is None:
        budget_usd = getattr(boost, "ad_budget_usd", None)
    if budget_usd is None:
        budget_usd = 50.0
        notes.append("budget_usd defaulted to 50.0")
    daily_budget_cents = _cents(budget_usd)

    # --- Campaign ---
    objective = ad.get("objective")
    if not objective:
        objective = _CAMPAIGN_OBJECTIVE_DEFAULT
        notes.append(f"campaign.objective defaulted to {_CAMPAIGN_OBJECTIVE_DEFAULT}")
    campaign = {
        "name": f"{name_base} · Real Estate Boost",
        "objective": objective,
        "status": "PAUSED",
        "special_ad_categories": ["HOUSING"],
        "daily_budget": daily_budget_cents,
    }
    notes.append("all objects forced to status=PAUSED (human must launch)")

    # --- Ad set ---
    geo = ad.get("geo_locations")
    if not geo:
        geo = {"countries": ["US"]}
        notes.append("adset.targeting.geo_locations defaulted to US")
    targeting = {
        "geo_locations": geo,
        "age_min": 18,
        "age_max": 65,
    }
    # Meta rejects an ad set that names no bid strategy: "Bid Amount Required For The Bid
    # Strategy Provided" (subcode 1815857). Verified live against a real HOUSING ad set:
    # even LOWEST_COST_WITHOUT_CAP is refused until bid_amount is supplied, while
    # LOWEST_COST_WITH_BID_CAP + bid_amount is accepted — so always send a bid cap, which
    # is also what Meta's special-ad-category guidance expects for housing ads.
    bid_strategy = ad.get("bid_strategy") or "LOWEST_COST_WITH_BID_CAP"
    if not ad.get("bid_strategy"):
        notes.append("adset.bid_strategy defaulted to LOWEST_COST_WITH_BID_CAP")
    bid_amount = ad.get("bid_amount")
    if bid_amount is None:
        bid_amount = _DEFAULT_BID_CAP_CENTS
        notes.append(f"adset.bid_amount defaulted to {_DEFAULT_BID_CAP_CENTS} cents")
    bid_amount = int(bid_amount)

    adset = {
        "name": ad.get("adset_name") or f"{name_base} · Targeting",
        "campaign_id": None,  # filled by MetaAdsClient.create_campaign()
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LINK_CLICKS",
        "bid_strategy": bid_strategy,
        "bid_amount": bid_amount,
        "targeting": targeting,
        # Budget lives on the campaign (CBO). Sending it here as well is refused with
        # "Can't Set Ad Set and Campaign Budget" (subcode 1885621).
        "status": "PAUSED",
    }
    notes.append("daily budget set on the campaign (CBO); the ad set carries no budget")
    notes.append("adset.campaign_id filled by MetaAdsClient.create_campaign()")

    # --- Ad creative ---
    resolved_page = (
        page_id
        or ad.get("page_id")
        or (getattr(boost, "brand_profile", None) or {}).get("page_id")
        or settings.META_PAGE_ID
        or ""
    )
    if not resolved_page:
        notes.append("adcreative.object_story_spec.page_id is empty (set META_PAGE_ID)")

    link = ad.get("link") or ad.get("landing_page_url")
    if not link:
        link = settings.PUBLIC_BASE_URL
        notes.append("adcreative.link defaulted to settings.PUBLIC_BASE_URL")

    primary_text = ad.get("primary_text") or ad.get("message") or ad.get("caption")
    if primary_text:
        primary_text = _clip(primary_text, 125)
    else:
        primary_text = ""
        notes.append("adcreative.message empty — no primary_text on the plan")

    headline = ad.get("headline") or ad.get("title")
    if headline:
        headline = _clip(headline, 40)
    else:
        headline = _clip(getattr(boost, "address", ""), 40)
        notes.append("adcreative.name defaulted to the street address")

    description = _clip(ad.get("description") or "", 30)
    if not ad.get("description"):
        notes.append("adcreative.description empty")

    cta = ad.get("cta_button") or ad.get("cta") or "LEARN_MORE"
    cta_type = str(cta).strip().replace(" ", "_").upper()
    if not (ad.get("cta_button") or ad.get("cta")):
        notes.append("adcreative call_to_action.type defaulted to LEARN_MORE")

    adcreative = {
        "name": f"{name_base} · Creative",
        "object_story_spec": {
            "page_id": resolved_page,
            "link_data": {
                "message": primary_text,
                "name": headline,
                "description": description,
                "link": link,
                "call_to_action": {"type": cta_type},
            },
        },
    }

    # --- Ad ---
    ad_payload = {
        "name": f"{name_base} · Ad",
        "status": "PAUSED",
    }

    return {
        "campaign": campaign,
        "adset": adset,
        "adcreative": adcreative,
        "ad": ad_payload,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------

class TikTokAdsClient(_BaseAdsClient):
    """TikTok for Business API client.

    OAuth scopes include: advertiser_management, ad_management, etc.
    Mirrors Creatify's ``tiktok_custom_configs`` tree
    (campaign -> adgroup -> ad).
    """

    def __init__(self, ad_account, *, base_url: Optional[str] = None, timeout: int = 30):
        super().__init__(ad_account, timeout=timeout)
        self.base_url = (
            base_url or "https://business-api.tiktok.com/open_api/v1.2"
        ).rstrip("/")

    def _headers(self) -> dict:
        return {"Access-Token": self.access_token, "Content-Type": "application/json"}

    async def _post(self, path: str, data: dict) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=data)
        return self._handle(resp, path)

    def _handle(self, resp: httpx.Response, path: str) -> dict:
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {"message": resp.text}
            raise PlatformError(
                f"TikTok API {resp.status_code} on {path}",
                platform="tiktok", status_code=resp.status_code, path=path, body=body,
            )
        return resp.json()

    async def create_campaign(self, configs: dict) -> dict:
        """Create a TikTok campaign -> ad group -> ad."""
        if self.simulated:
            return {
                "campaign": {"data": {"campaign_id": "sim_tiktok_campaign_001"}},
                "adgroup": {"data": {"adgroup_id": "sim_tiktok_adgroup_001"}},
                "ad": {"data": {"ad_id": "sim_tiktok_ad_001"}},
                "simulated": True,
            }

        results: dict = {}
        campaign_data = dict(configs.get("campaign") or {})
        adgroup_data = dict(configs.get("adgroup") or {})
        ad_data = dict(configs.get("ad") or {})

        results["campaign"] = await self._post(
            "advertiser/campaign/create/",
            {"advertiser_id": self.advertiser_id, **campaign_data},
        )
        campaign_id = results["campaign"].get("data", {}).get("campaign_id")
        if not campaign_id:
            raise PlatformError(
                "TikTok did not return a campaign id", platform="tiktok",
                path="advertiser/campaign/create/", body=results["campaign"],
            )

        adgroup_data["campaign_id"] = campaign_id
        adgroup_data["advertiser_id"] = self.advertiser_id
        results["adgroup"] = await self._post("advertiser/adgroup/create/", adgroup_data)
        adgroup_id = results["adgroup"].get("data", {}).get("adgroup_id")
        if not adgroup_id:
            raise PlatformError(
                "TikTok did not return an adgroup id", platform="tiktok",
                path="advertiser/adgroup/create/", body=results["adgroup"],
            )

        ad_data["advertiser_id"] = self.advertiser_id
        ad_data["adgroup_id"] = adgroup_id
        results["ad"] = await self._post("advertiser/ad/create/", ad_data)
        results["simulated"] = False
        return results


# ---------------------------------------------------------------------------
# Google Ads
# ---------------------------------------------------------------------------

class GoogleAdsClient(_BaseAdsClient):
    """Google Ads API client (REST).

    OAuth scope: https://www.googleapis.com/auth/adwords — uses the stored
    refresh_token to mint access tokens. Mirrors Creatify's
    ``google_custom_configs`` tree (campaign -> ad group -> ad).
    """

    def __init__(self, ad_account, *, base_url: Optional[str] = None, timeout: int = 30):
        super().__init__(ad_account, timeout=timeout)
        self.base_url = (base_url or "https://googleads.googleapis.com/v20").rstrip("/")
        self.customer_id = getattr(ad_account, "advertiser_id", None)
        self.refresh_token = getattr(ad_account, "refresh_token", None)

    async def _get_access_token(self) -> str:
        """Return a valid access token, refreshing it if expired."""
        expires = getattr(self.ad_account, "token_expires_at", None)
        if self.access_token and expires and datetime.utcnow() < expires:
            return self.access_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {"error": resp.text}
            raise PlatformError(
                "Google Ads token refresh failed", platform="google-ads",
                status_code=resp.status_code, path="oauth2/token", body=body,
            )
        token_data = resp.json()
        self.access_token = token_data["access_token"]
        if "expires_in" in token_data:
            self.ad_account.token_expires_at = datetime.utcnow() + timedelta(
                seconds=token_data["expires_in"]
            )
        return self.access_token

    async def _mutate(self, resource: str, create: dict, headers: dict) -> dict:
        url = f"{self.base_url}/customers/{self.customer_id}/{resource}:mutate"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json={"operations": [{"create": create}]})
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {"error": resp.text}
            raise PlatformError(
                f"Google Ads API {resp.status_code} on {resource}:mutate",
                platform="google-ads", status_code=resp.status_code,
                path=resource, body=body,
            )
        return resp.json()

    async def create_campaign(self, configs: dict) -> dict:
        """Create a Google Ads campaign -> ad group -> adGroupAd."""
        if self.simulated:
            return {
                "campaign": {"results": [{"resourceName": f"customers/{self.customer_id}/campaigns/sim_001"}]},
                "ad_group": {"results": [{"resourceName": f"customers/{self.customer_id}/adGroups/sim_001"}]},
                "ad": {"results": [{"resourceName": f"customers/{self.customer_id}/adGroupAds/sim_001"}]},
                "simulated": True,
            }

        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        results = {
            "campaign": await self._mutate("campaigns", dict(configs.get("campaign") or {}), headers),
            "ad_group": await self._mutate("adGroups", dict(configs.get("ad_group") or {}), headers),
            "ad": await self._mutate("adGroupAds", dict(configs.get("ad_copy") or {}), headers),
        }
        results["simulated"] = False
        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_platform_client(ad_account) -> _BaseAdsClient:
    """Return the right platform client for an AdAccount.

    Raises ValueError for an unsupported platform.
    """
    clients = {
        "meta": MetaAdsClient,
        "tiktok": TikTokAdsClient,
        "google-ads": GoogleAdsClient,
    }
    platform = getattr(ad_account, "platform", None)
    client_cls = clients.get(platform)
    if not client_cls:
        raise ValueError(f"Unsupported platform: {platform}")
    return client_cls(ad_account)
