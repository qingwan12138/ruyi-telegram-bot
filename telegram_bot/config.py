"""Environment-backed configuration for the Telegram service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv


class CallbackRouteError(ValueError):
    """Base error for unavailable callback delivery routes."""


class UnknownCallbackTargetError(CallbackRouteError):
    """Raised when an explicit logical callback target is not configured."""


class MissingCallbackRouteError(CallbackRouteError):
    """Raised when no explicit target or legacy fallback can be used."""


def _validate_endpoint(value: str, *, setting_name: str) -> str:
    endpoint = value.strip()
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{setting_name} only supports http:// or https:// URLs")
    return endpoint


def _parse_callback_targets(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CALLBACK_TARGETS_JSON must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("CALLBACK_TARGETS_JSON must be a JSON object")

    targets: dict[str, str] = {}
    for raw_target, raw_endpoint in parsed.items():
        if not isinstance(raw_target, str) or not raw_target.strip():
            raise ValueError("CALLBACK_TARGETS_JSON target names must be non-blank strings")
        if not isinstance(raw_endpoint, str):
            raise ValueError("CALLBACK_TARGETS_JSON values must be a string URL")
        target = raw_target.strip()
        if target in targets:
            raise ValueError("CALLBACK_TARGETS_JSON target names must be unique")
        targets[target] = _validate_endpoint(
            raw_endpoint,
            setting_name="CALLBACK_TARGETS_JSON endpoints",
        )
    return targets


@dataclass(frozen=True, slots=True)
class Settings:
    app_host: str = "127.0.0.1"
    app_port: int = 9878
    telegram_token: str = ""
    telegram_chat_id: int | None = None
    callback_forward_url: str | None = None
    callback_targets: dict[str, str] = field(default_factory=dict)
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

        callback_forward_url = optional("CALLBACK_FORWARD_URL")
        if callback_forward_url is not None:
            callback_forward_url = _validate_endpoint(
                callback_forward_url,
                setting_name="CALLBACK_FORWARD_URL",
            )

        return cls(
            app_host=environ.get("APP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            app_port=app_port,
            telegram_token=environ.get("TELEGRAM_TOKEN", "").strip(),
            telegram_chat_id=telegram_chat_id,
            callback_forward_url=callback_forward_url,
            callback_targets=_parse_callback_targets(
                environ.get("CALLBACK_TARGETS_JSON", "")
            ),
            http_proxy=optional("HTTP_PROXY"),
            https_proxy=optional("HTTPS_PROXY"),
        )

    @property
    def telegram_proxy(self) -> str | None:
        """Prefer HTTPS_PROXY for Telegram HTTPS traffic, then HTTP_PROXY."""
        return self.https_proxy or self.http_proxy

    def resolve_callback_url(self, callback_target: str | None) -> str:
        """Resolve a logical target, or use the legacy fallback when targetless."""
        if callback_target is not None:
            endpoint = self.callback_targets.get(callback_target)
            if endpoint is None:
                raise UnknownCallbackTargetError(
                    f"unknown callback target: {callback_target}"
                )
            return endpoint
        if self.callback_forward_url is not None:
            return self.callback_forward_url
        raise MissingCallbackRouteError("no callback delivery route is configured")

    def validate_startup(self) -> None:
        if not self.telegram_token:
            raise ValueError("TELEGRAM_TOKEN is required")
