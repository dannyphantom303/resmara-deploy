"""The launch gate + Meta campaign creation, shared by every launch entrypoint.

Both POST /api/boosts/{id}/launch and the legacy POST /api/resmara/launch call this, so
there is exactly one place that decides whether a campaign may spend money.

Mirrors the Creatify ad flow the dashboard was reverse-engineered from:
  layer 1 - budget precheck (subscription active + ad-account budget covers the spend)
  layer 2 - copy approval (every post approved, or an explicit auto-approve)
then campaign -> adset -> creative -> ad, all created PAUSED, and the
PENDING -> PENDING_APPROVAL -> APPROVED -> DEPLOYED -> LIVE state machine is advanced.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.session import Boost, Post, Ad, AdAccount, User, Event
from app.services.credits import (
    check_launch_budget, check_approval, CampaignStage, CampaignAction,
)


def _as_datetime(value):
    """Boost.go_live_date is stored as 'YYYY-MM-DD'; accept either form."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def resolve_ad_account(boost: Boost, current_user: User, db: Session):
    if boost.ad_account_id:
        acct = db.query(AdAccount).filter(AdAccount.id == boost.ad_account_id).first()
        if acct:
            return acct
    return (db.query(AdAccount)
            .filter(AdAccount.user_id == boost.user_id, AdAccount.platform == "meta",
                    AdAccount.is_active == True)
            .first())


def _merge_custom(configs: dict, custom: dict) -> list:
    """Overlay the operator's hand-edited campaign/adset/adcreative fields from the launch
    UI on top of the built configs. Returns the overridden paths so the caller can report
    exactly what the human changed (nothing is silently dropped)."""
    overridden = []
    for section, values in (custom or {}).items():
        if section not in configs or not isinstance(values, dict):
            continue
        for k, v in values.items():
            if configs[section].get(k) != v:
                configs[section][k] = v
                overridden.append(f"{section}.{k}")
    return overridden


async def launch_boost(boost: Boost, current_user: User, db: Session, *, budget_usd=None,
                       auto_approve: bool = False, action: str = None,
                       custom_configs: dict = None) -> dict:
    """Run the gate and, if it passes, create the campaign. Returns a JSON-safe dict."""
    from app.services.ad_platforms import get_platform_client, build_boost_configs

    action = action or CampaignAction.LAUNCH_NEW_CAMPAIGN
    ad_account = resolve_ad_account(boost, current_user, db)
    if not ad_account:
        return {"status": "no_ad_account",
                "detail": "No Meta ad account connected yet - connect one first",
                "boost_id": boost.id}

    posts = db.query(Post).filter(Post.boost_id == boost.id).all()
    if not posts:
        return {"status": "nothing_to_launch",
                "detail": "Build and approve the campaign content first",
                "boost_id": boost.id}

    # Layer-0 gate: is the connection itself healthy? In a client-billed setup the ad
    # account is the customer's own and their card pays Meta, so a dead token or an account
    # that cannot spend has to stop the launch HERE. Creating a PAUSED campaign that can
    # never run hides the problem until the customer notices no results.
    from app.services import token_health
    health = await token_health.ensure_ready(ad_account, db)
    if not health["ok"]:
        db.add(Event(user_id=current_user.id, boost_id=boost.id, event_type="error",
                     payload={"where": "launch_preflight", "status": health["status"],
                              "detail": (health.get("detail") or "")[:300]}))
        db.commit()
        return {"status": health["status"], "boost_id": boost.id,
                "ad_account_id": ad_account.id, "needs": health.get("needs", []),
                "detail": health.get("detail") or "the ad account is not ready to launch",
                "preflight": health.get("summary")}

    budget = float(budget_usd or boost.ad_budget_usd or 0.0)
    precheck = check_launch_budget(ad_account, budget)
    copy_approved = all(p.client_status == "approved" for p in posts)
    approval = check_approval(precheck["budget_approved"], copy_approved, auto_approve=auto_approve)

    # Layer-2 gate: the boost has to have been approved as a whole, too.
    stage_now = boost.stage or CampaignStage.PENDING
    if not approval["can_auto_publish"]:
        if CampaignStage.can_transition(stage_now, CampaignStage.PENDING_APPROVAL):
            boost.stage = CampaignStage.PENDING_APPROVAL
            db.commit()
        return {
            "status": "approval_required",
            "boost_id": boost.id,
            "budget_approved": precheck["budget_approved"],
            "copy_approved": copy_approved,
            "can_auto_publish": False,
            "reasons": approval["reasons"],
            "precheck": precheck,
        }

    configs = build_boost_configs(boost, plan=boost.plan or {}, page_id=ad_account.page_id)
    overridden = _merge_custom(configs, custom_configs or {})
    if overridden:
        configs.setdefault("notes", []).append("operator overrides: " + ", ".join(overridden))
    client = get_platform_client(ad_account)
    try:
        result = await client.create_campaign(configs)
    except Exception as e:
        # The client rolls back a half-created chain and reports what it removed, so a
        # failed launch leaves the customer's ad account exactly as it found it.
        partial = getattr(e, "partial", None) or {}
        db.add(Event(user_id=current_user.id, boost_id=boost.id, event_type="error",
                     payload={"where": "meta_launch", "error": str(e)[:400], "partial": partial}))
        db.commit()
        # Turn Meta's sentence into the action a human has to take, when it is one we know.
        kind = None
        if getattr(e, "graph_error", None):
            kind = (token_health.classify_graph_error(e.graph_error) or {}).get("kind")
        return {"status": "failed", "boost_id": boost.id,
                "needs": [kind] if kind else [],
                "created_ids": partial.get("created", {}),
                "rolled_back": partial.get("deleted", []),
                "detail": f"Meta launch failed: {e}"}

    campaign_id = (result.get("campaign") or {}).get("id")
    adset_id = (result.get("adset") or {}).get("id")
    creative_id = (result.get("creative") or {}).get("id")
    ad_id = (result.get("ad") or {}).get("id")

    boost.meta_campaign_id = campaign_id
    boost.stage = CampaignStage.DEPLOYED     # campaign exists and is PAUSED
    boost.main_status = "Launched"
    boost.launched_at = datetime.utcnow()

    ad_row = db.query(Ad).filter(Ad.boost_id == boost.id).first()
    if not ad_row:
        ad_row = Ad(boost_id=boost.id, kind="photo")
        db.add(ad_row)
    ad_row.meta_ad_id = ad_id
    ad_row.meta_adset_id = adset_id
    ad_row.meta_creative_id = creative_id
    ad_row.status = "submitted"

    db.add(Event(user_id=current_user.id, boost_id=boost.id, event_type="campaign_launched",
                 payload={"action": action, "campaign_id": campaign_id, "adset_id": adset_id,
                          "creative_id": creative_id, "ad_id": ad_id,
                          "simulated": bool(result.get("simulated"))}))
    db.commit()

    return {
        "status": "launched",
        "boost_id": boost.id,
        "stage": boost.stage,
        "simulated": bool(result.get("simulated")),
        "budget_approved": precheck["budget_approved"],
        "copy_approved": copy_approved,
        "can_auto_publish": True,
        "meta_campaign_id": campaign_id,
        "meta_adset_id": adset_id,
        "meta_creative_id": creative_id,
        "meta_ad_id": ad_id,
        "config_notes": configs.get("notes", []),
        "overridden_fields": overridden,
    }
