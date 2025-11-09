"""Entry point for the MCP server."""

from __future__ import annotations

from fastmcp import FastMCP

from app.api.client import DownloaderApiClient
from app.db.pg import get_engine
from mcp_server.config import settings
from mcp_server.tools import register_api_tools, register_db_tools, register_schema_tools


def create_app() -> FastMCP:
    app = FastMCP(
        name=settings.mcp_name,
        instructions=settings.instructions,
    )

    engine = get_engine()
    register_db_tools(app, engine)
    register_schema_tools(app, settings.schema_path, settings.glossary_path)
    register_api_tools(app, DownloaderApiClient(base_url=settings.api_base_url))

    @app.tool("health_check", description="Check MCP server health.")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    app = create_app()
    app.run(transport="streamable-http", host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
