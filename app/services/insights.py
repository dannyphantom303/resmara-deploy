"""Real Meta Graph metrics for Resmara.

Extracted verbatim from the handoff spec, Make scenario extract §9
("Boost \u00b7 Results": organic post metrics) and §10 ("Boost \u00b7 Ad numbers": paid
metrics).

Hard rule: this module NEVER invents a number. When Meta is not connected, a
call fails, or a metric simply is not fetched by the spec, the source is
reported as ``unavailable`` (with a reason) or the field is left as ``None`` /
0 \u2014 never a made-up figure. The old placeholder formula ``1250 * day`` lives
nowhere in this path.

Call shapes (spec §9 / §10):

  IG organic   GET /{ig_media_id}?fields=permalink
               GET /{ig_media_id}/insights?metric=reach,likes,comments,shares,saved,views
  FB organic   GET /{page_post_id}?fields=permalink_url,shares
               GET /{page_post_id}/reactions?summary=total_count
               GET /{page_post_id}/comments?filter=stream&limit=500
  Ad numbers   GET /act_<advertiser_id>/insights?level=campaign
                   &time_range={"since":from,"until":to}
                   &fields=spend,impressions,reach,clicks,inline_link_clicks,cpc,ctr,
                           frequency,campaign_name,campaign_id&limit=100
               GET /act_<advertiser_id>/insights?level=campaign
                   &time_range={...}&fields=reach,campaign_name
                   &breakdowns=publisher_platform&limit=100
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.db.session import AdAccount, Ad, Post

log = logging.getLogger("resmara.insights")

GRAPH_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# street key (spec §10 step 2)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - exercised implicitly
    # ad_platforms.py is written in parallel by another teammate; if it grows a
    # shared street_key(), use theirs so both modules agree on one definition.
    from app.services.ad_platforms import street_key  # type: ignore
except Exception:  # noqa: BLE001 - not defined yet, fall back to our own

    def street_key(address: Optional[str]) -> str:
        """Lowercase first two words of an address.

        ``"123 Main St, Austin TX"`` -> ``"123 main"``. Make matched campaigns
        with a *substring* test on ``lower(campaign_name)`` (spec §10), so this
        also matches ``"123 maine ..."`` \u2014 that is the documented behaviour,
        it is not an exact name match.
        """
        words = (address or "").strip().split()
        return " ".join(words[:2]).lower()


# ---------------------------------------------------------------------------
# configuration / availability
# ---------------------------------------------------------------------------
def _usable_token(ad_account: Any) -> Optional[str]:
    """Return a real Meta token, or None.

    A blank token or a ``sim...``/``demo...`` placeholder is NOT a usable Meta
    token, so the caller is told honestly that Meta is not connected.
    """
    token = (getattr(ad_account, "access_token", None) or "").strip()
    if not token:
        return None
    low = token.lower()
    if low.startswith("sim") or low.startswith("demo"):
        return None
    return token


def configured(ad_account: Any) -> Dict[str, Any]:
    """Return ``{ok, reason, token?}`` \u2014 a usable-token check for the caller."""
    if ad_account is None:
        return {"ok": False, "reason": "No Meta ad account connected"}
    token = _usable_token(ad_account)
    if token is None:
        return {
            "ok": False,
            "reason": "Meta not connected yet (no usable access token)",
        }
    return {"ok": True, "token": token}


async def organic_available(ad_account: Any = None) -> bool:
    """True when organic post metrics can be fetched for this account."""
    return configured(ad_account)["ok"]


async def ad_available(ad_account: Any = None) -> bool:
    """True when paid metrics can be fetched for this account."""
    return configured(ad_account)["ok"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _url(path: str) -> str:
    # Build absolute URLs rather than a base_url: graph_base carries the API
    # version (/v19.0), which an RFC-3986 join on a leading "/" would drop.
    return settings.graph_base.rstrip("/") + "/" + path.lstrip("/")


def _num(value: Any) -> Any:
    if value is None:
        return 0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    return int(f) if f.is_integer() else f


def _insights_values(payload: Any) -> Dict[str, Any]:
    """Flatten a Graph insights payload into ``{metric: value}``."""
    out: Dict[str, Any] = {}
    for entry in (payload or {}).get("data", []) or []:
        name = entry.get("name")
        if not name:
            continue
        if "total_value" in entry and isinstance(entry["total_value"], dict):
            out[name] = entry["total_value"].get("value")
        else:
            values = entry.get("values") or []
            if values:
                out[name] = sum((v or {}).get("value", 0) for v in values)
            else:
                out[name] = None
    return out


async def _count_comments(client: httpx.AsyncClient, post_id: str, token: str,
                          max_pages: int = 20) -> int:
    """GET /{post_id}/comments?filter=stream&limit=500 and count the ids."""
    count = 0
    url: Optional[str] = _url(f"/{post_id}/comments")
    params: Optional[Dict[str, Any]] = {
        "filter": "stream", "limit": 500, "access_token": token,
    }
    pages = 0
    while url and pages < max_pages:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json() or {}
        count += len(payload.get("data") or [])
        pages += 1
        nxt = (payload.get("paging") or {}).get("next")
        if nxt:
            url = nxt  # absolute URL; already carries the access token
            params = None
        else:
            url = None
    return count


async def _organic_ig(client: httpx.AsyncClient, post: Post, token: str) -> Dict[str, Any]:
    media_id = post.ig_media_id
    resp = await client.get(_url(f"/{media_id}"),
                            params={"fields": "permalink", "access_token": token})
    resp.raise_for_status()
    permalink = (resp.json() or {}).get("permalink")

    resp2 = await client.get(
        _url(f"/{media_id}/insights"),
        params={"metric": "reach,likes,comments,shares,saved,views", "access_token": token},
    )
    resp2.raise_for_status()
    values = _insights_values(resp2.json())
    return {
        "post_id": media_id,
        "db_id": post.id,
        "day": post.day,
        "platform": "instagram",
        "url": permalink,
        "reach": values.get("reach"),
        "likes": values.get("likes"),
        "comments": values.get("comments"),
        "shares": values.get("shares"),
        "saved": values.get("saved"),
        "views": values.get("views"),
        "reactions": None,
    }


async def _organic_fb(client: httpx.AsyncClient, post: Post, token: str,
                      page_id: str) -> Dict[str, Any]:
    ref = post.fb_post_id
    # spec §9: post id is ref if it contains "_", else "<page>_<ref>".
    post_id = ref if "_" in ref else f"{page_id}_{ref}"

    resp = await client.get(_url(f"/{post_id}"),
                            params={"fields": "permalink_url,shares", "access_token": token})
    resp.raise_for_status()
    data = resp.json() or {}
    permalink = data.get("permalink_url")
    shares: Any = None
    if isinstance(data.get("shares"), dict):
        shares = data["shares"].get("count")
    elif isinstance(data.get("shares"), int):
        shares = data["shares"]

    resp2 = await client.get(_url(f"/{post_id}/reactions"),
                             params={"summary": "total_count", "access_token": token})
    resp2.raise_for_status()
    reactions = ((resp2.json() or {}).get("summary") or {}).get("total_count")

    comments = await _count_comments(client, post_id, token)

    # Facebook reach / impressions are deliberately NOT fetched (spec §9).
    return {
        "post_id": post_id,
        "db_id": post.id,
        "day": post.day,
        "platform": "facebook",
        "url": permalink,
        "reach": None,
        "likes": None,
        "comments": comments,
        "shares": shares,
        "saved": None,
        "views": None,
        "reactions": reactions,
    }


def _fb_page_id(ad_account: Any) -> str:
    return (getattr(ad_account, "page_id", None) or settings.META_PAGE_ID or "").strip()


# ---------------------------------------------------------------------------
# §9 organic post metrics
# ---------------------------------------------------------------------------
async def organic_results(db, boost, ad_account, from_iso: str, to_iso: str) -> Dict[str, Any]:
    """Per-post organic metrics for a boost's posted posts in [from, to)."""
    if ad_account is None and getattr(boost, "ad_account_id", None):
        ad_account = db.query(AdAccount).filter(AdAccount.id == boost.ad_account_id).first()

    result: Dict[str, Any] = {
        "source": "unavailable",
        "period": {"from": from_iso, "to": to_iso},
        "posts": [],
        "summary": {"measured": 0, "posts": 0, "reach": 0, "interactions": 0},
        "errors": [],
        "notes": [
            "Facebook reach/impressions are deliberately not fetched (spec §9); "
            "only reactions, comments and shares are read for Facebook."
        ],
    }

    conf = configured(ad_account)
    if not conf["ok"]:
        result["reason"] = conf["reason"]
        return result

    token = conf["token"]
    page_id = _fb_page_id(ad_account)

    posted = (
        db.query(Post)
        .filter(Post.boost_id == boost.id, Post.publish_status == "posted")
        .all()
    )
    in_period = [p for p in posted if p.publish_at and from_iso <= p.publish_at < to_iso]
    result["summary"]["posts"] = len(in_period)

    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    measured = 0
    total_reach = 0
    total_interactions = 0

    async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
        for post in in_period:
            try:
                if post.ig_media_id:
                    row = await _organic_ig(client, post, token)
                elif post.fb_post_id:
                    row = await _organic_fb(client, post, token, page_id)
                else:
                    errors.append({"post_id": post.id,
                                   "error": "marked posted but has no fb/ig id"})
                    continue
                rows.append(row)
                measured += 1
                total_reach += row.get("reach") or 0
                total_interactions += (
                    (row.get("likes") or 0)
                    + (row.get("comments") or 0)
                    + (row.get("shares") or 0)
                    + (row.get("reactions") or 0)
                    + (row.get("saved") or 0)
                )
            except Exception as exc:  # one failing post must not kill the run
                errors.append({"post_id": post.id, "error": str(exc)})

    result["source"] = "meta"
    result["posts"] = rows
    result["errors"] = errors
    result["summary"]["measured"] = measured
    result["summary"]["reach"] = total_reach
    result["summary"]["interactions"] = total_interactions
    return result


