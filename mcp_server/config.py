"""Configuration helpers for the MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings for the MCP server."""

    pg_uri: Annotated[str, Field(alias="PG_URI")]
    api_base_url: Annotated[str, Field(alias="API_BASE_URL", default="http://localhost:8000/api/v1")]
    schema_path: Path = Path("app/prompts/schema.md")
    glossary_path: Path = Path("app/prompts/glossary.md")
    mcp_name: str = "llm-sql-mcp"
    instructions: str = (
        "Expose read-only tools for db queries, schema lookup and analytics API access."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
