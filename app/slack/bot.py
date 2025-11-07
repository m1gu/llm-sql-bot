"""Slack bot that routes questions to the Downloader API-backed agent."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from app.agent.sql_agent import route_and_answer

load_dotenv()

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)


MENTION_PATTERN = re.compile(r"<@([A-Z0-9]+)>")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required to run the Slack bot.")
    return value


def _clean_question(text: str, bot_user_id: str | None = None) -> str:
    cleaned = text or ""
    if bot_user_id:
        cleaned = re.sub(rf"<@{bot_user_id}>\s*", "", cleaned).strip()
    else:
        cleaned = MENTION_PATTERN.sub("", cleaned).strip()
    return cleaned


def _strip_final_answer(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\*?\s*final answer:?\s*\*?", "", text, flags=re.IGNORECASE).strip()


@dataclass
class SlackBot:
    bot_token: str
    app_token: str

    def __post_init__(self) -> None:
        self.app = App(token=self.bot_token)
        self.bot_user_id = self._fetch_bot_user_id()
        self._register_handlers()

    def _fetch_bot_user_id(self) -> str:
        try:
            resp = self.app.client.auth_test()
            return resp["user_id"]
        except SlackApiError as exc:  # pragma: no cover - happens if token invalid
            LOGGER.error("Slack auth_test failed: %s", exc)
            raise

    def _register_handlers(self) -> None:
        @self.app.event("app_mention")
        def handle_app_mention(body: Dict[str, Any], say, ack) -> None:  # type: ignore[no-untyped-def]
            ack()
            event = body.get("event", {})
            LOGGER.debug("Received app_mention event: %s", event)
            self._handle_question_event(event, say)

        @self.app.event("message")
        def handle_direct_messages(body: Dict[str, Any], say, ack) -> None:  # type: ignore[no-untyped-def]
            ack()
            event = body.get("event", {})
            LOGGER.debug("Received message event: %s", event)
            subtype = event.get("subtype")
            if subtype == "message_changed":
                event = event.get("message", {})
                LOGGER.debug("Unwrapped message_changed payload: %s", event)
                subtype = event.get("subtype")
            if event.get("channel_type") == "im" and not event.get("bot_id") and not subtype:
                self._handle_question_event(event, say)

    def _handle_question_event(self, event: Dict[str, Any], say) -> None:  # type: ignore[no-untyped-def]
        LOGGER.info("Processing event in channel %s: %s", event.get("channel"), event)
        text = event.get("text") or ""
        channel = event.get("channel")
        if not channel:
            LOGGER.warning("Event without channel: %s", event)
            return
        thread_ts = event.get("thread_ts")
        question = _clean_question(text, self.bot_user_id)
        if not question:
            say(
                text="I couldn't find a question in your message. Please provide more details.",
                channel=channel,
                thread_ts=thread_ts,
            )
            return

        if question.lower().strip() in {"hola", "hello", "hi", "hey"}:
            say(
                text="¡Hola! ¿Cómo puedo ayudarte hoy?",
                channel=channel,
                thread_ts=thread_ts,
            )
            return

        progress_message = say(
            text="Processing your request…",
            channel=channel,
            thread_ts=thread_ts,
        )
        try:
            result = route_and_answer(question)
            answer = result.get("answer") or "I couldn't produce a response."
            answer = _strip_final_answer(answer)
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Slack bot failed processing question.")
            answer = f"An error occurred while processing your request: {exc}"

        say_kwargs = {"text": answer, "channel": channel}
        if thread_ts:
            say_kwargs["thread_ts"] = thread_ts
        say(**say_kwargs)

        # Optionally delete the progress message if possible
        try:
            if isinstance(progress_message, dict):
                ts = progress_message.get("ts")
                if ts:
                    self.app.client.chat_delete(channel=channel, ts=ts)
        except SlackApiError:
            LOGGER.debug("Could not delete progress indicator message.")

    def run(self) -> None:
        handler = SocketModeHandler(self.app, self.app_token)
        handler.start()


def run_bot() -> None:
    bot_token = _require_env("SLACK_BOT_TOKEN")
    app_token = _require_env("SLACK_APP_TOKEN")
    SlackBot(bot_token=bot_token, app_token=app_token).run()


def main() -> None:
    run_bot()


if __name__ == "__main__":
    main()
