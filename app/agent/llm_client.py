"""
Client for interacting with a local Ollama instance using the chat API.

Usage example:
    python -m app.agent.llm_client
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx
try:
    from loguru import logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback if dependency missing
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("llm_client")
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role name, e.g. system, user, assistant")
    content: str = Field(..., description="Message content")


class LLMClient:
    """Simple HTTP client for the Ollama chat endpoint."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.timeout = timeout
        self._chat_endpoint = f"{self.base_url.rstrip('/')}/api/chat"
        logger.debug("LLMClient initialized with endpoint {}", self._chat_endpoint)

    def chat(self, messages: List[Dict[str, Any]]) -> str:
        """Send chat-formatted messages to Ollama and return the assistant reply."""
        payload = {
            "model": "mistral:instruct",
            "messages": [ChatMessage(**m).model_dump() for m in messages],
            "stream": False,
        }
        logger.debug(f"Sending payload to Ollama: {payload}")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self._chat_endpoint, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error(f"Ollama request failed: {exc}")
            raise

        data = response.json()
        logger.debug(f"Received response: {data}")
        resp_message = data.get("message", {})
        return resp_message.get("content", "").strip()


def _demo() -> None:
    client = LLMClient()
    messages = [
        {"role": "system", "content": "Eres un asistente útil que responde en español."},
        {"role": "user", "content": "Hola, ¿puedes resumir qué es PostgreSQL?"},
    ]
    try:
        answer = client.chat(messages)
    except httpx.HTTPError:
        logger.error("No fue posible contactar Ollama. ¿Está el servicio en ejecución?")
        return
    print("Respuesta del modelo:")
    print(answer)


if __name__ == "__main__":
    _demo()
