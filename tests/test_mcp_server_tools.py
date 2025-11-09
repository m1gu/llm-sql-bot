from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from mcp_server.tools.api_business import ApiToolService
from mcp_server.tools.db import DbToolService
from mcp_server.tools.schema import SchemaToolService

pytestmark = pytest.mark.anyio("asyncio")


class StubApiResponse:
    def __init__(self, endpoint: str, params: dict | None):
        self.endpoint = endpoint
        self.status_code = 200
        self.error = None
        self.data = {"endpoint": endpoint, "params": params}


class StubApiClient:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    def request(self, endpoint_name: str, params: dict | None = None):
        self.calls.append((endpoint_name, params))
        return StubApiResponse(endpoint_name, params)


async def test_db_tool_appends_limit_and_returns_rows(tmp_path: Path):
    db_path = tmp_path / "db.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    service = DbToolService(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE foo (id INTEGER PRIMARY KEY, value TEXT);"))
        conn.execute(text("INSERT INTO foo (value) VALUES ('a'), ('b');"))

    result = await service.execute("SELECT * FROM foo", params=None, limit=1)
    assert result["row_count"] == 1
    assert len(result["rows"]) == 1


def test_db_tool_rejects_non_select():
    engine = create_engine("sqlite://")
    service = DbToolService(engine)
    with pytest.raises(ValueError):
        service.ensure_select("UPDATE foo SET value='x'", limit=10)


async def test_schema_tool_reads_files(tmp_path: Path):
    schema_file = tmp_path / "schema.md"
    schema_file.write_text("# Schema\n", encoding="utf-8")
    glossary_file = tmp_path / "glossary.md"
    glossary_file.write_text("# Glossary\n", encoding="utf-8")

    service = SchemaToolService(schema_path=schema_file, glossary_path=glossary_file)
    payload = await service.execute(include_glossary=True, include_examples=True)
    assert payload["schema_md"].startswith("# Schema")
    assert payload["glossary_md"].startswith("# Glossary")
    assert "examples" in payload


async def test_api_tool_validates_endpoint_and_calls_client():
    from app.api.endpoints import ENDPOINT_SPECS

    client = StubApiClient()
    service = ApiToolService(client=client)
    endpoint_name = next(iter(ENDPOINT_SPECS))
    response = await service.call(endpoint_name, params={"limit": 1})
    assert response["endpoint"] == endpoint_name
    assert client.calls == [(endpoint_name, {"limit": 1})]

    with pytest.raises(ValueError):
        await service.call("unknown_endpoint", params={})
