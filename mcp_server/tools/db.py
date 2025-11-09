"""db_read MCP tool implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable

import anyio
from fastmcp import FastMCP
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


@dataclass
class DbToolService:
    """Wraps DB interactions so they are easy to test."""

    engine: Engine

    def ensure_select(self, query: str, limit: int) -> str:
        lowered = query.strip().lower()
        if not lowered.startswith("select"):
            raise ValueError("Only SELECT statements are allowed.")
        if "limit" in lowered:
            return query
        query = query.rstrip().rstrip(";")
        return f"{query} LIMIT {limit}"

    def run_query(self, query: str, params: Dict[str, Any] | None) -> list[dict[str, Any]]:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                rows = [dict(row) for row in result.mappings()]
            return rows
        except SQLAlchemyError as exc:  # pragma: no cover - raised in runtime
            raise RuntimeError(f"Database query failed: {exc}") from exc

    async def execute(
        self,
        query: str,
        params: Dict[str, Any] | None,
        limit: int,
    ) -> dict[str, Any]:
        sanitized = self.ensure_select(query, limit)
        rows = await anyio.to_thread.run_sync(self.run_query, sanitized, params)
        return {
            "rows": rows,
            "row_count": len(rows),
        }


def register_db_tools(app: FastMCP, engine: Engine) -> None:
    """Register the db_read tool with the MCP application."""

    service = DbToolService(engine=engine)

    @app.tool(
        "db_read",
        description="Execute read-only SQL queries with optional bind parameters.",
    )
    async def db_read(
        query: str,
        params: Dict[str, Any] | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """
        Execute a read-only SQL query.

        Args:
            query: SQL SELECT statement.
            params: Optional dictionary of bind parameters.
            limit: Optional LIMIT appended when not present.
        """

        return await service.execute(query=query, params=params, limit=limit)
