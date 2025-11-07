"""Public interface to answer questions using the Downloader API (no SQL)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from .api_orchestrator import ApiOrchestrator

_ORCHESTRATOR = ApiOrchestrator()


def route_and_answer(question: str) -> Dict[str, Any]:
    """Backward-compatible entry point used by the rest of the app."""

    return _ORCHESTRATOR.answer(question)


def answer_question(question: str) -> Dict[str, Any]:
    """Alias maintained for older imports."""

    return route_and_answer(question)


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Ask a question to the Downloader API-backed agent.")
    parser.add_argument("question", help="Free-form natural language question")
    parser.add_argument(
        "--show-calls",
        action="store_true",
        help="Print the raw API calls payload in addition to the final answer.",
    )
    args = parser.parse_args(argv)

    result = route_and_answer(args.question)
    answer = result.get("answer") or result
    print(answer)
    if args.show_calls and "calls" in result:
        print("\nAPI calls:")
        print(json.dumps(result["calls"], ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    raise SystemExit(_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()


__all__ = ["route_and_answer", "answer_question", "main"]
