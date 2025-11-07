# Documentación de Endpoints - Downloader QBench Data API

## Información General

- **Base URL**: `http://localhost:8000`
- **API Version**: v1
- **Prefix**: `/api/v1`
- **Documentación Interactiva**: `/api/docs` (Swagger UI)
- **Documentación Alternativa**: `/api/redoc` (ReDoc)

---

## Endpoints de Salud

### GET /api/health
Verifica el estado de salud de la API.

**Respuesta:**
```json
{
  "status": "ok"
}
```

---

## Endpoints de Métricas (Metrics)

### GET /api/v1/metrics/summary
Retorna un resumen de KPIs para el rango seleccionado.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `state` (string, opcional): Estado para filtrar
- `sla_hours` (float, default 48.0): Horas del SLA para métricas

**Respuesta:**
```json
{
  "kpis": {
    "total_samples": 1250,
    "total_tests": 3400,
    "total_customers": 45,
    "total_reports": 1180,
    "average_tat_hours": 36.5
  },
  "last_updated_at": "2024-01-15T10:30:00Z",
  "range_start": "2024-01-01T00:00:00Z",
  "range_end": "2024-01-15T23:59:59Z"
}
```

---

### GET /api/v1/metrics/activity/daily
Retorna conteos diarios de muestras y pruebas.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `compare_previous` (bool, default false): Incluir datos del período anterior para comparación

**Respuesta:**
```json
{
  "current": [
    {
      "date": "2024-01-15",
      "samples": 85,
      "tests": 230
    },
    {
      "date": "2024-01-14",
      "samples": 92,
      "tests": 245
    }
  ],
  "previous": [
    {
      "date": "2024-01-08",
      "samples": 78,
      "tests": 210
    }
  ]
}
```

---

### GET /api/v1/metrics/customers/new
Retorna clientes creados dentro del rango seleccionado.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `limit` (int, default 10, min 1): Número máximo de resultados

**Respuesta:**
```json
{
  "customers": [
    {
      "id": 123,
      "name": "Laboratorio Central",
      "created_at": "2024-01-15T14:30:00Z"
    },
    {
      "id": 124,
      "name": "Clínica Médica del Norte",
      "created_at": "2024-01-14T09:15:00Z"
    }
  ]
}
```

---

### GET /api/v1/metrics/customers/top-tests
Retorna los principales clientes clasificados por número de pruebas en el rango.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `limit` (int, default 10, min 1): Número máximo de resultados

**Respuesta:**
```json
{
  "customers": [
    {
      "id": 101,
      "name": "Hospital Regional",
      "tests": 450
    },
    {
      "id": 102,
      "name": "Centro Diagnóstico Avanzado",
      "tests": 380
    }
  ]
}
```

---

### GET /api/v1/metrics/reports/overview
Retorna conteos de informes dentro/fuera del SLA.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `state` (string, opcional): Estado para filtrar
- `sla_hours` (float, default 48.0): Horas del SLA para métricas

**Respuesta:**
```json
{
  "total_reports": 1180,
  "reports_within_sla": 1050,
  "reports_beyond_sla": 130
}
```

---

### GET /api/v1/metrics/tests/tat-daily
Retorna estadísticas diarias de TAT (Turnaround Time) incluyendo medias móviles.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `state` (string, opcional): Estado para filtrar
- `sla_hours` (float, default 48.0): Horas del SLA para métricas
- `moving_average_window` (int, default 7, min 1): Ventana para la media móvil

**Respuesta:**
```json
{
  "points": [
    {
      "date": "2024-01-15",
      "average_hours": 35.2,
      "within_sla": 78,
      "beyond_sla": 7
    },
    {
      "date": "2024-01-14",
      "average_hours": 38.5,
      "within_sla": 82,
      "beyond_sla": 10
    }
  ],
  "moving_average_hours": [
    {
      "period_start": "2024-01-15",
      "value": 36.8
    }
  ]
}
```

---

### GET /api/v1/metrics/samples/overview
Retorna métricas agregadas para muestras.

