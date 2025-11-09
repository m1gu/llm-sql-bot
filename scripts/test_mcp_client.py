"""Simple stdio client to exercise the MCP server locally."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
from fastmcp.client import Client, StreamableHttpTransport


async def main() -> None:
    transport = StreamableHttpTransport("http://127.0.0.1:8765/mcp")
    async with Client(transport=transport) as client:
        tools = await client.list_tools()
        print("Tools available:", [tool.name for tool in tools])

        db_result = await client.call_tool(
            "db_read",
            {"query": "SELECT 1 AS value"},
        )
        print("db_read:", db_result)

        schema_result = await client.call_tool("schema_info", {"include_glossary": False})
        schema_payload = schema_result.structured_content or {"schema_md": schema_result.content[0].text}
        print("schema_info keys:", schema_payload.keys())

        api_result = await client.call_tool(
            "api_business_read",
            {
                "endpoint": "metrics_summary",
                "params": {"limit": 1},
            },
        )
        api_payload = api_result.structured_content or {}
        print("api_business_read status:", api_payload.get("status_code"))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    anyio.run(main)