# ---------------------------------------------------------------------------
# §10 paid ad numbers
# ---------------------------------------------------------------------------
AD_FIELDS = ("spend,impressions,reach,clicks,inline_link_clicks,cpc,ctr,"
             "frequency,campaign_name,campaign_id")


async def ad_numbers(db, boost, from_iso: str, to_iso: str) -> Dict[str, Any]:
    """Campaign-level paid metrics for a boost, matched by street substring."""
    out: Dict[str, Any] = {
        "source": "unavailable",
        "matched_campaigns": [],
        "spend": None,
        "impressions": None,
        "reach": None,
        "clicks": None,
        "link_clicks": None,
        "cpc": None,
        "ctr": None,
        "frequency": None,
        "split": {"facebook": 0, "instagram": 0},
    }

    ad_account = None
    if getattr(boost, "ad_account_id", None):
        ad_account = db.query(AdAccount).filter(AdAccount.id == boost.ad_account_id).first()

    conf = configured(ad_account)
    if not conf["ok"]:
        out["reason"] = conf["reason"]
        return out

    adv = (ad_account.advertiser_id or "").strip()
    if not adv:
        out["reason"] = "Ad account has no advertiser id (act_...)"
        return out
    if not adv.startswith("act_"):
        adv = "act_" + adv
    token = conf["token"]

    key = street_key(boost.address)
    time_range = json.dumps({"since": from_iso, "until": to_iso})

    matched: List[Dict[str, Any]] = []
    split = {"facebook": 0, "instagram": 0}
    try:
        async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
            resp = await client.get(_url(f"/{adv}/insights"), params={
                "level": "campaign",
                "time_range": time_range,
                "fields": AD_FIELDS,
                "limit": 100,
                "access_token": token,
            })
            resp.raise_for_status()
            campaigns = (resp.json() or {}).get("data") or []

            # Spec §10: match is lower(campaign_name) CONTAINS the street key.
            # It is a SUBSTRING match, not an exact name match.
            matched = [c for c in campaigns
                       if key and key in (c.get("campaign_name") or "").lower()]

            resp2 = await client.get(_url(f"/{adv}/insights"), params={
                "level": "campaign",
                "time_range": time_range,
                "fields": "reach,campaign_name",
                "breakdowns": "publisher_platform",
                "limit": 100,
                "access_token": token,
            })
            resp2.raise_for_status()
            for c in (resp2.json() or {}).get("data") or []:
                if key and key in (c.get("campaign_name") or "").lower():
                    platform = (c.get("publisher_platform") or "").lower()
                    if platform in split:
                        split[platform] += _num(c.get("reach"))
    except Exception as exc:
        out["reason"] = f"Meta ad insights call failed: {exc}"
        return out

    def _sum(field: str) -> Any:
        return sum(_num(c.get(field)) for c in matched)

    spend = _sum("spend")
    impressions = _sum("impressions")
    reach = _sum("reach")
    clicks = _sum("clicks")
    link_clicks = _sum("inline_link_clicks")

    # Ratios are derived from the summed totals (summing per-campaign ratios
    # would be meaningless).
    cpc = round(spend / clicks, 4) if clicks else None
    ctr = round(clicks / impressions * 100, 4) if impressions else None
    frequency = round(impressions / reach, 4) if reach else None

    out.update({
        "source": "meta",
        "matched_campaigns": [
            {
                "campaign_id": c.get("campaign_id"),
                "campaign_name": c.get("campaign_name"),
                "spend": _num(c.get("spend")),
                "impressions": _num(c.get("impressions")),
                "reach": _num(c.get("reach")),
                "clicks": _num(c.get("clicks")),
                "link_clicks": _num(c.get("inline_link_clicks")),
            }
            for c in matched
        ],
        "spend": spend,
        "impressions": impressions,
        "reach": reach,
        "clicks": clicks,
        "link_clicks": link_clicks,
        "cpc": cpc,
        "ctr": ctr,
        "frequency": frequency,
        "split": split,
    })

    # Write the campaign reach back onto the boost's Ad row(s). Never crash if
    # there is no Ad row.
    try:
        for ad in db.query(Ad).filter(Ad.boost_id == boost.id).all():
            ad.reach = int(reach) if reach is not None else ad.reach
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning("could not write ad reach back for boost %s: %s", boost.id, exc)

    return out
