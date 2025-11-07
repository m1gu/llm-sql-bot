"""
Routing layer that selects between the simple NL2SQL chain and a LangChain SQL agent.
"""

from __future__ import annotations

import logging
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

try:
    from langchain.agents import AgentType, initialize_agent  # type: ignore
    from langchain.agents.agent_toolkits import SQLDatabaseToolkit  # type: ignore
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ImportError(
        "LangChain agents components are not available. Asegurate de tener "
        "langchain y langchain-community instalados en versiones compatibles."
    ) from exc

try:
    from langchain_community.chat_models import ChatOllama  # type: ignore
    from langchain_community.utilities import SQLDatabase  # type: ignore
except ModuleNotFoundError:
    from langchain.chat_models import ChatOllama  # type: ignore
    from langchain.utilities import SQLDatabase  # type: ignore

from langchain.tools import Tool
from langchain_core.exceptions import OutputParserException
# Ensure project root is importable when running as script
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.agent.nl2sql_chain import (
    AGGREGATION_HINT,
    ALLOWED_TABLES,
    EXAMPLE_HINT,
    GLOSSARY_HINT,
    POSTGRESQL_HINT,
    RELATIONSHIP_HINT,
    SCHEMA_HINT,
    STATE_PRIORITY_HINT,
    SYSTEM_HINT,
    answer_question as chain_answer,
    _validate_tables as chain_validate_tables,
)  # noqa: E402
from app.db.pg import get_engine, run_sql  # noqa: E402

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


COMPLEX_KEYWORDS = {
    "promedio",
    "media",
    "por region",
    "por país",
    "por pais",
    "ultimo mes",
    "último mes",
    "top",
    "comparar",
    "tendencia",
    "variacion",
    "por categoria",
    "por canal",
}

SIMPLE_PATTERNS = [
    re.compile(r"\b(count|cuent[ao]s?|total)\b", re.IGNORECASE),
    re.compile(r"\b(existe|hay)\b", re.IGNORECASE),
]

def _agent_prefix() -> str:
    sections = [
        SYSTEM_HINT.strip(),
        STATE_PRIORITY_HINT,
        RELATIONSHIP_HINT,
        AGGREGATION_HINT,
        POSTGRESQL_HINT,
        EXAMPLE_HINT,
        "Cuando concluyas, responde con el formato `Final Answer: ...` resumiendo la metrica solicitada.",
    ]
    if SCHEMA_HINT:
        sections.append("### Schema\n")
        sections.append(SCHEMA_HINT.strip())
    if GLOSSARY_HINT:
        sections.append("### Glossary\n")
        sections.append(GLOSSARY_HINT.strip())
    sections.append(
        "Usa únicamente las herramientas disponibles (list_tables, get_table_info, "
        "sql_db_query) para razonar paso a paso. Nunca inventes datos."
    )
    return "\n\n".join(sections)

