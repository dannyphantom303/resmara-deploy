"""Idempotent column migrations for the Resmara SQLite database.

`Base.metadata.create_all` creates missing *tables* but never adds missing *columns*
to tables that already exist, so new fields on ad_accounts/posts/ads need an explicit
ALTER. This runs on every startup and is a no-op once the columns are present.
"""
from sqlalchemy import inspect, text
from app.db.session import engine

# table -> [(column, DDL type/definition)]
ADDITIONS = {
    # A brand profile the customer entered has to outlive the browser it was typed in.
    "users": [
        ("brand", "JSON"),
        ("stripe_customer_id", "VARCHAR"),
    ],
    "ad_accounts": [
        ("refresh_token", "TEXT"),
        ("token_expires_at", "DATETIME"),
        ("page_id", "VARCHAR"),
        ("ig_user_id", "VARCHAR"),
        ("token_status", "VARCHAR"),
        ("token_checked_at", "DATETIME"),
        ("token_note", "TEXT"),
        ("funding_status", "VARCHAR"),
        ("funding_note", "TEXT"),
        ("account_status", "INTEGER"),
        ("account_checked_at", "DATETIME"),
        ("token_refreshed_at", "DATETIME"),
        ("token_refresh_note", "TEXT"),
    ],
    "posts": [
        ("publish_target", "VARCHAR DEFAULT 'both'"),
        ("last_error", "TEXT"),
    ],
    "ads": [
        ("meta_adset_id", "VARCHAR"),
        ("meta_creative_id", "VARCHAR"),
        ("reach", "INTEGER"),
        ("last_error", "TEXT"),
    ],
    # Listing photos live in the row, not only on disk: a free-tier instance has no volume,
    # so every deploy and every idle restart wipes uploads/ and leaves image_url pointing at
    # a 404. Bytes are stored next to the asset so the photo survives a restart.
    "assets": [
        ("data", "BYTEA"),
        ("content_type", "VARCHAR"),
    ],
    # A campaign is bought, not credited: these columns on an existing install are what let
    # the build gate ask "was this campaign paid for?" without a second query.
    "boosts": [
        ("paid_at", "TIMESTAMP"),
        ("paid_amount_cents", "INTEGER"),
        # Hiding a campaign from the list is reversible and keeps its history; only the flag
        # changes. A duplicate "boosts" key here would have silently dropped this entry, so
        # every boost column belongs in this one block.
        ("hidden", "BOOLEAN DEFAULT FALSE"),
    ],
    "orders": [
        ("user_id", "INTEGER"),
        ("boost_id", "INTEGER"),
        ("amount_cents", "INTEGER"),
        ("currency", "VARCHAR"),
        ("status", "VARCHAR"),
        ("stripe_session_id", "VARCHAR"),
        ("stripe_payment_intent", "VARCHAR"),
        ("checkout_url", "TEXT"),
        ("created_at", "TIMESTAMP"),
        ("paid_at", "TIMESTAMP"),
    ],
}

# SQLite has no BYTEA.
_DIALECT_TYPES = {("assets", "data"): {"postgresql": "BYTEA", "sqlite": "BLOB"}}


def encrypt_stored_tokens() -> int:
    """One-time upgrade: encrypt any token still stored in plaintext. No-op afterwards.

    Deliberately uses the raw connection and not the AdAccount model: the model's
    `access_token` property would decrypt on read, which for a legacy plaintext value is a
    no-op but for anything already encrypted would double-handle it. Working in SQL keeps
    this a dumb, idempotent data fix.
    """
    from app.core.crypto import encrypt, is_encrypted
    changed = 0
    insp = inspect(engine)
    if "ad_accounts" not in set(insp.get_table_names()):
        return 0
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, access_token, refresh_token FROM ad_accounts")).fetchall()
        for row_id, token, refresh in rows:
            sets, params = [], {}
            if token and not is_encrypted(token):
                sets.append("access_token = :token")
                params["token"] = encrypt(token)
            if refresh and not is_encrypted(refresh):
                sets.append("refresh_token = :refresh")
                params["refresh"] = encrypt(refresh)
            if sets:
                params["rowid"] = row_id
                conn.execute(text(f"UPDATE ad_accounts SET {', '.join(sets)} WHERE id = :rowid"), params)
                changed += 1
    return changed


def migrate() -> list[str]:
    """Add any missing columns. Returns the list of column names actually added."""
    added = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in ADDITIONS.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    per_dialect = _DIALECT_TYPES.get((table, name))
                    if per_dialect:
                        ddl = per_dialect.get(engine.dialect.name, ddl)
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    added.append(f"{table}.{name}")
    return added


if __name__ == "__main__":
    print("added:", migrate() or "nothing (schema already current)")
    print("tokens encrypted:", encrypt_stored_tokens())
