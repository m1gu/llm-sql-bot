# NL to SQL Bot

Proyecto base para un chatbot que responde preguntas en lenguaje natural consumiendo directamente la **Downloader QBench Data API** (ya no ejecuta SQL sobre PostgreSQL). La orquestación sigue apoyándose en LangChain + Ollama para planear llamadas a los endpoints y sintetizar la respuesta final.

## Estructura inicial

```
llm-sql-bot/
  app/
    api/
    agent/
    db/
    prompts/
    security/
    observability/
    slack/
    __init__.py
  tests/
  .env.example
  requirements.txt
  README.md
```

## Configuracion del entorno

1. Crea y activa un entorno virtual de Python 3.11+.
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate
   ```
2. Instala las dependencias base.
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. Copia las variables de entorno de ejemplo y personalízalas.
   ```bash
   cp .env.example .env        # macOS / Linux
   copy .env.example .env      # Windows PowerShell
   ```
   Completa `API_BASE_URL` (ej. `http://localhost:8000/api/v1`), `OLLAMA_BASE_URL`, `SLACK_BOT_TOKEN` y `SLACK_APP_TOKEN` con los valores reales.

## Pasos siguientes recomendados

- Verificar que `pip install -r requirements.txt` termine sin errores.
- Continuar con la fase de experimentos para refinar el planificador de endpoints y, si es necesario, agregar nuevas herramientas sobre la API.
