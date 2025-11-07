"""
Helpers for connecting to PostgreSQL using SQLAlchemy in read-only mode.

Recommended SQL to create a read-only role (adjust names and schema):

```sql
CREATE ROLE bot_ro LOGIN PASSWORD 'strong_password';
GRANT USAGE ON SCHEMA public TO bot_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bot_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO bot_ro;
```
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


load_dotenv()


logger = logging.getLogger(__name__)

if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


DEFAULT_LIMIT = 50
DEFAULT_TIMEOUT = 30

_engine: Engine | None = None


def get_engine() -> Engine:
    """Create (or memoize) the SQLAlchemy engine using PG_URI environment variable."""
    global _engine  # noqa: PLW0603
    if _engine is not None:
        return _engine

    pg_uri = os.getenv("PG_URI")
    if not pg_uri:
        raise RuntimeError("PG_URI environment variable is not set")

    _engine = create_engine(
        pg_uri,
        connect_args={"connect_timeout": DEFAULT_TIMEOUT},
        pool_pre_ping=True,
    )
    return _engine


def run_sql(sql: str, limit: int = DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    """Execute a read-only SQL statement and return list of row dicts."""
    engine = get_engine()
    cleaned_sql = _ensure_limit(sql, limit)
    try:
        logger.debug("Executing SQL: %s", cleaned_sql)
        with engine.connect() as conn:
            result = conn.execute(text(cleaned_sql))
            rows = [dict(row) for row in result.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("Database query failed")
        raise RuntimeError(f"Database query failed: {exc}") from exc
    return rows


def _ensure_limit(sql: str, limit: int) -> str:
    """Append LIMIT clause when missing."""
    if "limit" in sql.lower():
        return sql
    stripped = sql.rstrip().rstrip(";")
    return f"{stripped} LIMIT {limit};"
