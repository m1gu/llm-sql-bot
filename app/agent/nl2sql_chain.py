"""Compatibility module that now proxies to the API orchestrator."""

from __future__ import annotations

from typing import Any, Dict

from .api_orchestrator import ApiOrchestrator

_ORCHESTRATOR = ApiOrchestrator(max_calls=2)


def answer_question(question: str) -> Dict[str, Any]:
    """Retained for backwards compatibility."""

    return _ORCHESTRATOR.answer(question)


__all__ = ["answer_question"]
