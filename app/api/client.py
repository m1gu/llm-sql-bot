"""HTTP client to consume the Downloader QBench Data API."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

from .endpoints import ENDPOINT_SPECS, EndpointSpec


load_dotenv()


def _default_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")


@dataclass
class ApiCallResult:
    """Represents the outcome of an API request."""

    endpoint: str
    params: Dict[str, Any]
    data: Any | None
    error: str | None = None
    status_code: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if isinstance(self.data, (dict, list)):
            payload["data"] = self.data
        return payload


class DownloaderApiClient:
    """Convenience wrapper around httpx for the Downloader API."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self.timeout = timeout

    def request(self, endpoint_name: str, *, params: Optional[Dict[str, Any]] = None) -> ApiCallResult:
        spec = self._resolve_spec(endpoint_name)
        url = self._build_url(spec, params or {})
        prepared_params = self._extract_query_params(spec, params or {})
        try:
            response = httpx.request(spec.method, url, params=prepared_params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return ApiCallResult(
                endpoint=endpoint_name,
                params=prepared_params,
                data=data,
                status_code=response.status_code,
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network errors handled in runtime
            response = getattr(exc, "response", None)
            error_payload = self._extract_error(exc, response)
            return ApiCallResult(
                endpoint=endpoint_name,
                params=prepared_params,
                data=None,
                error=error_payload,
                status_code=getattr(response, "status_code", None),
            )

    def _resolve_spec(self, endpoint_name: str) -> EndpointSpec:
        if endpoint_name not in ENDPOINT_SPECS:
            raise ValueError(f"Endpoint '{endpoint_name}' no está definido")
        return ENDPOINT_SPECS[endpoint_name]

    def _build_url(self, spec: EndpointSpec, params: Dict[str, Any]) -> str:
        path = spec.path
        # Replace path params like {sample_id}
        for param in spec.params:
            if param.required and "{" + param.name + "}" in path:
                if param.name not in params:
                    raise ValueError(f"Missing required path parameter '{param.name}' for {spec.name}")
                value = str(params[param.name])
                path = path.replace("{" + param.name + "}", value)
        return f"{self.base_url}{path}"

    @staticmethod
    def _extract_query_params(spec: EndpointSpec, params: Dict[str, Any]) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        for name, value in params.items():
            if "{" + name + "}" in spec.path:
                # already embedded as path param
                continue
            if value in (None, "", []):
                continue
            query[name] = value
        return query

    @staticmethod
    def _extract_error(exc: httpx.HTTPError, resp: httpx.Response | None) -> str:
        if resp is None:
            return str(exc)
        try:
            payload = resp.json()
            return json.dumps(payload)
        except Exception:  # pragma: no cover - fallback when JSON parsing fails
            return resp.text or str(exc)


__all__ = ["DownloaderApiClient", "ApiCallResult"]
