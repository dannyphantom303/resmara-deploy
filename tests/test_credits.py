"""Hermetic tests for app.services.credits.

Covers the Creatify-mirrored credit precheck, the two-layer approval check
(including the auto_approve bypass), creative-copy gating, and the full campaign
state machine (valid transitions accepted, invalid rejected, LIVE terminal).

Run:  cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_credits.py
"""

import sys
from types import SimpleNamespace

from app.services.credits import (
    check_credit,
    check_approval,
    check_creative_copy,
    CampaignStage,
    CampaignAction,
)

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


def user(subscription="inactive", is_admin=False):
    return SimpleNamespace(subscription_status=subscription, is_admin=is_admin)


def ad_account(budget=1000.0, is_active=True, platform="meta", advertiser_id="act_1", currency="USD"):
    return SimpleNamespace(budget=budget, is_active=is_active, platform=platform,
                           advertiser_id=advertiser_id, currency=currency)


def main():
    global PASSED, FAILED

    # --- check_credit -----------------------------------------------------
    print("[check_credit]")
    ok = check_credit(user("active"), ad_account(budget=1000.0), 50.0)
    for key in ("has_sufficient_credit", "budget_approved", "available_budget",
                "required_budget", "currency", "platform", "advertiser_id", "message"):
        check(f"returns key '{key}'", key in ok, sorted(ok))
    check("active subscription + enough budget approves",
          ok["has_sufficient_credit"] is True and ok["budget_approved"] is True)
    check("available/required echo the account and request",
          ok["available_budget"] == 1000.0 and ok["required_budget"] == 50.0)
    check("currency/platform/advertiser_id surfaced",
          ok["currency"] == "USD" and ok["platform"] == "meta" and ok["advertiser_id"] == "act_1")

    inactive = check_credit(user("inactive"), ad_account(budget=1000.0), 50.0)
    check("inactive subscription rejects", inactive["budget_approved"] is False)
    check("inactive subscription message mentions subscription",
          "subscription" in inactive["message"].lower(), inactive["message"])

    admin = check_credit(user("inactive", is_admin=True), ad_account(budget=1000.0), 50.0)
    check("admin bypasses the subscription gate", admin["budget_approved"] is True)

    poor = check_credit(user("active"), ad_account(budget=10.0), 50.0)
    check("insufficient budget rejects", poor["budget_approved"] is False)
    check("insufficient budget message present", "budget" in poor["message"].lower(), poor["message"])

    inactive_acct = check_credit(user("active"), ad_account(budget=1000.0, is_active=False), 50.0)
    check("inactive account rejects", inactive_acct["budget_approved"] is False)
    check("inactive account message", "inactive" in inactive_acct["message"].lower(),
          inactive_acct["message"])

    exact = check_credit(user("active"), ad_account(budget=50.0), 50.0)
    check("budget exactly equal is sufficient", exact["budget_approved"] is True)

    # --- check_approval ---------------------------------------------------
    print("\n[check_approval]")
    both = check_approval(True, True)
    check("both approved -> can_auto_publish", both["can_auto_publish"] is True)
    check("both approved -> no reasons", both["reasons"] == [], both["reasons"])
    check("result keys present",
          all(k in both for k in ("budget_approved", "copy_approved", "can_auto_publish", "reasons")))

    no_copy = check_approval(True, False)
    check("copy not approved blocks publish", no_copy["can_auto_publish"] is False)
    check("copy reason recorded",
          any("copy" in r.lower() for r in no_copy["reasons"]), no_copy["reasons"])

    no_budget = check_approval(False, True)
    check("budget not approved blocks publish", no_budget["can_auto_publish"] is False)
    check("budget reason recorded",
          any("budget" in r.lower() for r in no_budget["reasons"]), no_budget["reasons"])

    auto = check_approval(True, False, auto_approve=True)
    check("auto_approve bypasses the copy gate", auto["can_auto_publish"] is True)
    check("auto_approve reason recorded",
          any("auto-approve" in r.lower() for r in auto["reasons"]), auto["reasons"])

    auto_no_budget = check_approval(False, False, auto_approve=True)
    check("auto_approve does NOT bypass the budget gate",
          auto_no_budget["can_auto_publish"] is False)

    # --- check_creative_copy ----------------------------------------------
    print("\n[check_creative_copy]")
    check("APPROVED creative passes", check_creative_copy(SimpleNamespace(render_status="APPROVED")) is True)
    check("PENDING creative fails", check_creative_copy(SimpleNamespace(render_status="PENDING")) is False)
    check("REJECTED creative fails", check_creative_copy(SimpleNamespace(render_status="REJECTED")) is False)

    # --- CampaignStage (dSn mirror) --------------------------------------
    print("\n[CampaignStage state machine]")
    S = CampaignStage
    check("PENDING -> PENDING_APPROVAL valid", S.can_transition(S.PENDING, S.PENDING_APPROVAL) is True)
    check("PENDING -> APPROVED valid", S.can_transition(S.PENDING, S.APPROVED) is True)
    check("PENDING -> LIVE REJECTED", S.can_transition(S.PENDING, S.LIVE) is False)
    check("PENDING -> DEPLOYED REJECTED", S.can_transition(S.PENDING, S.DEPLOYED) is False)
    check("PENDING_APPROVAL -> APPROVED valid", S.can_transition(S.PENDING_APPROVAL, S.APPROVED) is True)
    check("PENDING_APPROVAL -> PENDING valid (send back)", S.can_transition(S.PENDING_APPROVAL, S.PENDING) is True)
    check("PENDING_APPROVAL -> LIVE REJECTED", S.can_transition(S.PENDING_APPROVAL, S.LIVE) is False)
    check("APPROVED -> DEPLOYED valid", S.can_transition(S.APPROVED, S.DEPLOYED) is True)
    check("APPROVED -> PENDING_APPROVAL valid (revoke)", S.can_transition(S.APPROVED, S.PENDING_APPROVAL) is True)
    check("APPROVED -> LIVE REJECTED (must deploy first)", S.can_transition(S.APPROVED, S.LIVE) is False)
    check("DEPLOYED -> LIVE valid", S.can_transition(S.DEPLOYED, S.LIVE) is True)
    check("DEPLOYED -> APPROVED valid (rollback)", S.can_transition(S.DEPLOYED, S.APPROVED) is True)
    check("LIVE -> LIVE valid (terminal, idempotent)", S.can_transition(S.LIVE, S.LIVE) is True)
    check("LIVE -> APPROVED REJECTED (terminal)", S.can_transition(S.LIVE, S.APPROVED) is False)
    check("LIVE -> DEPLOYED REJECTED (terminal)", S.can_transition(S.LIVE, S.DEPLOYED) is False)
    check("unknown source stage has no transitions", S.can_transition("BOGUS", S.APPROVED) is False)
    check("all five stages enumerated", set(S.all_stages()) == {"PENDING", "PENDING_APPROVAL", "APPROVED", "DEPLOYED", "LIVE"})

    # walk the full happy-path chain
    chain = [S.PENDING, S.PENDING_APPROVAL, S.APPROVED, S.DEPLOYED, S.LIVE]
    walk_ok = all(S.can_transition(chain[i], chain[i + 1]) for i in range(len(chain) - 1))
    check("full chain PENDING..LIVE is walkable", walk_ok is True)

    # --- CampaignAction (Jgn mirror) -------------------------------------
    print("\n[CampaignAction]")
    A = CampaignAction
    expected_actions = {
        "LAUNCH_NEW_CREATIVES", "LAUNCH_NEW_CAMPAIGN", "CREATE_CAMPAIGN_DRAFT",
        "EDIT_CAMPAIGN_STATUS", "EDIT_ADGROUP", "APPROVE", "AUTO_APPROVE", "SKIP_APPROVAL",
    }
    actual = {getattr(A, name) for name in dir(A) if name.isupper()}
    check("all Jgn action constants present", actual == expected_actions, actual)

    # --- summary ----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"{PASSED} passed, {FAILED} failed")
    if FAILED:
        print("SOME CREDITS TESTS FAILED")
        sys.exit(1)
    print("ALL CREDITS TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
