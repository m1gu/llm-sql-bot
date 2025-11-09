from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.agent.api_orchestrator import (
    EndpointCall,
    ApiOrchestrator,
    extract_json_block,
    parse_plan_response,
    _normalize_duration_phrases,
    _normalize_hours_phrases,
)
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

    def __init__(self, payloads: Dict[str, Any]) -> None:
        super().__init__(base_url="http://stub")
        self._payloads = payloads
        self.calls: List[ApiCallResult] = []

    def request(self, endpoint_name: str, *, params: Dict[str, Any] | None = None):
        entry = self._payloads.get(endpoint_name, {})
        data = entry.get("data") if isinstance(entry, dict) else entry
        status_code = entry.get("status_code", 200) if isinstance(entry, dict) else 200
        error = entry.get("error") if isinstance(entry, dict) else None
        if status_code >= 400 and error is None:
            error = '{"detail": "customer_not_found"}'
            data = None
        result = ApiCallResult(
            endpoint=endpoint_name,
            params=params or {},
            data=data,
            error=error,
            status_code=status_code,
        )
        self.calls.append(result)
        return result


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

    payloads = {
        "metrics_summary": {"data": {"kpis": {"total_samples": 1}}},
        "analytics_customers_orders_summary": {
            "data": {
                "matched_customer": {"id": 101, "name": "La Casa de las Flores"},
                "metrics": {"open_orders": 2},
                "orders": [
                    {
                        "order_id": 3452,
                        "state": "CREATED",
                        "samples": [{"sample_id": 555}],
                        "tests": [{"test_id": 777}],
                    },
                    {
                        "order_id": 4001,
                        "state": "COMPLETED",
                        "samples": [],
                        "tests": [],
                    },
                ],
            }
        },
        "entities_order_detail": {
            "data": {
                "order": {"id": 3452, "state": "CREATED", "pending_tests": 9},
                "samples": [{"id": 555, "state": "CREATED"}],
            }
        },
        "entities_sample_full": {
            "data": {
                "sample": {"id": 555, "state": "CREATED"},
                "order": {"id": 3452},
                "tests": [{"id": 777, "state": "RUNNING"}],
            }
        },
        "entities_test_full": {
            "data": {
                "test": {"id": 777, "state": "RUNNING"},
                "sample": {"id": 555},
                "order": {"id": 3452},
            }
        },
        "metrics_samples_overview": {"data": {"kpis": {"pending": 5}}},
        "analytics_orders_overdue": {"data": {"orders": []}},
    }
    client = StubClient(payloads)
    return ApiOrchestrator(
        client=client,
        planner_llm_factory=planner_factory,
        summarizer_llm_factory=summarizer_factory,
        max_calls=2,
    )


def test_orchestrator_runs_plan(orchestrator):
    result = orchestrator.answer("¿Cuántos samples tenemos?")
    assert result["used"] == "api:special"
    assert result["calls"][0]["endpoint"] == "metrics_samples_overview"


def test_normalize_duration_phrases_converts_decimal_days():
    original = "Average TAT is 4.36 days and SLA is 2 day."
    transformed = _normalize_duration_phrases(original)
    assert "4d" in transformed and "h" in transformed
    assert "2d 0h" in transformed


def test_normalize_hours_phrases_converts_long_hours():
    original = "Average duration is 77 hours and max was 20 hours."
    transformed = _normalize_hours_phrases(original)
    assert "3d" in transformed and "5h" in transformed
    assert "20 hours" in transformed  # stays as hours when below threshold


def test_open_orders_question_uses_special_plan(orchestrator):
    result = orchestrator.answer("La Casa de las Flores open orders")
    endpoints = [call["endpoint"] for call in result["calls"]]
    assert endpoints == ["analytics_customers_orders_summary"]
    assert result["used"] == "api:special"
    params = result["calls"][0]["params"]
    assert params["customer_name"] == "La Casa de las Flores"
    client_calls = getattr(orchestrator, "client").calls
    assert client_calls[0].endpoint == "analytics_customers_orders_summary"
    assert client_calls[0].params["customer_name"] == "La Casa de las Flores"
    assert client_calls[0].params["include_samples"] is True
    assert client_calls[0].params["include_tests"] is True


def test_open_orders_name_not_found(orchestrator):
    orchestrator.client._payloads["analytics_customers_orders_summary"] = {
        "status_code": 404,
        "error": '{"detail": "customer_not_found"}',
    }
    result = orchestrator.answer("Unknown Labs open orders")
    assert result["used"] == "api:special"
    assert "couldn't find any customer" in result["answer"].lower()


def test_customer_samples_question_routes_to_summary(orchestrator):
    result = orchestrator.answer("Dreamscape Farms samples")
    assert result["used"] == "api:special"
    assert result["calls"][0]["endpoint"] == "analytics_customers_orders_summary"
    assert result["calls"][0]["params"]["customer_name"] == "Dreamscape Farms"


def test_order_question_with_customer_extracts_focus_match(orchestrator):
    result = orchestrator.answer("What happened to order 3452 from La Casa de las Flores?")
    call = result["calls"][0]
    matches = call["data"]["focus_matches"]
    assert matches["orders"][0]["order_id"] == 3452


def test_ready_to_report_samples_routes_to_entity_endpoint(orchestrator):
    result = orchestrator.answer("Ready to report samples")
    assert result["calls"][0]["endpoint"] == "metrics_samples_overview"
    assert result["used"] == "api:special"


def test_global_kpi_question_skips_llm_plan(orchestrator):
    result = orchestrator.answer("Total samples overall?")
    assert result["calls"][0]["endpoint"] == "metrics_summary"
    assert result["used"] == "api:special"


def test_customer_order_question_highlights_specific_order(orchestrator):
    result = orchestrator.answer("What happened to order 3452 from La Casa de las Flores?")
    endpoints = [call["endpoint"] for call in result["calls"]]
    assert endpoints[0] == "analytics_customers_orders_summary"
    assert endpoints[1] == "entities_order_detail"
    data = result["calls"][0]["data"]
    matches = data.get("focus_matches", {})
    assert matches["orders"][0]["order_id"] == 3452


def test_order_id_without_customer_uses_entity_endpoint(orchestrator):
    result = orchestrator.answer("Need update on order 3452")
    assert result["calls"][0]["endpoint"] == "entities_order_detail"
    assert result["calls"][0]["params"]["order_id"] == 3452


def test_sample_id_without_customer_uses_entity_endpoint(orchestrator):
    result = orchestrator.answer("sample 555 status?")
    assert result["calls"][0]["endpoint"] == "entities_sample_full"
    assert result["calls"][0]["params"]["sample_id"] == 555


def test_test_id_without_customer_uses_entity_endpoint(orchestrator):
    result = orchestrator.answer("test 777 details")
    assert result["calls"][0]["endpoint"] == "entities_test_full"
    assert result["calls"][0]["params"]["test_id"] == 777
