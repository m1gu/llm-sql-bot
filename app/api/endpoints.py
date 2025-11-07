"""Metadata defining the Downloader QBench Data API endpoints available to the bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class EndpointParam:
    """Describes a supported query parameter for an endpoint."""

    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class EndpointSpec:
    """Definition of an endpoint that the agent can invoke."""

    name: str
    method: str
    path: str
    description: str
    params: List[EndpointParam] = field(default_factory=list)


ENDPOINT_SPECS: Dict[str, EndpointSpec] = {
    "metrics_summary": EndpointSpec(
        name="metrics_summary",
        method="GET",
        path="/metrics/summary",
        description="KPIs globales de samples, tests, customers y reports en un rango.",
        params=[
            EndpointParam("date_from", "Fecha/hora inicial ISO 8601", False),
            EndpointParam("date_to", "Fecha/hora final ISO 8601", False),
            EndpointParam("customer_id", "Filtro por cliente", False),
            EndpointParam("order_id", "Filtro por orden", False),
            EndpointParam("state", "Filtro por estado de orden", False),
            EndpointParam("sla_hours", "Horas SLA para métricas, default 48", False),
        ],
    ),
    "metrics_activity_daily": EndpointSpec(
        name="metrics_activity_daily",
        method="GET",
        path="/metrics/activity/daily",
        description="Serie diaria de samples/tests y comparativo opcional.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("customer_id", "Cliente"),
            EndpointParam("order_id", "Orden"),
            EndpointParam("compare_previous", "true/false para incluir histórico"),
        ],
    ),
    "metrics_customers_new": EndpointSpec(
        name="metrics_customers_new",
        method="GET",
        path="/metrics/customers/new",
        description="Lista de nuevos clientes en el rango.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("limit", "Resultados máximos (default 10)"),
        ],
    ),
    "metrics_customers_top_tests": EndpointSpec(
        name="metrics_customers_top_tests",
        method="GET",
        path="/metrics/customers/top-tests",
        description="Top clientes por cantidad de tests.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("limit", "Resultados máximos (default 10)"),
        ],
    ),
    "metrics_reports_overview": EndpointSpec(
        name="metrics_reports_overview",
        method="GET",
        path="/metrics/reports/overview",
        description="Totales de reportes dentro/fuera de SLA.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("customer_id", "Cliente"),
            EndpointParam("order_id", "Orden"),
            EndpointParam("state", "Estado"),
            EndpointParam("sla_hours", "Horas SLA"),
        ],
    ),
    "metrics_tests_tat": EndpointSpec(
        name="metrics_tests_tat",
        method="GET",
        path="/metrics/tests/tat",
        description="Estadísticas de TAT (avg/median/p95) y distribución.",
        params=[
            EndpointParam("date_created_from", "Fecha inicial por creación"),
            EndpointParam("date_created_to", "Fecha final por creación"),
            EndpointParam("customer_id", "Cliente"),
            EndpointParam("order_id", "Orden"),
            EndpointParam("batch_id", "Batch"),
            EndpointParam("group_by", "Agrupación (day/week)"),
        ],
    ),
    "metrics_tests_tat_daily": EndpointSpec(
        name="metrics_tests_tat_daily",
        method="GET",
        path="/metrics/tests/tat-daily",
        description="Serie diaria de TAT con within/beyond SLA.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("moving_average_window", "Ventana para promedio móvil"),
        ],
    ),
    "metrics_samples_overview": EndpointSpec(
        name="metrics_samples_overview",
        method="GET",
        path="/metrics/samples/overview",
        description="KPIs y distribuciones de samples por estado/matriz.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("customer_id", "Cliente"),
            EndpointParam("order_id", "Orden"),
            EndpointParam("state", "Estado de sample"),
        ],
    ),
    "metrics_tests_overview": EndpointSpec(
        name="metrics_tests_overview",
        method="GET",
        path="/metrics/tests/overview",
        description="KPIs y distribuciones de tests por estado/label.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("customer_id", "Cliente"),
            EndpointParam("order_id", "Orden"),
            EndpointParam("state", "Estado de test"),
            EndpointParam("batch_id", "Batch"),
        ],
    ),
    "metrics_common_filters": EndpointSpec(
        name="metrics_common_filters",
        method="GET",
        path="/metrics/common/filters",
        description="Catálogos básicos (clientes, estados) y timestamp de actualización.",
        params=[],
    ),
    "analytics_orders_throughput": EndpointSpec(
        name="analytics_orders_throughput",
        method="GET",
        path="/analytics/orders/throughput",
        description="Creación/completado de órdenes por intervalo.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("interval", "Granularidad day/week"),
        ],
    ),
    "analytics_samples_cycle_time": EndpointSpec(
        name="analytics_samples_cycle_time",
        method="GET",
        path="/analytics/samples/cycle-time",
        description="Tiempo de ciclo promedio por matriz y periodo.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("interval", "day/week"),
        ],
    ),
    "analytics_orders_overdue": EndpointSpec(
        name="analytics_orders_overdue",
        method="GET",
        path="/analytics/orders/overdue",
        description="Órdenes vencidas, warning, heatmap y samples listos para reportar.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("interval", "day/week"),
            EndpointParam("min_days_overdue", "Días mínimos para considerar overdue"),
            EndpointParam("sla_hours", "SLA en horas"),
        ],
    ),
    "analytics_customers_alerts": EndpointSpec(
        name="analytics_customers_alerts",
        method="GET",
        path="/analytics/customers/alerts",
        description="Alertas por cliente (on hold, SLA, etc.).",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("customer_id", "Cliente específico"),
            EndpointParam("interval", "day/week"),
            EndpointParam("sla_hours", "SLA horas"),
            EndpointParam("min_alert_percentage", "Umbral para alertas"),
        ],
    ),
    "analytics_tests_state_distribution": EndpointSpec(
        name="analytics_tests_state_distribution",
        method="GET",
        path="/analytics/tests/state-distribution",
        description="Distribución de estados de tests por periodo.",
        params=[
            EndpointParam("date_from", "Fecha inicial"),
            EndpointParam("date_to", "Fecha final"),
            EndpointParam("interval", "day/week"),
        ],
    ),
    "entities_sample_detail": EndpointSpec(
        name="entities_sample_detail",
        method="GET",
        path="/entities/samples/{sample_id}",
        description="Detalle completo de una sample.",
        params=[EndpointParam("sample_id", "ID de la sample (path param)", True)],
    ),
    "entities_test_detail": EndpointSpec(
        name="entities_test_detail",
        method="GET",
        path="/entities/tests/{test_id}",
        description="Detalle completo de un test.",
        params=[EndpointParam("test_id", "ID del test (path param)", True)],
    ),
}


def build_endpoint_catalog() -> str:
    """Return a human-readable catalog used in prompts."""

    lines: List[str] = []
    for spec in ENDPOINT_SPECS.values():
        lines.append(f"- {spec.name} [{spec.method} {spec.path}]: {spec.description}")
        if spec.params:
            param_desc = "; ".join(
                f"{param.name}{' (req)' if param.required else ''}: {param.description}"
                for param in spec.params
            )
            lines.append(f"  Parámetros: {param_desc}")
    return "\n".join(lines)


__all__ = ["ENDPOINT_SPECS", "EndpointSpec", "build_endpoint_catalog"]
