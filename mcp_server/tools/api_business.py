"\"\"\"api_business_read MCP tool implementation.\"\"\""

from __future__ import annotations

from typing import Any, Dict

import anyio
from fastmcp import FastMCP

from app.api.client import DownloaderApiClient
from app.api.endpoints import ENDPOINT_SPECS


class ApiToolService:
    def __init__(self, client: DownloaderApiClient) -> None:
        self._client = client

    def validate_endpoint(self, endpoint: str) -> None:
        if endpoint not in ENDPOINT_SPECS:
            raise ValueError(f"Endpoint '{endpoint}' is not supported.")

    async def call(self, endpoint: str, params: Dict[str, Any] | None) -> Dict[str, Any]:
        self.validate_endpoint(endpoint)

        def _run() -> Dict[str, Any]:
            result = self._client.request(endpoint, params=params or {})
            payload: Dict[str, Any] = {
                "endpoint": endpoint,
                "status_code": result.status_code,
                "error": result.error,
                "data": result.data,
            }
            return payload

        return await anyio.to_thread.run_sync(_run)


def register_api_tools(app: FastMCP, client: DownloaderApiClient) -> None:
    service = ApiToolService(client=client)

    @app.tool(
        "api_business_read",
        description="Proxy read-only analytics endpoints exposed by the llm-sql-bot API.",
    )
    async def api_business_read(
        endpoint: str,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Invoke a whitelisted analytics endpoint.

        Args:
            endpoint: Name of the endpoint as defined in ENDPOINT_SPECS.
            params: Query/path params depending on the endpoint.
        """

        return await service.call(endpoint=endpoint, params=params)
