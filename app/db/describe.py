"""
Utility to extract PostgreSQL schema metadata and write a markdown summary.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import text

# Ensure project root for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.db.pg import get_engine

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

SCHEMA_MD_PATH = Path(__file__).resolve().parents[1] / "prompts" / "schema.md"
EXCLUDED_TABLES = {"sync_checkpoints"}

TABLE_QUERY = text(
    """
    SELECT
        table_name,
        column_name,
        data_type,
        is_nullable,
        column_default
    FROM information_schema.columns
    WHERE table_schema = :schema
      AND (table_name = ANY(:included) OR :included IS NULL)
    ORDER BY table_name, ordinal_position;
    """
)

FK_QUERY = text(
    """
    SELECT
        tc.table_name,
        kcu.column_name,
        ccu.table_name AS foreign_table,
        ccu.column_name AS foreign_column
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
    JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = :schema
      AND (tc.table_name = ANY(:included) OR :included IS NULL)
      AND (ccu.table_name = ANY(:included) OR :included IS NULL)
    ORDER BY tc.table_name, kcu.column_name;
    """
)


def main(schema: str = "public") -> None:
    engine = get_engine()
    logger.info("Collecting schema information for schema '%s'", schema)
    included = _build_included_list(schema)

    with engine.connect() as conn:
        params = {"schema": schema, "included": included}
        columns = conn.execute(TABLE_QUERY, params).fetchall()
        fks = conn.execute(FK_QUERY, params).fetchall()

    markdown = _build_markdown(columns, fks)
    SCHEMA_MD_PATH.write_text(markdown, encoding="utf-8")
    logger.info("Schema summary written to %s", SCHEMA_MD_PATH)


def _build_markdown(columns, fks) -> str:
    section_lines: list[str] = []
    section_lines.append("# Schema Overview")
    tables: dict[str, list[tuple[str, str, str, str]]] = {}
    for table_name, column_name, data_type, is_nullable, column_default in columns:
        tables.setdefault(table_name, []).append(
            (
                column_name,
                data_type,
                "YES" if is_nullable == "YES" else "NO",
                column_default or "",
            )
        )

    for table_name, cols in tables.items():
        section_lines.append(f"\n## {table_name}")
        section_lines.append("| Column | Type | Nullable | Default |")
        section_lines.append("| --- | --- | --- | --- |")
        for col_name, data_type, nullable, default in cols:
            default_display = default.replace("\n", " ") if default else ""
            section_lines.append(
                f"| {col_name} | {data_type} | {nullable} | {default_display} |"
            )

    if fks:
        section_lines.append("\n## Foreign Keys")
        section_lines.append("| Table | Column | References |")
        section_lines.append("| --- | --- | --- |")
        for table_name, column_name, foreign_table, foreign_column in fks:
            section_lines.append(
                f"| {table_name} | {column_name} | {foreign_table}.{foreign_column} |"
            )

    section_lines.append("")
    return "\n".join(section_lines)


def _build_included_list(schema: str) -> list[str] | None:
    if not EXCLUDED_TABLES:
        return None
    engine = get_engine()
    with engine.connect() as conn:
        existing = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema
                """
            ),
            {"schema": schema},
        ).scalars()
        tables = [name for name in existing if name not in EXCLUDED_TABLES]
    return tables


if __name__ == "__main__":
    main()