**Parámetros Query:**
- `date_from` (datetime, opcional): Filtrar muestras creadas después de esta fecha
- `date_to` (datetime, opcional): Filtrar muestras creadas antes de esta fecha
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `state` (string, opcional): Estado para filtrar

**Respuesta:**
```json
{
  "kpis": {
    "total_samples": 1250,
    "completed_samples": 1100,
    "pending_samples": 150
  },
  "by_state": [
    {
      "key": "completed",
      "count": 1100
    },
    {
      "key": "pending",
      "count": 150
    }
  ],
  "by_matrix_type": [
    {
      "key": "blood",
      "count": 750
    },
    {
      "key": "urine",
      "count": 500
    }
  ],
  "created_vs_completed": [
    {
      "key": "created",
      "count": 1250
    },
    {
      "key": "completed",
      "count": 1100
    }
  ]
}
```

---

### GET /api/v1/metrics/tests/overview
Retorna métricas agregadas para pruebas.

**Parámetros Query:**
- `date_from` (datetime, opcional): Fecha de inicio del filtro
- `date_to` (datetime, opcional): Fecha de fin del filtro
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `state` (string, opcional): Estado para filtrar
- `batch_id` (int, opcional): ID del lote para filtrar

**Respuesta:**
```json
{
  "kpis": {
    "total_tests": 3400,
    "completed_tests": 3100,
    "pending_tests": 300
  },
  "by_state": [
    {
      "key": "completed",
      "count": 3100
    },
    {
      "key": "pending",
      "count": 300
    }
  ],
  "by_label": [
    {
      "key": "hematology",
      "count": 1200
    },
    {
      "key": "chemistry",
      "count": 1500
    },
    {
      "key": "microbiology",
      "count": 700
    }
  ]
}
```

---

### GET /api/v1/metrics/tests/tat
Retorna métricas de turnaround time para pruebas.

**Parámetros Query:**
- `date_created_from` (datetime, opcional): Fecha de creación de inicio
- `date_created_to` (datetime, opcional): Fecha de creación de fin
- `customer_id` (int, opcional): ID del cliente para filtrar
- `order_id` (int, opcional): ID del orden para filtrar
- `state` (string, opcional): Estado para filtrar
- `group_by` (string, opcional): Intervalo de agrupación para datos de series temporales (day|week)

**Respuesta:**
```json
{
  "metrics": {
    "average_hours": 36.5,
    "median_hours": 34.2,
    "p95_hours": 48.0,
    "completed_within_sla": 1050,
    "completed_beyond_sla": 130
  },
  "distribution": [
    {
      "label": "< 24h",
      "count": 600
    },
    {
      "label": "24-48h",
      "count": 450
    },
    {
      "label": "> 48h",
      "count": 130
    }
  ],
  "series": [
    {
      "period_start": "2024-01-15",
      "value": 35.2
    },
    {
      "period_start": "2024-01-14",
      "value": 38.5
    }
  ]
}
```

---

### GET /api/v1/metrics/tests/tat-breakdown
Retorna métricas de TAT desglosadas por etiqueta.

**Parámetros Query:**
- `date_created_from` (datetime, opcional): Fecha de creación de inicio
- `date_created_to` (datetime, opcional): Fecha de creación de fin

**Respuesta:**
```json
{
  "breakdown": [
    {
      "label": "hematology",
      "average_hours": 24.5,
      "median_hours": 22.0,
      "p95_hours": 36.0,
      "total_tests": 1200
    },
    {
      "label": "chemistry",
      "average_hours": 42.3,
      "median_hours": 40.0,
      "p95_hours": 56.0,
      "total_tests": 1500
    },
    {
      "label": "microbiology",
      "average_hours": 48.7,
      "median_hours": 46.0,
      "p95_hours": 72.0,
      "total_tests": 700
    }
  ]
}
```

---

### GET /api/v1/metrics/common/filters
Retorna valores para poblar los filtros del dashboard.

**Parámetros Query:**
Ninguno

