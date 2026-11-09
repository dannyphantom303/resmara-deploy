"""Who is allowed to create an account.

Resmara is live on a real domain while it is still being built, so "anyone can sign up" is
the wrong default: a stranger registering is a stranger holding a login to a product that is
not finished, and an open signup page is the first thing a crawler finds.

Two ways in, either is enough:

* the address is on the allowlist (the people running the beta), or
* the caller knows the invite code (share it with one partner, no deploy to add an address).

Both empty means open signup, so a local checkout and the test suite behave exactly as
before. The decision is a pure function so it can be tested without a request or a database.
"""

from __future__ import annotations

import hmac


def parse_allowlist(raw: str | None) -> set[str]:
    """Read a comma/space separated list of addresses, lowercased."""
    out: set[str] = set()
    for chunk in (raw or "").replace(";", ",").replace("\n", ",").split(","):
        for piece in chunk.split():
            value = piece.strip().strip('"').lower()
            if value:
                out.add(value)
    return out


def signup_block_reason(email: str, invite_code: str | None, allowlist: str | None,
                        expected_code: str | None, admins: str | None = None) -> str | None:
    """None when this signup may proceed, otherwise the message to show the person.

    A configured code is compared in constant time; an unset code never blocks, which keeps
    a fresh environment usable. An allowlisted address skips the code entirely, so losing the
    code does not lock the owners out of their own product. Owners (ADMIN_EMAILS) are always
    allowed: locking the operator out of their own signup page is never the right answer.
    """
    who = (email or "").strip().lower()
    allowed = parse_allowlist(allowlist) | parse_allowlist(admins)
    code = (expected_code or "").strip()

    if allowed and who in allowed:
        return None
    if not allowed and not code:
        return None
    if code:
        given = (invite_code or "").strip()
        if given and hmac.compare_digest(given, code):
            return None
        if allowed:
            return ("Resmara is in private beta. Sign up with an invited address, or enter the "
                    "invite code you were sent.")
        return "Resmara is in private beta. Enter the invite code you were sent."
    return ("Resmara is in private beta. This address is not on the invite list yet — reply to "
            "the invitation email and we will add it.")