def route_and_answer(question: str) -> Dict[str, Any]:
    """
    Decide si usar el chain simple o el agente SQL según la pregunta.
    """
    normalized = question.lower()
    if _should_use_chain(normalized):
        logger.info("Routing question to NL2SQL chain.")
        result = chain_answer(question)
        result["used"] = "chain"
        return result

    logger.info("Routing question to SQL agent.")
    agent = _get_agent()
    response, steps = _invoke_agent(agent, question)
    sql, rows_preview = _extract_sql_and_rows(steps)
    placeholder_message = _detect_placeholder(sql)
    validation_message = chain_validate_tables(sql) if sql and not placeholder_message else None
    # Si no se encontró SQL en pasos, intenta parsear del output final
    if placeholder_message:
        return {
            "answer": placeholder_message,
            "sql": "",
            "rows_preview": rows_preview,
            "used": "agent",
        }

    if not sql:
        sql = _extract_sql_from_text(response)
        placeholder_message = _detect_placeholder(sql)
        if placeholder_message:
            return {
                "answer": placeholder_message,
                "sql": "",
                "rows_preview": rows_preview,
                "used": "agent",
            }
        if sql and not validation_message:
            try:
                rows_preview = run_sql(sql)
            except Exception as exc:
                return {
                    "answer": f"La consulta generada falló al ejecutarse: {exc}",
                    "sql": sql,
                    "rows_preview": rows_preview,
                    "used": "agent",
                }
    elif validation_message:
        return {
            "answer": validation_message,
            "sql": sql,
            "rows_preview": rows_preview,
            "used": "agent",
        }

    if sql and not validation_message:
        validation_message = chain_validate_tables(sql)
        if validation_message:
            return {
                "answer": validation_message,
                "sql": sql,
                "rows_preview": rows_preview,
                "used": "agent",
            }

    raw_output = response.strip() if isinstance(response, str) else str(response)
    fallback_needed = not raw_output or raw_output.lower().startswith("could not parse")
    if fallback_needed:
        if rows_preview:
            answer_body = _compose_answer("", sql, rows_preview)
        elif sql:
            answer_body = f"No se interpretó la respuesta del agente. Consulta generada: {sql}"
        else:
            answer_body = "No se pudo interpretar la respuesta del agente. Reformula la pregunta o revisa el contexto."
    else:
        answer_body = _compose_answer(raw_output, sql, rows_preview)

    answer = _ensure_final_prefix(answer_body)
    return {
        "answer": answer,
        "sql": sql,
        "rows_preview": rows_preview,
        "used": "agent",
    }


def _should_use_chain(question: str) -> bool:
    if any(keyword in question for keyword in COMPLEX_KEYWORDS):
        return False
    return any(pattern.search(question) for pattern in SIMPLE_PATTERNS)


@lru_cache(maxsize=1)
def _get_agent():
    engine = get_engine()
    sql_db = SQLDatabase(engine=engine)
    llm = ChatOllama(model="mistral:instruct", temperature=0)
    toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)
    tools = _wrap_sql_toolkit(toolkit)
    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        agent_kwargs={"prefix": _agent_prefix()},
        return_intermediate_steps=True,
        max_iterations=6,
        early_stopping_method="generate",
    )
    agent.max_iterations = 6  # type: ignore[attr-defined]
    agent.max_execution_time = 45  # type: ignore[attr-defined]
    return agent


def _invoke_agent(agent, question: str) -> Tuple[str, List[Any]]:
    try:
        result = agent.invoke({"input": question})
    except OutputParserException as exc:
        logger.warning("El agente no pudo interpretar la salida: %s", exc)
        return str(exc), []
    if isinstance(result, dict):
        steps = result.get("intermediate_steps", [])
        _log_steps(steps)
        return result.get("output", "").strip(), steps
    return str(result), []


def _extract_sql_and_rows(steps: List[Any]) -> Tuple[str, List[Dict[str, Any]]]:
    sql = ""
    rows: List[Dict[str, Any]] = []
    for step in steps:
        if isinstance(step, tuple) and len(step) == 2:
            action, observation = step
            tool = getattr(action, "tool", "")
            tool_input = getattr(action, "tool_input", "")
            if tool == "sql_db_query" and isinstance(tool_input, str):
                sql = _strip_fences(tool_input)
                logger.info("Sanitized SQL from agent: %s", sql)
                if isinstance(observation, list):
                    rows = observation
                else:
                    rows = _ensure_list_of_dict(observation)
    return sql, rows


SQL_PATTERN = re.compile(r"SELECT\s.+?(?:;|\Z)", re.IGNORECASE | re.DOTALL)


def _extract_sql_from_text(text: str) -> str:
    match = SQL_PATTERN.search(text)
    if not match:
        return ""
    return _strip_fences(match.group(0))


