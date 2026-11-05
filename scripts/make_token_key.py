#!/usr/bin/env python
"""Print a fresh RESMARA_TOKEN_KEY.

32 random bytes, urlsafe-base64 — the only shape app/core/crypto.py accepts. Set it in the
host's environment before the first ad account is connected. Changing it later makes every
stored token fail to decrypt, so each connected account has to be reconnected by hand.
"""
import base64
import secrets

print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
