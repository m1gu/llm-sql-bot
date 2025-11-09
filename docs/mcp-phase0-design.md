MCP Integration – Phase 0 Deliverable
=====================================

1. Context & Goals
------------------
- **Bot de Slack**: entrada principal; recibe preguntas de usuarios y envía la respuesta final que produce el agente.
- **Orquestador/Agente actual**: lógica en `app/agent/api_orchestrator.py` que detecta intención y llama directamente a endpoints HTTP o DB helpers (`app/db/pg.py`, `app/api/client.py`).
- **Servicios disponibles**: endpoints REST (resúmenes, analytics, entidades), acceso directo a Postgres (read-only), prompts/schema/glossary, y lógica de RAG futura (pgvector).

**Meta de la fase**: definir cómo encapsular estos servicios como tools MCP y cómo será el servidor MCP que los expone.

2. Servicios a convertir en tools MCP
-------------------------------------
| Servicio | Fuente actual | Tool MCP propuesta | Notas |
| --- | --- | --- | --- |
| Consulta SQL read-only | `app/db/pg.py` (SQLAlchemy) | `db_read` | Ejecuta SELECT seguros (limita tiempo y añade LIMIT opcional). |
| Schema + glosario | `docs/app/prompts/schema.md`, `glossary.md`, `doc schema extractor` | `schema_info` | Devuelve resumen de tablas/relaciones + glosario y fecha de actualización. |
| RAG/pgvector (futuro) | Planeado en roadmap | `rag_schema_lookup` | Busca embeddings para describir tablas/columnas relevantes. |
| API negocio (analytics, métricas, entidades) | `app/api/client.py` + endpoints | `api_business_call` | Tool genérica que recibe `endpoint_name` + params y proxyea las llamadas permitidas. |
| Entidades detalladas | Nuevos endpoints `/entities/...` | `entity_detail` (puede delegar internamente a `api_business_call` o ser un alias directo). |
| Observabilidad/Audit | logging actual + futuro | `log_event` o `metrics_emit` (fase posterior). |

3. Arquitectura del Servidor MCP
--------------------------------
- **Lenguaje & framework**: Python 3.11+, librería [fastmcp](https://github.com/modelcontextprotocol) o equivalente (así podemos reutilizar código y dependencias existentes).
- **Estructura propuesta**:
  ```
  mcp-server/
    main.py              # arranque del servidor MCP
    tools/
      db_read.py
      schema_info.py
      api_business.py
      rag_schema.py      # opcional en Fase 3
    config.py            # lecturas de .env (DB URI, API base, auth tokens)
    security.py          # sanitización SQL, rate limits básicos
    tests/
      test_db_read.py
      test_api_business.py
  ```
- **Autenticación**: token compartido vía variable de entorno (e.g. `MCP_SERVER_TOKEN`), validado en cada request MCP.
- **Registro/observabilidad**: logs estructurados (JSON) + contador de llamadas por tool; exportables a Prometheus en fases posteriores.

4. Contrato preliminar de tools
-------------------------------

### Tool: `db_read`
- **Responsabilidad**: ejecutar consultas `SELECT` con límite y timeout.
- **Parámetros**:
  - `query` (string, requerido): SQL seguro (solo lectura).
  - `params` (dict opcional): bind parameters para SQLAlchemy.
  - `limit` (int opcional, default 200) y `timeout` (float opcional).
- **Respuesta**:
  ```json
  {
    "rows": [ { "column": value, ... } ],
    "row_count": 42,
    "execution_ms": 15.2,
    "source": "postgres-read"
  }
  ```
- **Validaciones**: rechaza SQL que contenga `INSERT/UPDATE/DELETE`, soporta sólo `SELECT`.

### Tool: `schema_info`
- **Responsabilidad**: devolver el schema y glosario vigentes.
- **Parámetros**:
  - `include_glossary` (bool, default true).
  - `include_examples` (bool, default false) para anexar queries típicas.
- **Respuesta**:
  ```json
  {
    "schema_md": "## samples ...",
    "glossary": [ {"term": "Customer", "meaning": "..."} ],
    "generated_at": "2025-11-09T12:00:00Z"
  }
  ```

### Tool: `api_business_call`
- **Responsabilidad**: proxy seguro a los endpoints analíticos existentes.
- **Parámetros**:
  - `endpoint` (enum string, p.ej. `analytics_customers_orders_summary`).
  - `method` (string, default `GET`).
  - `query_params` (dict), `path_params` (dict).
  - `timeout` opcional.
- **Respuesta**:
  ```json
  {
    "endpoint": "analytics_customers_orders_summary",
    "status_code": 200,
    "payload": { ... },
    "fetched_at": "..."
  }
  ```
- **Seguridad**: sólo endpoints whitelisted; sanitize numbers/strings antes de reenviar.

### Tool: `entity_detail`
- **Responsabilidad**: facilitar consultas rápidas a `/entities/orders/{id}`, `/entities/samples/{id}/full`, `/entities/tests/{id}/full`.
- **Parámetros**:
  - `entity_type` (`order|sample|test`).
  - `entity_id` (int).
  - `options` (dict) para flags `include_*`, `sla_hours`.
- **Respuesta**:
  ```json
  {
    "entity_type": "order",
    "entity": {...},
    "customer": {...},
    "samples": [...],
    "tests": [...]
  }
  ```
- **Implementación**: puede delegar internamente a `api_business_call`.

### Tool: `rag_schema_lookup` (fase siguiente, pero definido ahora)
- **Responsabilidad**: dado un texto natural, devolver tablas/columnas más relevantes (usando pgvector).
- **Parámetros**:
  - `question` (string).
  - `top_k` (int, default 5).
- **Respuesta**:
  ```json
  {
    "matches": [
      {"table": "samples", "column": "state", "score": 0.81, "description": "..."}
    ]
  }
  ```

5. Notas finales
----------------
- Este documento sirve como contrato inicial; cualquier tool adicional (logs, writes) se agregará en Fase 3.
- Recomendación: documentar las tools en formato Markdown dentro del repositorio MCP (README o `/docs/tools.md`) para mantener la especificación sincronizada.

