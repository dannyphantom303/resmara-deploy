"""Connection-string handling that has no side effects.

Kept apart from ``app.db.session`` so it can be imported and tested without opening an
engine: ``session.py`` builds the engine at import time, which imports the DBAPI driver.
"""


def normalize_database_url(raw: str) -> str:
    """Point a bare postgres URL at the psycopg 3 driver this image ships.

    Managed hosts (Render, Fly, Heroku) hand out ``postgres://`` or ``postgresql://``.
    SQLAlchemy maps both to psycopg2, which is not installed — the pinned driver in
    requirements.txt is psycopg 3. An explicit ``+psycopg`` URL is left untouched, and
    sqlite URLs pass straight through.
    """
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw
