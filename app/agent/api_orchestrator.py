"""Agent orchestration layer that plans and executes API calls instead of SQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from app.api.client import ApiCallResult, DownloaderApiClient
from app.api.endpoints import ENDPOINT_SPECS, build_endpoint_catalog

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

UTC = timezone.utc


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _floor_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def _format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


PLAN_TEMPLATE = """Eres un analista de laboratorio. Contestas preguntas usando los endpoints REST disponibles.

Endpoints soportados:
{endpoint_catalog}

Contexto temporal:
- Fecha/hora actual (UTC): {current_datetime}
- Guía de rango: {range_description} ({range_start} a {range_end}). Si el usuario no provee fechas, usa este rango.
- Si el usuario menciona expresiones como "last month/week", tradúcelas a rangos exactos basados en la fecha actual.

Instrucciones:
1. Analiza la pregunta del usuario.
2. Decide hasta {max_calls} llamadas a endpoint (puede ser 1 si es suficiente).
3. Devuelve SOLO un JSON válido con el formato:
{{
  "steps": [
    {{"endpoint": "metrics_summary", "params": {{"date_from": "..."}}, "reason": "Por qué"}}
  ],
  "notes": "Detalle de cómo combinarás los datos"
}}

Reglas:
- Usa únicamente los nombres de endpoint listados.
- Incluye sólo parámetros necesarios y en formato ISO cuando sean fechas.
- Si no necesitas llamados extra, elige un endpoint principal y deja los demás fuera.
- Responde siempre en español.

Pregunta: {question}
"""


SUMMARY_TEMPLATE = """Eres un asistente experto en datos de laboratorio. Resume la información recopilada.

Pregunta original:
{question}

Plan ejecutado:
{plan_summary}

Resultados JSON de la API:
{api_payload}

