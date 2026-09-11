"""Telegram action callback acknowledgement and optional HTTP forwarding."""

from __future__ import annotations

import logging

import httpx
from telegram import CallbackQuery

from .config import Settings
from .models import CallbackEvent
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class CallbackService:
    def __init__(
        self,
        settings: Settings,
        telegram_client: TelegramClient,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.telegram_client = telegram_client
        self.http_client = http_client

    async def handle(self, query: CallbackQuery) -> CallbackEvent | None:
        """Acknowledge a callback, build a generic event, and optionally forward it."""
        try:
            await self.telegram_client.answer_callback_query(query.id)
        except Exception as exc:
            logger.error(
                "Failed to answer Telegram callback query id=%s (%s)",
                query.id,
                type(exc).__name__,
            )

        action = query.data
        message = query.message
        if not action or message is None:
            logger.warning("Ignoring callback without action or message: id=%s", query.id)
            return None

        event = CallbackEvent(
            action=action,
            chat_id=int(message.chat_id),
            message_id=int(message.message_id),
            user_id=int(query.from_user.id),
            username=query.from_user.username,
            callback_query_id=query.id,
        )
        logger.info(
            "action callback received: action=%s chat_id=%s message_id=%s",
            event.action,
            event.chat_id,
            event.message_id,
        )

        if not self.settings.callback_forward_url:
            logger.info("No CALLBACK_FORWARD_URL configured; callback logged only")
            return event

        try:
            response = await self.http_client.post(
                self.settings.callback_forward_url,
                json=event.model_dump(mode="json"),
            )
            response.raise_for_status()
            logger.info("callback forwarded: action=%s", event.action)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "callback forwarding error: upstream status=%s",
                exc.response.status_code,
            )
        except Exception as exc:
            logger.error("callback forwarding error (%s)", type(exc).__name__)

        return event
