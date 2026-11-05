#!/usr/bin/env python
"""Create (or promote) the first operator account on a fresh Resmara deployment.

The app has no admin bootstrap route on purpose - the first operator must be made on the box,
against the same DATABASE_URL the app uses:

    DATABASE_URL=postgresql+psycopg://resmara:pw@db:5432/resmara \
      python scripts/create_operator.py --email ops@example.com --password 'S3cret!' --name Dana

Run it inside the container so the environment matches:

    docker compose exec app python scripts/create_operator.py --email ops@example.com ...

Idempotent: an existing account is promoted to admin and its password left alone unless
--password is passed explicitly. Never prints the password back.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import get_password_hash  # noqa: E402
from app.db.session import SessionLocal, User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Create or promote a Resmara operator account.")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", default=None, help="omit to create the account without a usable password")
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-admin", action="store_true", help="create a normal client account instead")
    args = ap.parse_args()

    want_admin = not args.no_admin
    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            if not args.password:
                print("refusing to create a new account without --password", file=sys.stderr)
                return 2
            user = User(
                email=email,
                name=args.name or email.split("@")[0],
                hashed_password=get_password_hash(args.password),
                is_active=True,
                is_admin=want_admin,
            )
            db.add(user)
            action = "created"
        else:
            action = "found"
            if args.password:
                user.hashed_password = get_password_hash(args.password)
                action = "password reset"
            if args.name:
                user.name = args.name
            user.is_admin = want_admin or user.is_admin
        db.commit()
        db.refresh(user)
        print(f"{action}: id={user.id} email={user.email} is_admin={user.is_admin} is_active={user.is_active}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
