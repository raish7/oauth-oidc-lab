"""Database engine. Tables are created by SQL files in bff/migrations (see app.migrate).

Phase 1 adds the users and sessions queries here.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def ping() -> None:
    """Raise if the database is unreachable."""
    with get_engine().connect() as conn:
        conn.execute(text("select 1"))
