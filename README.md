# NL to SQL Bot

Proyecto base para un chatbot que responde preguntas en lenguaje natural usando una base de datos PostgreSQL local y un modelo de lenguaje orquestado con LangChain y FastAPI.

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
3. Copia las variables de entorno de ejemplo y personalizalas.
   ```bash
   cp .env.example .env        # macOS / Linux
   copy .env.example .env      # Windows PowerShell
   ```
   Completa `PG_URI`, `OLLAMA_BASE_URL`, `SLACK_BOT_TOKEN` y `SLACK_APP_TOKEN` con los valores reales.

## Pasos siguientes recomendados

- Verificar que `pip install -r requirements.txt` termine sin errores.
- Continuar con la Fase 1 del roadmap para integrar Ollama y probar el modelo Mistral localmente.
