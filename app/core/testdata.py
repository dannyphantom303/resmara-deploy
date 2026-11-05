"""Which rows are ours, not a customer's.

The test suites register throwaway clients on every run (`smoke<epoch>@example.com`) and
connect simulated ad accounts, so the operator console had 71 "users" and 24 support tickets
that no human ever created - which buried the four real accounts and made the console a
20-screen scroll. One definition, shared by the admin endpoints and the console, keeps the
real numbers visible and the test rows one click away instead of gone.
"""

# Domains reserved for documentation and tests (RFC 2606 / RFC 6761) - a real client can
# never own one, so a row using it was made by a test.
TEST_DOMAINS = ("example.com", "example.org", "example.net", "example.edu", "test", "localhost")
TEST_LOCAL_PREFIXES = ("smoke", "demo", "test", "e2e")


def is_test_email(email: str | None) -> bool:
    """True when an account was registered by a test run rather than a person.

    Being wrong here is not cosmetic: hiding a real customer's ticket is worse than showing a
    test one, so the rule only fires on reserved domains and obvious throwaway local parts.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    local, _, domain = email.rpartition("@")
    if domain in TEST_DOMAINS or domain.endswith(".test") or domain.endswith(".localhost"):
        return True
    return local.startswith(TEST_LOCAL_PREFIXES)


def is_test_advertiser(advertiser_id: str | None) -> bool:
    """True for the demo/smoke ad accounts the prototype and suites connect."""
    adv = (advertiser_id or "").strip().lower()
    return adv.startswith(("act_smoke", "act_demo", "act_test")) or adv in ("demo_token", "act_demo_12345")