def _ensure_list_of_dict(observation: Any) -> List[Dict[str, Any]]:
    if isinstance(observation, list):
        if observation and isinstance(observation[0], dict):
            return observation  # type: ignore[return-value]
        return [{"result": str(observation)}]
    if isinstance(observation, dict):
        return [observation]
    if isinstance(observation, str):
        return [{"result": observation}]
    return []


def _compose_answer(output: str, sql: str, rows: List[Dict[str, Any]]) -> str:
    if rows:
        first = rows[0]
        summary = ", ".join(f"{k}: {v}" for k, v in first.items())
        return f"{summary} (SQL ejecutada: {sql})"
    if output:
        return output.strip()
    return "No se obtuvo una respuesta del agente."


def _strip_fences(sql: str) -> str:
    trimmed = sql.strip()
    if trimmed.startswith("```"):
        trimmed = trimmed[3:]
        trimmed = trimmed.lstrip()
        trimmed = re.sub(r"^[a-zA-Z0-9_]*\r?\n?", "", trimmed)
    if trimmed.endswith("```"):
        trimmed = trimmed[:-3]
    trimmed = trimmed.strip("`")
    trimmed = re.sub(r"^Action Input:\s*", "", trimmed, flags=re.IGNORECASE)
    trimmed = re.sub(r"^Action:\s*", "", trimmed, flags=re.IGNORECASE)
    return trimmed.strip()


def _log_steps(steps: List[Any]) -> None:
    for idx, step in enumerate(steps, start=1):
        if isinstance(step, tuple) and len(step) == 2:
            action, observation = step
            tool = getattr(action, "tool", "")
            tool_input = getattr(action, "tool_input", "")
            logger.info("Step %s - tool: %s input: %s", idx, tool, tool_input)
            if observation:
                logger.info("Step %s - observation: %s", idx, observation)


def _ensure_final_prefix(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "Final Answer: No se pudo generar una respuesta."
    if stripped.lower().startswith("final answer"):
        return stripped
    return f"Final Answer: {stripped}"


def _detect_placeholder(sql: str) -> Optional[str]:
    if not sql:
        return None
    lowered = sql.lower()
    sanitized = sql.strip()
    if "<the" in lowered or sanitized.startswith("<") or "checked sql query" in lowered:
        return "La consulta propuesta contiene marcadores de posición y no se ejecutó. Solicita al modelo que genere SQL lista para ejecutar."
    return None


FORBIDDEN_PATTERNS = [
    ("date_format", r"\bdate_format\b"),
    ("date_sub", r"\bdate_sub\b"),
    ("now(", r"\bnow\s*\("),
    ("backticks", r"`"),
]


def _detect_forbidden_syntax(sql: str) -> Optional[str]:
    lowered = sql.lower()
    for name, pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, lowered):
            return f"La consulta incluye sintaxis no valida para PostgreSQL ({name}). Usa funciones como date_trunc/extract/interval."
    return None


def _wrap_sql_toolkit(toolkit: SQLDatabaseToolkit):
    wrapped_tools = []
    for tool in toolkit.get_tools():
        if tool.name == "sql_db_query":

            def wrapped(query: str, *, _tool=tool):
                cleaned = _strip_fences(query)
                placeholder_msg = _detect_placeholder(cleaned)
                if placeholder_msg:
                    raise OutputParserException(placeholder_msg)
                validation_msg = chain_validate_tables(cleaned)
                if validation_msg:
                    raise OutputParserException(validation_msg)
                forbidden = _detect_forbidden_syntax(cleaned)
                if forbidden:
                    raise OutputParserException(forbidden)
                try:
                    return _tool.run(cleaned)
                except Exception as exc:
                    raise OutputParserException(f"Error ejecutando SQL: {exc}") from exc

            wrapped_tools.append(
                Tool(
                    name=tool.name,
                    func=wrapped,
                    description=tool.description,
                )
            )
        else:
            wrapped_tools.append(tool)
    return wrapped_tools


if __name__ == "__main__":
    sample = route_and_answer("Cual es el promedio de ventas por region en el ultimo mes?")
    print(sample)
