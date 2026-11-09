"""A sign-in has to outlive the work it is for.

The reported bug: "I tried to connect my Facebook page and it said could not start the Meta
connection." The cause was not Meta. A sign-in lasted 60 minutes, the browser kept calling
itself signed in, and the next API call came back 401 "Could not validate credentials" -
which the Connect Meta button reported as a Meta failure.

Two things are pinned here: the default session lasts longer than a campaign setup, and the
expiry the token carries matches the setting (so the browser can read it and say so).
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jose import jwt  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


# ---- the default is longer than the work ------------------------------------------
check("the default session lasts at least a day",
      settings.ACCESS_TOKEN_EXPIRE_MINUTES >= 60 * 24,
      f"{settings.ACCESS_TOKEN_EXPIRE_MINUTES} minutes")

# ---- the token says when it ends --------------------------------------------------
token = create_access_token({"sub": "customer@example.com"})
claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
issued = datetime.now(timezone.utc)
expires = datetime.fromtimestamp(claims["exp"], timezone.utc)
minutes = (expires - issued).total_seconds() / 60
check("a token expires when the setting says",
      abs(minutes - settings.ACCESS_TOKEN_EXPIRE_MINUTES) < 2,
      f"{minutes:.0f} minutes")

# The customer's own timeline: they signed in this morning and tried the connection in the
# afternoon. That has to still be a session.
check("a token issued this morning is still alive this afternoon",
      minutes > 6 * 60, f"{minutes:.0f} minutes")

# ---- an override still works ------------------------------------------------------
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "90"
from app.core.config import Settings  # noqa: E402

check("ACCESS_TOKEN_EXPIRE_MINUTES still overrides the default",
      Settings().ACCESS_TOKEN_EXPIRE_MINUTES == 90,
      str(Settings().ACCESS_TOKEN_EXPIRE_MINUTES))
del os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"]

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    sys.exit(1)
print("ALL SESSION LIFETIME TESTS PASSED")
