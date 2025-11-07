"""
One-shot natural language to SQL chain using LangChain and Ollama.
"""

from __future__ import annotations

import logging
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from langchain_community.chat_models import ChatOllama  # type: ignore
    from langchain_community.utilities import SQLDatabase  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - compatibility with older LangChain
    from langchain.chat_models import ChatOllama  # type: ignore
    from langchain.utilities import SQLDatabase  # type: ignore

try:
    from langchain_experimental.sql import SQLDatabaseChain  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
    from langchain.chains.sql_database.base import SQLDatabaseChain  # type: ignore

# Ensure project root is on sys.path when executing as a script
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.db.pg import get_engine, run_sql


logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


PROMPTS_DIR = PROJECT_ROOT / "app" / "prompts"
SYSTEM_BASE_PATH = PROMPTS_DIR / "system_base.md"
SCHEMA_PATH = PROMPTS_DIR / "schema.md"
GLOSSARY_PATH = PROMPTS_DIR / "glossary.md"

if SYSTEM_BASE_PATH.exists():
    SYSTEM_HINT = SYSTEM_BASE_PATH.read_text(encoding="utf-8")
else:
    SYSTEM_HINT = (
        "Eres un analista experto en PostgreSQL. Responde solo con consultas SELECT "
        "seguras. Si la pregunta es ambigua o faltan datos, solicita una aclaracion breve "
        "antes de generar la SQL. Usa LIMIT si el resultado puede ser grande."
    )

SCHEMA_HINT = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
GLOSSARY_HINT = GLOSSARY_PATH.read_text(encoding="utf-8") if GLOSSARY_PATH.exists() else ""
TABLE_HEADER_PATTERN = re.compile(r"^##\s+([a-zA-Z_][\w]*)", re.MULTILINE)
ALLOWED_TABLES = {name.lower() for name in TABLE_HEADER_PATTERN.findall(SCHEMA_HINT)}
STATE_PRIORITY_HINT = (
    "Prioriza usar la columna 'state' para determinar si un test u orden esta completado "
    "(por ejemplo valores 'REPORTED', 'COMPLETED'). Evita depender del campo 'has_report' "
    "a menos que el usuario lo pida explicitamente."
)
RELATIONSHIP_HINT = (
    "Relaciones clave: orders.id <-> samples.order_id y samples.id <-> tests.sample_id. "
    "No existe la columna tests.order_id; para combinar orders con tests siempre pasa por samples."
)
AGGREGATION_HINT = (
    "Para promedios mensuales o trimestrales, calcula primero los conteos por mes con date_trunc('month', ...)"
    " y despues aplica AVG sobre esos conteos agrupados por la dimension solicitada."
)
POSTGRESQL_HINT = (
    "Trabaja unicamente con sintaxis de PostgreSQL. Usa funciones como date_trunc('month', ...), "
    "extract(year from ...), interval '3 months' y CURRENT_DATE. Evita funciones de otros motores como "
    "DATE_FORMAT, DATE_SUB, NOW()."
)
EXAMPLE_HINT = (
    "Ejemplo esperado:\n"
    "Pregunta: What is the average number of completed tests per state per month over the last quarter?\n"
    "SQL ejemplo:\n"
    "WITH monthly_counts AS (\n"
    "  SELECT o.state,\n"
    "         date_trunc('month', o.date_completed) AS month_bucket,\n"
    "         COUNT(*) AS test_count\n"
    "  FROM tests t\n"
    "  JOIN samples s ON t.sample_id = s.id\n"
    "  JOIN orders o ON s.order_id = o.id\n"
    "  WHERE o.state IN ('COMPLETED', 'REPORTED')\n"
    "    AND o.date_completed >= date_trunc('quarter', current_date) - interval '3 months'\n"
    "  GROUP BY o.state, month_bucket\n"
    ")\n"
    "SELECT state, AVG(test_count)::numeric(10,2) AS avg_tests_per_month\n"
    "FROM monthly_counts\n"
    "GROUP BY state;\n"
    "Respuesta ejemplo: Final Answer: COMPLETED: 19.00 tests/month; REPORTED: 2098.80 tests/month."
)


@lru_cache(maxsize=1)
def _get_chain() -> SQLDatabaseChain:
    engine = get_engine()
    sql_db = SQLDatabase(engine=engine)
    system_prompt = _compose_system_prompt()
    llm = ChatOllama(model="mistral:instruct", temperature=0, system=system_prompt)
    chain = SQLDatabaseChain.from_llm(
        llm,
        sql_db,
        verbose=False,
        return_intermediate_steps=True,
    )
    chain.return_direct = True  # type: ignore[attr-defined]
    return chain


def answer_question(question: str) -> Dict[str, Any]:
    chain = _get_chain()
    logger.info("Running NL2SQL chain for question: %s", question)
    try:
        result = chain(question)
    except Exception as exc:
        logger.warning("La cadena falló, intentando recuperar SQL desde el error.")
        intermediate = getattr(exc, "intermediate_steps", [])
        raw_output = str(exc)
        sql, rows_preview = _extract_intermediate(intermediate)
        if not sql:
            sql = _extract_sql_from_text(raw_output)
        try:
            rows = _execute_sql(sql)
        except ValueError as validation_error:
            answer_text = str(validation_error)
            return {
                "answer": answer_text,
                "sql": sql,
                "rows_preview": rows_preview,
            }
        answer_text = _compose_answer(raw_output, sql, rows if rows else rows_preview)
        return {
            "answer": answer_text,
            "sql": sql,
            "rows_preview": rows if rows else rows_preview,
        }  # pragma: no cover - flow solo en fallos

    if isinstance(result, str):
        raw_output = result
        intermediate = []
    elif isinstance(result, dict):
        raw_output = result.get("result", "")
        intermediate = result.get("intermediate_steps", [])
    else:
        raw_output = str(result)
        intermediate = []

    sql, rows_preview = _extract_intermediate(intermediate)
    if not sql:
        sql = _extract_sql_from_text(raw_output)
    try:
        rows = _execute_sql(sql)
    except ValueError as validation_error:
        return {
            "answer": str(validation_error),
            "sql": sql,
            "rows_preview": rows_preview,
        }
    answer_text = _compose_answer(raw_output, sql, rows if rows else rows_preview)

    return {
        "answer": answer_text,
        "sql": sql,
        "rows_preview": rows if rows else rows_preview,
    }


