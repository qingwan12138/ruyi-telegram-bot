"""Telegram callback acknowledgement, routing, and delivery feedback."""

from __future__ import annotations

import logging

import httpx
from telegram import CallbackQuery

from .callback_data import (
    CALLBACK_DATA_PREFIX,
    CallbackDataError,
    decode_interaction_callback,
)
from .config import CallbackRouteError, Settings
from .models import CallbackEvent, InteractionResult
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)

CALLBACK_ACK_TEXT = "Selection received."
DELIVERY_SUCCESS_TEXT = "Selection delivered successfully."
DELIVERY_FAILURE_TEXT = "Failed to deliver your selection."


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

    async def handle(
        self,
        query: CallbackQuery,
    ) -> CallbackEvent | InteractionResult | None:
        """Acknowledge, decode, route, and report transport delivery status."""
        try:
            await self.telegram_client.answer_callback_query(
                query.id,
                text=CALLBACK_ACK_TEXT,
            )
        except Exception as exc:
            logger.error(
                "Failed to answer Telegram callback query id=%s (%s)",
                query.id,
                type(exc).__name__,
            )

        callback_data = query.data
        message = query.message
        if not callback_data or message is None:
            logger.warning("Ignoring incomplete callback: id=%s", query.id)
            return None

        chat_id = int(message.chat_id)
        common_fields = {
            "chat_id": chat_id,
            "message_id": int(message.message_id),
            "user_id": int(query.from_user.id),
            "username": query.from_user.username,
            "callback_query_id": query.id,
        }

        callback_target: str | None = None
        if callback_data.startswith(CALLBACK_DATA_PREFIX):
            try:
                decoded = decode_interaction_callback(callback_data)
            except CallbackDataError as exc:
                logger.warning(
                    "Malformed interaction callback ignored (%s)",
                    type(exc).__name__,
                )
                await self._send_delivery_feedback(chat_id, delivered=False)
                return None
            callback_target = decoded.callback_target
            event: CallbackEvent | InteractionResult = InteractionResult(
                interaction_id=decoded.interaction_id,
                option_id=decoded.option_id,
                **common_fields,
            )
        else:
            event = CallbackEvent(action=callback_data, **common_fields)

        logger.info(
            "callback received: event=%s chat_id=%s message_id=%s",
            event.event,
            event.chat_id,
            event.message_id,
        )

        delivered = await self._deliver(event, callback_target)
        await self._send_delivery_feedback(chat_id, delivered=delivered)
        return event

    async def _deliver(
        self,
        event: CallbackEvent | InteractionResult,
        callback_target: str | None,
    ) -> bool:
        try:
            endpoint = self.settings.resolve_callback_url(callback_target)
            response = await self.http_client.post(
                endpoint,
                json=event.model_dump(mode="json"),
            )
            response.raise_for_status()
        except CallbackRouteError as exc:
            logger.error("callback route resolution failed (%s)", type(exc).__name__)
            return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "callback delivery failed: target status=%s",
                exc.response.status_code,
            )
            return False
        except httpx.TimeoutException as exc:
            logger.error("callback delivery timed out (%s)", type(exc).__name__)
            return False
        except httpx.HTTPError as exc:
            logger.error("callback delivery network error (%s)", type(exc).__name__)
            return False
        except Exception as exc:
            logger.error("callback delivery error (%s)", type(exc).__name__)
            return False

        logger.info("callback delivered: event=%s", event.event)
        return True

    async def _send_delivery_feedback(self, chat_id: int, *, delivered: bool) -> None:
        text = DELIVERY_SUCCESS_TEXT if delivered else DELIVERY_FAILURE_TEXT
        try:
            await self.telegram_client.send_message(text, chat_id=chat_id)
        except Exception as exc:
            logger.error(
                "Telegram delivery feedback failed (%s)",
                type(exc).__name__,
            )
