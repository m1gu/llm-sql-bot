"""Agent orchestration layer that plans and executes API calls instead of SQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

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
Produce una respuesta única (no repitas la información ni generes múltiples bloques). Escribe todo en inglés (puedes usar tablas Markdown) y termina con una sola línea `Final Answer: ...`.
"""


@dataclass
class EndpointCall:
    endpoint: str
    params: Dict[str, Any]
    reason: str


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
        plan_calls = self._plan_calls(question, range_context)
        if not plan_calls:
            plan_calls = [
                EndpointCall(
                    endpoint="metrics_summary",
                    params={},
                    reason="Planificador sin respuesta; se usa resumen de métricas por defecto.",
                )
            ]
        self._apply_range_defaults(plan_calls, range_context)
        api_results = [self.client.request(call.endpoint, params=call.params) for call in plan_calls]
        answer = self._summarize(question, plan_calls, api_results, range_context)
        return {
            "answer": answer,
            "calls": [self._to_public_dict(call, result) for call, result in zip(plan_calls, api_results)],
            "used": "api",
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


__all__ = ["ApiOrchestrator", "EndpointCall", "parse_plan_response", "extract_json_block"]
