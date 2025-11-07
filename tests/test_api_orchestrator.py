from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.agent.api_orchestrator import EndpointCall, ApiOrchestrator, extract_json_block, parse_plan_response
from app.api.client import ApiCallResult, DownloaderApiClient


def test_extract_json_block_handles_code_block():
    text = "Plan\n```json\n{\"steps\": []}\n```"
    assert extract_json_block(text) == '{"steps": []}'


def test_parse_plan_response_returns_calls():
    raw = '{"steps": [{"endpoint": "metrics_summary", "params": {"date_from": "2024-01-01"}, "reason": "Check KPIs"}]}'
    calls = parse_plan_response(raw, max_calls=2)
    assert len(calls) == 1
    assert calls[0].endpoint == "metrics_summary"
    assert calls[0].params["date_from"] == "2024-01-01"


def test_parse_plan_response_ignores_unknown_endpoints():
    raw = '{"steps": [{"endpoint": "unknown", "params": {}, "reason": ""}]}'
    calls = parse_plan_response(raw, max_calls=2)
    assert calls == []


class StubClient(DownloaderApiClient):
    """Client stub that returns predefined payloads."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        super().__init__(base_url="http://stub")
        self._payload = payload

    def request(self, endpoint_name: str, *, params: Dict[str, Any] | None = None):
        return ApiCallResult(endpoint=endpoint_name, params=params or {}, data=self._payload, status_code=200)


class StubLLM:
    def __init__(self, text: str):
        self._text = text

    def predict(self, _: str) -> str:
        return self._text


@pytest.fixture()
def orchestrator():
    plan_text = """
    ```json
    {
      "steps": [
        {"endpoint": "metrics_summary", "params": {"date_from": "2024-01-01"}, "reason": "Necesito KPIs"}
      ],
      "notes": "Solo un llamado"
    }
    ```
    """

    def planner_factory():
        return StubLLM(plan_text)

    def summarizer_factory():
        return StubLLM("Final Answer: datos mezclados")

    client = StubClient({"kpis": {"total_samples": 1}})
    return ApiOrchestrator(
        client=client,
        planner_llm_factory=planner_factory,
        summarizer_llm_factory=summarizer_factory,
        max_calls=2,
    )


def test_orchestrator_runs_plan(orchestrator):
    result = orchestrator.answer("¿Cuántos samples tenemos?")
    assert result["used"] == "api"
    assert result["answer"].startswith("Final Answer")
    assert result["calls"][0]["endpoint"] == "metrics_summary"