def _execute_sql(sql: str) -> List[Dict[str, Any]]:
    if not sql:
        logger.warning("No se pudo extraer una consulta SQL de la respuesta.")
        return []
    invalid_message = _validate_tables(sql)
    if invalid_message:
        logger.warning(invalid_message)
        raise ValueError(invalid_message)
    try:
        return run_sql(sql)
    except Exception as exc:  # pragma: no cover
        logger.error("Error ejecutando SQL generada: %s", exc)
        raise


def _extract_intermediate(
    steps: List[Any],
) -> Tuple[str, List[Any]]:
    sql = ""
    rows: List[Any] = []
    for step in steps:
        if isinstance(step, dict):
            sql = step.get("sql", "") or sql
            step_result = step.get("result")
            if isinstance(step_result, list):
                rows = step_result
            elif step_result is not None:
                rows = [step_result]
        elif isinstance(step, (list, tuple)) and len(step) == 2:
            candidate_sql, candidate_rows = step
            if isinstance(candidate_sql, str):
                sql = candidate_sql
            if isinstance(candidate_rows, list):
                rows = candidate_rows
        elif isinstance(step, str):
            extracted = _extract_sql_from_text(step)
            if extracted:
                sql = extracted
    return _strip_fences(sql), rows


SQL_PATTERN = re.compile(r"SELECT\s.+?(?:;|\Z)", re.IGNORECASE | re.DOTALL)


def _extract_sql_from_text(text: str) -> str:
    match = SQL_PATTERN.search(text)
    if not match:
        return ""
    return match.group(0)


def _strip_fences(sql: str) -> str:
    if not sql:
        return sql
    trimmed = sql.strip()
    if trimmed.startswith("```"):
        trimmed = trimmed.strip("`")
    return trimmed.strip("`").strip()


def _compose_system_prompt() -> str:
    sections = [
        SYSTEM_HINT.strip(),
        STATE_PRIORITY_HINT,
        RELATIONSHIP_HINT,
        AGGREGATION_HINT,
        POSTGRESQL_HINT,
        EXAMPLE_HINT,
    ]
    if SCHEMA_HINT:
        sections.append("### Schema\n")
        sections.append(SCHEMA_HINT.strip())
    if GLOSSARY_HINT:
        sections.append("### Glossary\n")
        sections.append(GLOSSARY_HINT.strip())
    return "\n\n".join(sections)


def _compose_answer(raw_output: str, sql: str, rows: List[Any]) -> str:
    if rows:
        first = rows[0]
        if isinstance(first, dict) and first:
            key, value = next(iter(first.items()))
            return f"{key}: {value} (SQL ejecutada: {sql})"
        return f"Resultado: {rows} (SQL ejecutada: {sql})"
    cleaned = raw_output.strip()
    if cleaned.startswith("(") and "psycopg2" in cleaned:
        return "No se pudo ejecutar la consulta generada."
    return cleaned


def _validate_tables(sql: str) -> str | None:
    if not ALLOWED_TABLES:
        return None
    cte_names = _extract_cte_names(sql)
    mentioned = _extract_table_tokens(sql) - cte_names
    disallowed = mentioned - ALLOWED_TABLES
    if disallowed:
        return (
            "La consulta generada refiere a tablas desconocidas: "
            f"{', '.join(sorted(disallowed))}. Solicita aclaración al usuario."
        )
    if re.search(r"\btests\.order_id\b", sql, flags=re.IGNORECASE):
        return (
            "La consulta intenta usar la columna tests.order_id, que no existe. "
            "Une tests con samples mediante tests.sample_id y luego samples con orders mediante samples.order_id."
        )
    return None


def _extract_table_tokens(sql: str) -> set[str]:
    tokens = re.finditer(r"[A-Za-z_][\w]*|[(),]", sql)
    depth = 0
    result: list[str] = []
    tokens = list(tokens)
    length = len(tokens)
    idx = 0
    while idx < length:
        token = tokens[idx].group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(depth - 1, 0)
        else:
            token_lower = token.lower()
            if token_lower in ("from", "join") and depth == 0:
                idx += 1
                while idx < length:
                    next_token = tokens[idx].group(0)
                    if next_token in (",",):
                        idx += 1
                        continue
                    if re.match(r"[A-Za-z_][\w]*", next_token):
                        result.append(next_token.lower())
                    break
        idx += 1
    return set(result)


def _extract_cte_names(sql: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"\bWITH\s+([a-zA-Z_][\w]*)\s+AS\s*\(", sql, flags=re.IGNORECASE):
        names.add(match.group(1).lower())
    for match in re.finditer(r",\s*([a-zA-Z_][\w]*)\s+AS\s*\(", sql):
        names.add(match.group(1).lower())
    return names


if __name__ == "__main__":
    try:
        sample = answer_question("Cuantas filas hay en la tabla customers?")
    except Exception as exc:  # pragma: no cover - demo guard
        logger.error("Fallo la demostracion de nl2sql_chain: %s", exc)
    else:
        print(sample)