**Respuesta:**
```json
{
  "customers": [
    {
      "id": 101,
      "name": "Hospital Regional"
    },
    {
      "id": 102,
      "name": "Centro Diagnóstico Avanzado"
    }
  ],
  "sample_states": ["pending", "completed", "cancelled"],
  "test_states": ["pending", "completed", "failed", "cancelled"],
  "last_updated_at": "2024-01-15T10:30:00Z"
}
```

---

## Endpoints de Entidades (Entities)

### GET /api/v1/entities/samples/{sample_id}
Retorna detalles para una muestra específica.

**Parámetros Path:**
- `sample_id` (int, requerido): Identificador de la muestra

**Respuesta:**
```json
{
  "id": 12345,
  "sample_name": "SANGRE-001",
  "custom_formatted_id": "SNG-2024-001",
  "order_id": 678,
  "has_report": true,
  "batch_ids": [101, 102],
  "completed_date": "2024-01-15T14:30:00Z",
  "date_created": "2024-01-14T08:15:00Z",
  "start_date": "2024-01-14T09:00:00Z",
  "matrix_type": "blood",
  "state": "completed",
  "test_count": 5,
  "raw_payload": {
    "additional_fields": "..."
  },
  "order": {
    "id": 678,
    "customer_name": "Hospital Regional"
  },
  "batches": [
    {
      "id": 101,
      "name": "BATCH-001"
    }
  ]
}
```

**Errores:**
- `404 Not Found`: Sample not found

---

### GET /api/v1/entities/tests/{test_id}
Retorna detalles para una prueba específica.

**Parámetros Path:**
- `test_id` (int, requerido): Identificador de la prueba

**Respuesta:**
```json
{
  "id": 54321,
  "sample_id": 12345,
  "batch_ids": [101],
  "date_created": "2024-01-14T08:30:00Z",
  "state": "completed",
  "has_report": true,
  "report_completed_date": "2024-01-15T14:30:00Z",
  "label_abbr": "HEM",
  "title": "Hemograma Completo",
  "worksheet_raw": {
    "results": [...]
  },
  "raw_payload": {
    "additional_fields": "..."
  },
  "sample": {
    "id": 12345,
    "sample_name": "SANGRE-001"
  },
  "batches": [
    {
      "id": 101,
      "name": "BATCH-001"
    }
  ]
}
```

**Errores:**
- `404 Not Found`: Test not found

---

## Consideraciones Generales

1. **Formato de Fechas**: Todos los parámetros de fecha deben seguir el formato ISO 8601 (YYYY-MM-DDTHH:MM:SSZ).

2. **Paginación**: Los endpoints que retornan listas utilizan el parámetro `limit` para controlar el número de resultados.

3. **Filtros**: La mayoría de los endpoints de métricas permiten filtrar por rango de fechas, cliente, orden y estado.

4. **SLA**: El SLA predeterminado es de 48 horas, pero puede ser ajustado mediante el parámetro `sla_hours`.

5. **CORS**: La API tiene configurado CORS para permitir solicitudes desde cualquier origen.

6. **Documentación Interactiva**: Para explorar y probar los endpoints de forma interactiva, visite `/api/docs`.

---

## Ejemplos de Uso

### Obtener resumen de métricas para las últimas 2 semanas

```bash
curl -X GET "http://localhost:8000/api/v1/metrics/summary?date_from=2024-01-01T00:00:00Z&date_to=2024-01-15T23:59:59Z"
```

### Obtener detalles de una muestra específica

```bash
curl -X GET "http://localhost:8000/api/v1/entities/samples/12345"
```

### Obtener TAT de pruebas agrupado por semana

```bash
curl -X GET "http://localhost:8000/api/v1/metrics/tests/tat?date_created_from=2024-01-01T00:00:00Z&date_created_to=2024-01-15T23:59:59Z&group_by=week"
```

### Obtener los 5 clientes principales por número de pruebas

```bash
curl -X GET "http://localhost:8000/api/v1/metrics/customers/top-tests?date_from=2024-01-01T00:00:00Z&date_to=2024-01-15T23:59:59Z&limit=5"