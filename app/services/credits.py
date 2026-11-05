"""Credit/budget checking, approval, and the campaign state machine for Resmara.

Ported from the Creatify reverse-engineering reference
(``/Users/dan/tmg-fastapi/app/services/credits.py``). Mirrors Creatify's
two-layer approval system as exercised by ``create_and_launch_new_campaign``:

1. Credit precheck  -> POST ``/tools/adflow/credits/precheck/``
   The user must have an active subscription (or be an admin) AND the ad account
   must be active and hold enough budget.
2. Creative approval -> a creative may only be launched once its
   ``render_status == "APPROVED"`` (the copy/render has been signed off).
3. State machine    -> ``PENDING -> PENDING_APPROVAL -> APPROVED -> DEPLOYED -> LIVE``
   (mirrors Creatify's ``dSn`` enum) plus the action set (mirrors the ``Jgn`` enum).

All functions return plain dicts so the API layer can read them directly.
"""

from app.db.session import User, AdAccount, Creative  # noqa: F401  (typing / documentation)


def check_credit(user, ad_account, budget) -> dict:
    """Check whether a user has sufficient credit/budget for a campaign.

    Mirrors Creatify's ``POST /tools/adflow/credits/precheck/`` endpoint:
      * Layer 1 — subscription: ``user.subscription_status == 'active'`` OR the
        user is an admin (``is_admin`` is a full bypass, matching the reference).
      * Layer 2 — platform budget: the ad account must be ``is_active`` and its
        ``budget`` must cover the requested ``budget``.

    Returns ``budget_approved=True`` when the campaign may launch.
    """
    subscription_approved = (
        getattr(user, "subscription_status", None) == "active"
        or bool(getattr(user, "is_admin", False))
    )

    platform_active = bool(getattr(ad_account, "is_active", False))
    available = getattr(ad_account, "budget", None) or 0.0
    required = budget or 0.0
    platform_budget_ok = available >= required

    has_sufficient = subscription_approved and platform_active and platform_budget_ok

    if has_sufficient:
        message = "Budget approved — sufficient subscription and platform credits"
    elif not subscription_approved:
        message = "Insufficient budget or inactive subscription"
    elif not platform_active:
        message = "Ad account is inactive"
    else:
        message = "Insufficient ad account budget"

    return {
        "has_sufficient_credit": has_sufficient,
        "budget_approved": has_sufficient,
        "available_budget": available,
        "required_budget": required,
        "currency": getattr(ad_account, "currency", "USD"),
        "platform": getattr(ad_account, "platform", None),
        "advertiser_id": getattr(ad_account, "advertiser_id", None),
        "message": message,
    }


def check_approval(budget_approved: bool, copy_approved: bool, auto_approve: bool = False) -> dict:
    """Determine whether a campaign may be posted without manual approval.

    This is the core of Creatify's "post without approval" mechanism:
      * ``budget_approved`` — sufficient credits + active subscription;
      * ``copy_approved``   — the creative render status is APPROVED;
      * ``auto_approve``    — an additional bypass the AdMax chat agent can set.

    When both budget and copy are approved the campaign is posted immediately via
    ``create_and_launch_new_campaign`` — no manual approval step. ``auto_approve``
    only clears the copy gate (budget must still be approved).
    """
    reasons: list[str] = []

    if not budget_approved:
        reasons.append("Budget not approved — insufficient credits or inactive subscription")
    if not copy_approved:
        reasons.append("Copy not approved — creative render status is not APPROVED")

    can_auto_publish = budget_approved and copy_approved

    if auto_approve and budget_approved:
        can_auto_publish = True
        reasons.append("Auto-approve enabled by campaign action")

    return {
        "budget_approved": budget_approved,
        "copy_approved": copy_approved,
        "can_auto_publish": can_auto_publish,
        "reasons": reasons,
    }


def check_creative_copy(creative) -> bool:
    """True only when the creative's copy/render has been approved.

    Mirrors Creatify's ``render_status`` check: only creatives with
    ``render_status == "APPROVED"`` may be used in campaign creation.
    """
    return getattr(creative, "render_status", None) == "APPROVED"


# --- State machine ---------------------------------------------------------

class CampaignStage:
    """Campaign approval state machine (mirrors Creatify's ``dSn`` enum).

    ``PENDING`` is a fresh campaign; ``PENDING_APPROVAL`` awaits a human;
    ``APPROVED`` is cleared to deploy; ``DEPLOYED`` has been pushed to the
    platform; ``LIVE`` is the terminal, running state.
    """

    PENDING = "PENDING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    LIVE = "LIVE"

    @classmethod
    def all_stages(cls) -> list[str]:
        return [cls.PENDING, cls.PENDING_APPROVAL, cls.APPROVED, cls.DEPLOYED, cls.LIVE]

    @classmethod
    def transitions(cls) -> dict:
        """Valid transitions. ``LIVE`` is terminal (only ``LIVE`` -> ``LIVE``)."""
        return {
            cls.PENDING: [cls.PENDING_APPROVAL, cls.APPROVED],
            cls.PENDING_APPROVAL: [cls.APPROVED, cls.PENDING],
            cls.APPROVED: [cls.DEPLOYED, cls.PENDING_APPROVAL],
            cls.DEPLOYED: [cls.LIVE, cls.APPROVED],
            cls.LIVE: [cls.LIVE],  # Terminal state
        }

    @classmethod
    def can_transition(cls, from_stage: str, to_stage: str) -> bool:
        """True when ``from_stage -> to_stage`` is a legal move."""
        return to_stage in cls.transitions().get(from_stage, [])


class CampaignAction:
    """Campaign action types (mirrors Creatify's ``Jgn`` enum).

    ``LAUNCH_NEW_CAMPAIGN`` / ``LAUNCH_NEW_CREATIVES`` are the
    ``create_and_launch_new_campaign`` entrypoints; ``APPROVE`` /
    ``AUTO_APPROVE`` / ``SKIP_APPROVAL`` are the two-layer approval actions.
    """

    LAUNCH_NEW_CREATIVES = "LAUNCH_NEW_CREATIVES"
    LAUNCH_NEW_CAMPAIGN = "LAUNCH_NEW_CAMPAIGN"
    CREATE_CAMPAIGN_DRAFT = "CREATE_CAMPAIGN_DRAFT"
    EDIT_CAMPAIGN_STATUS = "EDIT_CAMPAIGN_STATUS"
    EDIT_ADGROUP = "EDIT_ADGROUP"
    APPROVE = "APPROVE"
    AUTO_APPROVE = "AUTO_APPROVE"
    SKIP_APPROVAL = "SKIP_APPROVAL"
