"""Environment-backed configuration for the Telegram service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    app_host: str = "127.0.0.1"
    app_port: int = 9878
    telegram_token: str = ""
    telegram_chat_id: int | None = None
    callback_forward_url: str | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None

    @classmethod
    def load(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Load settings from .env and environment variables."""
        if environ is None:
            load_dotenv()
            environ = os.environ

        port_raw = environ.get("APP_PORT", "9878").strip()
        try:
            app_port = int(port_raw)
        except ValueError as exc:
            raise ValueError("APP_PORT must be an integer") from exc
        if not 1 <= app_port <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535")

        chat_id_raw = environ.get("TELEGRAM_CHAT_ID", "").strip()
        telegram_chat_id: int | None = None
        if chat_id_raw:
            try:
                telegram_chat_id = int(chat_id_raw)
            except ValueError as exc:
                raise ValueError("TELEGRAM_CHAT_ID must be an integer") from exc

        def optional(name: str) -> str | None:
            value = environ.get(name, "").strip()
            return value or None

        return cls(
            app_host=environ.get("APP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            app_port=app_port,
            telegram_token=environ.get("TELEGRAM_TOKEN", "").strip(),
            telegram_chat_id=telegram_chat_id,
            callback_forward_url=optional("CALLBACK_FORWARD_URL"),
            http_proxy=optional("HTTP_PROXY"),
            https_proxy=optional("HTTPS_PROXY"),
        )

    @property
    def telegram_proxy(self) -> str | None:
        """Prefer HTTPS_PROXY for Telegram HTTPS traffic, then HTTP_PROXY."""
        return self.https_proxy or self.http_proxy

    def validate_startup(self) -> None:
        if not self.telegram_token:
            raise ValueError("TELEGRAM_TOKEN is required")
