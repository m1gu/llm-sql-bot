"""Agent orchestration layer that plans and executes API calls instead of SQL."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.api.client import ApiCallResult, DownloaderApiClient
from app.api.endpoints import ENDPOINT_SPECS, build_endpoint_catalog

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


PLAN_TEMPLATE = """Eres un analista de laboratorio. Contestas preguntas usando los endpoints REST disponibles.

Endpoints soportados:
{endpoint_catalog}

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

Escribe la respuesta final en inglés, mencionando claramente qué datos consultaste. Puedes incluir tablas Markdown cuando ayuden a resumir resultados, no es necesario convertir todo a prosa.
Si hubo errores, indícalos. Finaliza siempre con el formato `Final Answer: ...`.
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
        plan_calls = self._plan_calls(question)
        if not plan_calls:
            plan_calls = [
                EndpointCall(
                    endpoint="metrics_summary",
                    params={},
                    reason="Planificador sin respuesta; se usa resumen de métricas por defecto.",
                )
            ]
        api_results = [self.client.request(call.endpoint, params=call.params) for call in plan_calls]
        answer = self._summarize(question, plan_calls, api_results)
        return {
            "answer": answer,
            "calls": [self._to_public_dict(call, result) for call, result in zip(plan_calls, api_results)],
            "used": "api",
        }

    def _plan_calls(self, question: str) -> List[EndpointCall]:
        prompt = PLAN_TEMPLATE.format(
            endpoint_catalog=self._endpoint_catalog,
            max_calls=self.max_calls,
            question=question.strip(),
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
        )
        llm = self._summarizer_llm_factory()
        response = llm.predict(prompt)
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


__all__ = ["ApiOrchestrator", "EndpointCall", "parse_plan_response", "extract_json_block"]
