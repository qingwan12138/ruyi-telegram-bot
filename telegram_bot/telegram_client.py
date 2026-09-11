"""Thin async wrapper around python-telegram-bot."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Sequence

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

from .config import Settings
from .models import Button

logger = logging.getLogger(__name__)


class TelegramClientError(RuntimeError):
    """Base error for sanitized Telegram client failures."""


class TelegramSendError(TelegramClientError):
    """Raised when Telegram rejects or fails a send operation."""


class TelegramCallbackError(TelegramClientError):
    """Raised when Telegram callback acknowledgement fails."""


class MissingChatIdError(ValueError):
    """Raised when neither request nor configuration provides a chat ID."""


@dataclass(frozen=True, slots=True)
class SendResult:
    chat_id: int
    message_id: int


class TelegramClient:
    def __init__(self, settings: Settings, *, bot: Bot | None = None) -> None:
        self.settings = settings
        if bot is not None:
            self.bot = bot
            return

        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=35.0,
            write_timeout=30.0,
            pool_timeout=30.0,
            proxy=settings.telegram_proxy,
        )
        self.bot = Bot(token=settings.telegram_token, request=request)
        logger.info(
            "Telegram client initialized%s",
            " with proxy" if settings.telegram_proxy else "",
        )

    async def initialize(self) -> None:
        try:
            await self.bot.initialize()
        except Exception as exc:
            logger.error("Telegram client initialization failed (%s)", type(exc).__name__)
            raise TelegramClientError("Telegram client initialization failed") from None

    async def shutdown(self) -> None:
        try:
            await self.bot.shutdown()
        except Exception as exc:
            logger.error("Telegram client shutdown failed (%s)", type(exc).__name__)

    async def answer_callback_query(self, callback_query_id: str) -> None:
        """Acknowledge a Telegram inline-button callback."""
        try:
            await self.bot.answer_callback_query(callback_query_id=callback_query_id)
        except Exception as exc:
            logger.error("Telegram callback acknowledgement failed (%s)", type(exc).__name__)
            raise TelegramCallbackError("Telegram callback acknowledgement failed") from None

    async def poll_callbacks(self, callback_handler) -> None:
        """Long-poll Telegram for callback_query updates until cancelled."""
        offset: int | None = None
        while True:
            try:
                updates = await self.bot.get_updates(
                    offset=offset,
                    timeout=30,
                    read_timeout=35.0,
                    allowed_updates=["callback_query"],
                )
                for update in updates:
                    offset = update.update_id + 1
                    if update.callback_query is None:
                        continue
                    try:
                        await callback_handler(update.callback_query)
                    except Exception:
                        logger.exception(
                            "Unhandled callback handler error for update_id=%s",
                            update.update_id,
                        )
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                logger.error("Telegram polling error (%s)", type(exc).__name__)
                await asyncio.sleep(2)
            except Exception as exc:
                logger.error("Unexpected Telegram polling error (%s)", type(exc).__name__)
                await asyncio.sleep(2)

    @staticmethod
    def build_keyboard(buttons: Sequence[Button]) -> InlineKeyboardMarkup | None:
        if not buttons:
            return None

        rendered: list[InlineKeyboardButton] = []
        for button in buttons:
            if button.type == "url":
                rendered.append(InlineKeyboardButton(text=button.text, url=button.url))
            else:
                rendered.append(
                    InlineKeyboardButton(text=button.text, callback_data=button.action)
                )

        rows = [rendered[index : index + 2] for index in range(0, len(rendered), 2)]
        return InlineKeyboardMarkup(rows)

    def resolve_chat_id(self, requested_chat_id: int | None) -> int:
        target = requested_chat_id if requested_chat_id is not None else self.settings.telegram_chat_id
        if target is None:
            raise MissingChatIdError(
                "chat_id is required when TELEGRAM_CHAT_ID is not configured"
            )
        return target

    async def send_message(
        self,
        text: str,
        *,
        chat_id: int | None = None,
        buttons: Sequence[Button] = (),
    ) -> SendResult:
        target_chat_id = self.resolve_chat_id(chat_id)
        keyboard = self.build_keyboard(buttons)

        try:
            message = await self.bot.send_message(
                chat_id=target_chat_id,
                text=text,
                reply_markup=keyboard,
            )
        except TelegramError as exc:
            logger.error("Telegram API error while sending message (%s)", type(exc).__name__)
            raise TelegramSendError("Telegram notification failed") from None
        except Exception as exc:
            logger.error("Unexpected Telegram send error (%s)", type(exc).__name__)
            raise TelegramSendError("Telegram notification failed") from None

        message_id = int(message.message_id)
        logger.info("message sent: chat_id=%s message_id=%s", target_chat_id, message_id)
        return SendResult(chat_id=target_chat_id, message_id=message_id)