Recuerda mencionar que los datos corresponden al rango {range_description}: {range_start} a {range_end}.
No hables del proceso interno ni de los endpoints (evita frases como "The API call..."). Enfócate solo en lo que sucede con el cliente.
Produce una única respuesta en inglés, sin repetir información. Si necesitas tablas, enciérralas dentro de bloques ``` para que se vean alineadas en Slack.
Termina siempre con una sola línea `Final Answer: ...`.
"""


@dataclass
class EndpointCall:
    endpoint: str
    params: Dict[str, Any]
    reason: str


class SpecialPlan(NamedTuple):
    calls: List["EndpointCall"]
    context: Dict[str, Any]


def extract_json_block(text: str) -> Optional[str]:
    """Return the first JSON object found inside a string."""

    if not text:
        return None
    code_block_match = re.search(r"```json(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_block_match:
        candidate = code_block_match.group(1).strip()
        if candidate:
            return candidate
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        return text[brace_start : brace_end + 1]
    return None


def parse_plan_response(raw_text: str, max_calls: int) -> List[EndpointCall]:
    """Parse the JSON response from the LLM into endpoint calls."""

    json_block = extract_json_block(raw_text)
    if not json_block:
        logger.warning("No JSON block detected in planner output.")
        return []
    try:
        payload = json.loads(json_block)
    except json.JSONDecodeError as exc:
        logger.warning("Planner JSON inválido: %s", exc)
        return []
    steps = payload.get("steps")
    if not isinstance(steps, Sequence):
        logger.warning("Planner response sin lista de pasos.")
        return []

    calls: List[EndpointCall] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        endpoint = raw_step.get("endpoint")
        params = raw_step.get("params") or {}
        reason = raw_step.get("reason") or ""
        if not endpoint or endpoint not in ENDPOINT_SPECS:
            logger.warning("Endpoint desconocido en plan: %s", endpoint)
            continue
        if not isinstance(params, dict):
            logger.warning("Parámetros inválidos para endpoint %s", endpoint)
            params = {}
        calls.append(EndpointCall(endpoint=endpoint, params=params, reason=str(reason)))
        if len(calls) >= max_calls:
            break
    return calls


class ApiOrchestrator:
    """Coordinates planning, execution and summarization using the HTTP API."""

    def __init__(
        self,
        *,
        client: Optional[DownloaderApiClient] = None,
        planner_llm_factory: Optional[Callable[[], Any]] = None,
        summarizer_llm_factory: Optional[Callable[[], Any]] = None,
        max_calls: int = 3,
    ) -> None:
        self.client = client or DownloaderApiClient()
        self._planner_llm_factory = planner_llm_factory or _default_llm_factory
        self._summarizer_llm_factory = summarizer_llm_factory or _default_llm_factory
        self.max_calls = max_calls
        self._endpoint_catalog = build_endpoint_catalog()

    def answer(self, question: str) -> Dict[str, Any]:
        range_context = self._resolve_range_context(question)
        special_plan = self._build_priority_plan(question)
        special_used = special_plan is not None
        special_context = special_plan.context if special_plan else None
        plan_calls = special_plan.calls if special_plan else self._plan_calls(question, range_context)
        if not plan_calls:
            plan_calls = [
                EndpointCall(
                    endpoint="metrics_summary",
                    params={},
                    reason="Planificador sin respuesta; se usa resumen de métricas por defecto.",
                )
            ]
        self._apply_range_defaults(plan_calls, range_context)
        api_results = self._execute_plan_calls(plan_calls, special_context)
        if special_used:
            self._inject_focus_matches(api_results, special_context)
        if special_used and _is_customer_not_found(api_results):
            friendly_answer = _build_customer_not_found_answer(
                special_context.get("customer_focus") if special_context else None
            )
            return {
                "answer": friendly_answer,
                "calls": [self._to_public_dict(call, result) for call, result in zip(plan_calls, api_results)],
                "used": "api:special",
                "date_range": range_context,
            }
        answer = self._summarize(question, plan_calls, api_results, range_context)
        return {
            "answer": answer,
            "calls": [self._to_public_dict(call, result) for call, result in zip(plan_calls, api_results)],
            "used": "api:special" if special_used else "api",
            "date_range": range_context,
        }

    def _plan_calls(self, question: str, range_context: Dict[str, Any]) -> List[EndpointCall]:
        prompt = PLAN_TEMPLATE.format(
            endpoint_catalog=self._endpoint_catalog,
            max_calls=self.max_calls,
            question=question.strip(),
            current_datetime=_format_iso(_now_utc()),
            range_description=range_context["description"],
            range_start=range_context["start"],
            range_end=range_context["end"],
        )
        llm = self._planner_llm_factory()
        raw_response = llm.predict(prompt)
        logger.debug("Planner raw response: %s", raw_response)
        return parse_plan_response(raw_response, self.max_calls)

    def _execute_plan_calls(
        self,
        plan_calls: List[EndpointCall],
        special_context: Optional[Dict[str, Any]],
    ) -> List[ApiCallResult]:
        results: List[ApiCallResult] = []
        if not special_context:
            return [self.client.request(call.endpoint, params=call.params) for call in plan_calls]

        focus_name = special_context.get("customer_focus")

        for call in plan_calls:
            params = dict(call.params)
            if call.endpoint == CUSTOMER_ORDERS_ENDPOINT and focus_name:
                params.setdefault("customer_name", focus_name)
                call.params["customer_name"] = params["customer_name"]

            result = self.client.request(call.endpoint, params=params)
            results.append(result)

        return results

    def _inject_focus_matches(
        self,
        results: List[ApiCallResult],
        special_context: Optional[Dict[str, Any]],
    ) -> None:
        if not special_context:
            return
        focus_entities: Dict[str, List[int]] = special_context.get("focus_entities") or {}
        if not focus_entities:
            return
        for result in results:
            data = result.data
            if not isinstance(data, dict):
                continue
            if result.endpoint == CUSTOMER_ORDERS_ENDPOINT:
                orders = data.get("orders")
                if not isinstance(orders, list):
                    continue
                matches: Dict[str, Any] = {}
                if focus_entities.get("orders"):
                    matches["orders"] = [
                        order
                        for order in orders
                        if order.get("order_id") in focus_entities["orders"]
                    ]
                if focus_entities.get("samples"):
                    sample_hits = []
                    for order in orders:
                        for sample in order.get("samples", []):
                            if sample.get("sample_id") in focus_entities["samples"]:
                                sample_hits.append(
                                    {
                                        **sample,
                                        "order_id": order.get("order_id"),
                                    }
                                )
                    if sample_hits:
                        matches["samples"] = sample_hits
                if focus_entities.get("tests"):
                    test_hits = []
                    for order in orders:
                        for test in order.get("tests", []):
                            if test.get("test_id") in focus_entities["tests"]:
                                test_hits.append(
                                    {
                                        **test,
                                        "order_id": order.get("order_id"),
                                    }
                                )
                    if test_hits:
                        matches["tests"] = test_hits
                if matches:
                    data["focus_matches"] = matches
                elif any(focus_entities.values()):
                    data.setdefault(
                        "focus_matches",
                        {"note": "No matches found for the requested IDs within this customer summary."},
                    )
            elif result.endpoint in _ENTITY_DETAIL_ENDPOINT_TO_ENTITY:
                entity = _ENTITY_DETAIL_ENDPOINT_TO_ENTITY[result.endpoint]
                matches: Dict[str, Any] = {}
                if entity == "orders" and data.get("order"):
                    matches["orders"] = [data["order"]]
                    if data.get("samples"):
                        matches["samples"] = data["samples"]
                elif entity == "samples" and data.get("sample"):
                    matches["samples"] = [data["sample"]]
                    if data.get("tests"):
                        matches["tests"] = data["tests"]
                elif entity == "tests" and data.get("test"):
                    matches["tests"] = [data["test"]]
                if matches:
                    data["focus_matches"] = matches
    def _build_priority_plan(self, question: str) -> Optional[SpecialPlan]:
        return (
            self._build_global_kpi_plan(question)
            or self._build_customer_plan(question)
            or self._build_entity_detail_plan(question)
            or self._build_entity_state_plan(question)
        )

    def _build_global_kpi_plan(self, question: str) -> Optional[SpecialPlan]:
        lowered = question.lower()
        if not any(keyword in lowered for keyword in _GLOBAL_KPI_KEYWORDS):
            return None
        calls = [
            EndpointCall(
                endpoint="metrics_summary",
                params={},
                reason="Consultar KPIs globales solicitados por el usuario.",
            )
        ]
        context: Dict[str, Any] = {"intent": "global_kpi"}
        return SpecialPlan(calls=calls, context=context)

    def _build_customer_plan(self, question: str) -> Optional[SpecialPlan]:
        focus, topic = _extract_customer_focus(question)
        if not focus:
            return None
        focus_entities = _extract_entity_ids(question)
        params = {
            "match_strategy": "best",
            "match_threshold": 0.6,
            "include_samples": True,
            "include_tests": True,
            "limit_orders": 20,
        }
        calls = [
            EndpointCall(
                endpoint=CUSTOMER_ORDERS_ENDPOINT,
                params=params,
                reason=f"Consultar resumen de {topic or 'orders'} para el cliente '{focus}'.",
            )
        ]
        entity_calls = self._build_entity_detail_calls(focus_entities)
        calls.extend(entity_calls)
        context: Dict[str, Any] = {
            "customer_focus": focus,
            "customer_topic": topic or "orders",
            "focus_entities": focus_entities,
        }
        return SpecialPlan(calls=calls, context=context)

    def _build_entity_detail_plan(self, question: str) -> Optional[SpecialPlan]:
        focus_entities = _extract_entity_ids(question)
        for entity in ("orders", "samples", "tests"):
            ids = focus_entities.get(entity)
            if ids:
                config = _ENTITY_DETAIL_CONFIG[entity]
                params = {config["param"]: ids[0]}
                params.update(config["defaults"])
                calls = [
                    EndpointCall(
                        endpoint=config["endpoint"],
                        params=params,
                        reason=f"Obtener detalle del {entity[:-1]} {ids[0]}.",
                    )
                ]
                context: Dict[str, Any] = {"intent": "entity_detail", "focus_entities": {entity: ids}}
                return SpecialPlan(calls=calls, context=context)
        return None

    def _build_entity_detail_calls(self, focus_entities: Dict[str, List[int]]) -> List[EndpointCall]:
        calls: List[EndpointCall] = []
        for entity, config in _ENTITY_DETAIL_CONFIG.items():
            ids = focus_entities.get(entity)
            if not ids:
                continue
            params = {config["param"]: ids[0]}
            params.update(config["defaults"])
            calls.append(
                EndpointCall(
                    endpoint=config["endpoint"],
                    params=params,
                    reason=f"Obtener detalle del {entity[:-1]} {ids[0]} para enriquecer la respuesta.",
                )
            )
        return calls

    def _build_entity_state_plan(self, question: str) -> Optional[SpecialPlan]:
        entity = _detect_entity_keyword(question)
        if not entity:
            return None
        state_term = _detect_state_keyword(question)
        endpoint = _ENTITY_STATE_ENDPOINTS.get(entity)
        if not endpoint:
            return None
        calls = [
            EndpointCall(
                endpoint=endpoint,
                params={},
                reason=f"Consultar {entity} con estado solicitado ({state_term or 'general'}).",
            )
        ]
        context: Dict[str, Any] = {"intent": "entity_state", "entity": entity, "state_term": state_term}
        return SpecialPlan(calls=calls, context=context)

    def _summarize(
        self,
        question: str,
        calls: List[EndpointCall],
        results: List[ApiCallResult],
        range_context: Dict[str, Any],
    ) -> str:
        plan_summary_lines = []
        for call in calls:
            plan_summary_lines.append(f"- {call.endpoint} con params {json.dumps(call.params, ensure_ascii=False)}")
        api_payload = [
            {
                "endpoint": res.endpoint,
                "status_code": res.status_code,
                "error": res.error,
                "data": res.data,
            }
            for res in results
        ]
        prompt = SUMMARY_TEMPLATE.format(
            question=question.strip(),
            plan_summary="\n".join(plan_summary_lines),
            api_payload=json.dumps(api_payload, ensure_ascii=False, indent=2),
            range_description=range_context["description"],
            range_start=range_context["start"],
            range_end=range_context["end"],
        )
        llm = self._summarizer_llm_factory()
        response = llm.predict(prompt)
        response = _dedupe_blocks(response.strip())
        response = _wrap_tables(response)
        response = _normalize_duration_phrases(response)
        response = _normalize_hours_phrases(response)
        response = _dedupe_lines(response)
        if not response:
            response = "No response from model."
        if not response.lower().startswith("final answer"):
            response = f"Final Answer: {response.strip()}"
        return response

    @staticmethod
    def _to_public_dict(call: EndpointCall, result: ApiCallResult) -> Dict[str, Any]:
        payload = {
            "endpoint": call.endpoint,
            "params": call.params,
            "reason": call.reason,
            "status_code": result.status_code,
            "error": result.error,
        }
        if isinstance(result.data, (dict, list)):
            payload["data"] = result.data
        return payload

    def _resolve_range_context(self, question: str) -> Dict[str, Any]:
        q = question.lower()
        now = _now_utc()
        start: datetime
        end: datetime
        description: str
        assumed = False

        if "last month" in q:
            first_day_current = _floor_day(now).replace(day=1)
            prev_month_end = first_day_current - timedelta(seconds=1)
            start = first_day_current - timedelta(days=first_day_current.day)
            start = start.replace(day=1)
            end = prev_month_end
            description = "last month"
        elif "this month" in q:
            start = _floor_day(now).replace(day=1)
            end = now
            description = "this month"
        elif "last week" in q:
            current_week_start = _floor_day(now) - timedelta(days=_floor_day(now).weekday())
            start = current_week_start - timedelta(days=7)
            end = current_week_start - timedelta(seconds=1)
            description = "last week"
        elif "this week" in q:
            start = _floor_day(now) - timedelta(days=_floor_day(now).weekday())
            end = now
            description = "this week"
        elif "past week" in q:
            end = now
            start = end - timedelta(days=7)
            description = "past week"
        elif "last 7 days" in q:
            end = now
            start = end - timedelta(days=7)
            description = "last 7 days"
        else:
            end = now
            start = end - timedelta(days=7)
            description = "last 7 days (default)"
            assumed = True

        if description in {"this week", "this month"}:
            range_end = _format_iso(end)
        else:
            range_end = _format_iso(_end_of_day(end))

        return {
            "start": _format_iso(_floor_day(start)),
            "end": range_end,
            "description": description,
            "assumed": assumed,
        }

    def _apply_range_defaults(self, calls: List[EndpointCall], range_context: Dict[str, Any]) -> None:
        for call in calls:
            spec = ENDPOINT_SPECS.get(call.endpoint)
            if not spec:
                continue
            for param in spec.params:
                pname = param.name.lower()
                if "date" not in pname:
                    continue
                if "from" in pname and param.name not in call.params:
                    call.params[param.name] = range_context["start"]
                elif "to" in pname and param.name not in call.params:
                    call.params[param.name] = range_context["end"]



def _default_llm_factory():
    """Lazy factory to avoid importing LangChain when running unit tests without it."""

    try:
        from langchain_community.chat_models import ChatOllama  # type: ignore
    except ModuleNotFoundError:
        try:
            from langchain.chat_models import ChatOllama  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ImportError(
                "LangChain no está instalado. Instala langchain y langchain-community para usar el orquestador."
            ) from exc
    return ChatOllama(model="mistral:instruct", temperature=0)


def _dedupe_blocks(text: str) -> str:
    if not text:
        return text
    blocks = re.split(r"\n\s*\n", text)
    seen: set[str] = set()
    deduped: List[str] = []
    for block in blocks:
        normalized = block.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        deduped.append(normalized)
    return "\n\n".join(deduped)


def _wrap_tables(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines()
    result: List[str] = []
    table_buffer: List[str] = []

    def flush_table():
        nonlocal table_buffer
        if len(table_buffer) >= 2:
            for row in table_buffer:
                result.append(f"`{row}`")
        else:
            result.extend(table_buffer)
        table_buffer = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if table_buffer:
                flush_table()
            result.append(line)
            continue
        if "|" in line and not stripped.startswith("-"):
            table_buffer.append(line)
        else:
            if table_buffer:
                flush_table()
            result.append(line)
    if table_buffer:
        flush_table()
    return "\n".join(result) + "\n"


_DURATION_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:day|days|d[ií]a|d[ií]as)\b", re.IGNORECASE)
_HOURS_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", re.IGNORECASE)

_GLOBAL_KPI_KEYWORDS = {
    "total samples",
    "total tests",
    "total customers",
    "total reports",
    "overall samples",
    "overall tests",
    "kpi",
    "kpis",
    "summary metrics",
    "metrics summary",
}

_ENTITY_KEYWORDS = {
    "orders": ["order", "orders", "orden", "ordenes", "órdenes"],
    "samples": ["sample", "samples", "muestra", "muestras"],
    "tests": ["test", "tests", "prueba", "pruebas"],
}

_ENTITY_STATE_ENDPOINTS = {
    "orders": "analytics_orders_overdue",
    "samples": "metrics_samples_overview",
    "tests": "metrics_tests_overview",
}

_ENTITY_DETAIL_CONFIG = {
    "orders": {
        "endpoint": "entities_order_detail",
        "param": "order_id",
        "defaults": {"include_samples": True, "include_tests": False},
    },
    "samples": {
        "endpoint": "entities_sample_full",
        "param": "sample_id",
        "defaults": {"include_tests": True, "include_batches": True},
    },
    "tests": {
        "endpoint": "entities_test_full",
        "param": "test_id",
        "defaults": {
            "include_sample": True,
            "include_order": True,
            "include_batches": True,
            "include_raw_worksheet": False,
        },
    },
}
_ENTITY_DETAIL_ENDPOINT_TO_ENTITY = {
    config["endpoint"]: entity for entity, config in _ENTITY_DETAIL_CONFIG.items()
}

_STATE_KEYWORDS = {
    "overdue": [
        "overdue",
        "delayed",
        "late",
        "atrasada",
        "vencida",
        "vencidas",
    ],
    "ready": [
        "ready to report",
        "ready for report",
        "ready for reporting",
        "listo para reportar",
        "listos para reportar",
        "ready to deliver",
    ],
    "open": [
        "open",
        "pending",
        "in progress",
        "en progreso",
        "pendiente",
        "pending completion",
        "waiting",
    ],
}

_STOPWORD_TOKENS = {
    "ready",
    "report",
    "reports",
    "sample",
    "samples",
    "test",
    "tests",
    "order",
    "orders",
    "pending",
    "overdue",
    "total",
    "overall",
    "average",
    "open",
    "what",
    "happened",
    "to",
    "from",
    "the",
    "need",
    "update",
    "status",
    "on",
}


def _format_decimal_days(days_value: float) -> str:
    whole_days = int(days_value)
    fractional = max(days_value - whole_days, 0.0)
    hours = round(fractional * 24)
    if hours == 24:
        whole_days += 1
        hours = 0
    return f"{whole_days}d {hours}h"


def _normalize_duration_phrases(text: str) -> str:
    if not text:
        return text

    def _replacer(match: re.Match[str]) -> str:
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            return match.group(0)
        return _format_decimal_days(value)

    return _DURATION_PATTERN.sub(_replacer, text)


def _normalize_hours_phrases(text: str) -> str:
    if not text:
        return text

    def _replacer(match: re.Match[str]) -> str:
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            return match.group(0)
        if value < 24:
            return match.group(0)
        return _format_decimal_days(value / 24)

    return _HOURS_PATTERN.sub(_replacer, text)


def _dedupe_lines(text: str) -> str:
    if not text:
        return text
    seen: set[str] = set()
    result: List[str] = []
    for line in text.splitlines():
        key = line.strip().lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(line)
    return "\n".join(result)


_TOPIC_PATTERN = r"open orders?|orders? open|pending orders?|orders?|order|samples?|sample|tests?|test|muestras?|pruebas?"
_CUSTOMER_FOCUS_PATTERNS = [
    re.compile(rf"(?P<name>.+?)\s+(?P<topic>{_TOPIC_PATTERN})\b", re.IGNORECASE),
    re.compile(
        rf"(?P<topic>{_TOPIC_PATTERN})\s+(?:(?:\S+\s+){{0,3}})?(?:for|from|of|para|de|del)\s+(?P<name>.+)",
        re.IGNORECASE,
    ),
]

_QUESTION_PREFIXES = {
    "how",
    "cuantas",
    "cuantos",
    "cuántas",
    "cuántos",
    "que",
    "qué",
    "what",
    "which",
    "cual",
    "cuál",
}


def _extract_customer_focus(question: str) -> tuple[Optional[str], Optional[str]]:
    text = question.strip()
    topic_hint = _infer_topic(text)
    name_by_prep = _extract_name_after_preposition(text)
    if name_by_prep:
        return name_by_prep, topic_hint
    for pattern in _CUSTOMER_FOCUS_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = match.group("name") or ""
        topic = match.group("topic") or ""
        cleaned_name = _clean_customer_name(name)
        if not _is_probable_customer_name(cleaned_name):
            continue
        normalized_topic = _normalize_topic(topic) or topic_hint
        if not normalized_topic:
            normalized_topic = "orders"
        return cleaned_name, normalized_topic
    return None, None


def _clean_customer_name(name: str) -> str:
    cleaned = name.strip(' ?!.:,;"\'()\u00bf\u00a1')
    # Remove trailing filler words
    for suffix in ("orders", "samples", "tests", "open", "pending", "overdue"):
        if cleaned.lower().endswith(f" {suffix}"):
            cleaned = cleaned[: -len(suffix) - 1].strip()
    lowered = cleaned.lower()
    for delimiter in (
        " with ",
        " that ",
        " which ",
        " whose ",
        " having ",
        " status",
        " acerca de ",
        " sobre ",
    ):
        idx = lowered.find(delimiter.strip())
        if idx != -1:
            cleaned = cleaned[:idx].strip()
            lowered = cleaned.lower()
    cleaned = re.sub(r"^(?:what|which|who|que|qué|cual|cuál)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned

def _is_probable_customer_name(name: str) -> bool:
    if not name or len(name) < 3:
        return False
    lowered = name.lower()
    first_word = lowered.split()[0]
    if first_word in _QUESTION_PREFIXES:
        return False
    tokens = re.findall(r"[a-zñáéíóú]+", lowered)
    if not tokens:
        return False
    if all(token in _STOPWORD_TOKENS for token in tokens):
        return False
    if not any(char.isalpha() and char.isupper() for char in name):
        if len(tokens) == 1 and len(tokens[0]) <= 4:
            return False
    return any(char.isalpha() for char in name)


def _normalize_topic(raw_topic: Optional[str]) -> Optional[str]:
    if not raw_topic:
        return "orders"
    text = raw_topic.lower()
    if "muestra" in text or "sample" in text:
        return "samples"
    if "prueba" in text or "test" in text:
        return "tests"
    return "orders"


def _infer_topic(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ("sample", "samples", "muestra", "muestras")):
        return "samples"
    if any(keyword in lowered for keyword in ("test", "tests", "prueba", "pruebas")):
        return "tests"
    return "orders"


def _extract_name_after_preposition(text: str) -> Optional[str]:
    match = re.search(
        r"(?:order|orders|sample|samples|test|tests)\s+(?:from|for|by|para|de|del)\s+([A-Za-z0-9][^?.!,;]*)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    candidate = match.group(1).strip()
    candidate = re.split(r"(?i)\b(order|sample|test)s?\b", candidate, 1)[0].strip()
    candidate = _clean_customer_name(candidate)
    if _is_probable_customer_name(candidate):
        return candidate
    return None


def _is_customer_not_found(results: List[ApiCallResult]) -> bool:
    for result in results:
        if result.status_code == 404:
            return True
    return False


def _build_customer_not_found_answer(customer_name: Optional[str]) -> str:
    target = f'"{customer_name}"' if customer_name else "the requested customer"
    message = (
        f"I couldn't find any customer matching {target}. "
        "Please double-check the spelling or provide a different name."
    )
    return f"Final Answer: {message}"


def _extract_entity_ids(question: str) -> Dict[str, List[int]]:
    text = question.lower()
    entities = {"orders": _find_numbers(text, ["order", "orden"]), "samples": _find_numbers(text, ["sample", "muestra"]), "tests": _find_numbers(text, ["test", "prueba"])}
    return entities


def _find_numbers(text: str, keywords: List[str]) -> List[int]:
    matches: List[int] = []
    pattern = re.compile(
        r"(?:"
        + "|".join(re.escape(keyword) for keyword in keywords)
        + r")\s*(?:id|number|#|número|nro|num)?\s*(\d+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        try:
            matches.append(int(match.group(1)))
        except ValueError:
            continue
    return matches


def _detect_entity_keyword(question: str) -> Optional[str]:
    lowered = question.lower()
    for entity, keywords in _ENTITY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return entity
    return None


def _detect_state_keyword(question: str) -> Optional[str]:
    lowered = question.lower()
    for state, keywords in _STATE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lowered:
                return state
    return None




CUSTOMER_ORDERS_ENDPOINT = "analytics_customers_orders_summary"


__all__ = ["ApiOrchestrator", "EndpointCall", "parse_plan_response", "extract_json_block"]
