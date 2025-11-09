"""schema_info MCP tool implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import anyio
from fastmcp import FastMCP


@dataclass
class SchemaToolService:
    schema_path: Path
    glossary_path: Path

    def load_text(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return path.read_text(encoding="utf-8")

    async def execute(self, include_glossary: bool, include_examples: bool) -> dict[str, object]:
        schema_md = await anyio.to_thread.run_sync(self.load_text, self.schema_path)
        glossary_md = ""
        if include_glossary:
            glossary_md = await anyio.to_thread.run_sync(self.load_text, self.glossary_path)
        payload: dict[str, object] = {
            "schema_md": schema_md,
        }
        if include_glossary:
            payload["glossary_md"] = glossary_md
        if include_examples:
            # Placeholder: could be replaced by curated examples later.
            payload["examples"] = [
                "SELECT * FROM samples LIMIT 10;",
                "SELECT customer_id, count(*) FROM orders GROUP BY 1;",
            ]
        return payload


def register_schema_tools(app: FastMCP, schema_path: Path, glossary_path: Path) -> None:
    service = SchemaToolService(schema_path=schema_path, glossary_path=glossary_path)

    @app.tool(
        "schema_info",
        description="Return the latest schema and glossary information used for MCP tools.",
    )
    async def schema_info(
        include_glossary: bool = True,
        include_examples: bool = False,
    ) -> dict[str, object]:
        """
        Fetch schema/glossary markdown assets.

        Args:
            include_glossary: If true, include glossary markdown.
            include_examples: If true, include canned SQL examples.
        """

        return await service.execute(include_glossary=include_glossary, include_examples=include_examples)
