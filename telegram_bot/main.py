"""FastAPI application entrypoint and service lifecycle."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .callback_service import CallbackService
from .console_routes import WEB_DIRECTORY, console_router
from .config import Settings
from .routes import router
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    telegram_client: TelegramClient | None = None,
    http_client: httpx.AsyncClient | None = None,
    enable_lifespan: bool = True,
) -> FastAPI:
    app_settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app_settings.validate_startup()
        client = telegram_client or TelegramClient(app_settings)
        forwarding_client = http_client or httpx.AsyncClient(timeout=10.0)
        owns_http_client = http_client is None
        polling_task: asyncio.Task | None = None
        client_initialized = False

        try:
            await client.initialize()
            client_initialized = True
            app.state.telegram_client_initialized = True
            callback_service = CallbackService(app_settings, client, forwarding_client)
            app.state.telegram_client = client
            app.state.callback_service = callback_service
            polling_task = asyncio.create_task(
                client.poll_callbacks(callback_service.handle),
                name="telegram-callback-poller",
            )
            app.state.polling_task = polling_task
            logger.info(
                "service started: listen=%s:%s",
                app_settings.app_host,
                app_settings.app_port,
            )
            yield
        finally:
            if polling_task is not None:
                polling_task.cancel()
                with suppress(asyncio.CancelledError):
                    await polling_task
            if owns_http_client:
                await forwarding_client.aclose()
            if client_initialized:
                await client.shutdown()
            app.state.telegram_client_initialized = False

    app = FastAPI(
        title="Ruyi Telegram Bot",
        version="0.1.0",
        lifespan=lifespan if enable_lifespan else None,
    )
    app.state.settings = app_settings
    app.state.polling_task = None
    app.state.telegram_client_initialized = False
    if telegram_client is not None:
        app.state.telegram_client = telegram_client
    app.include_router(router)
    app.include_router(console_router)
    app.mount(
        "/console/assets",
        StaticFiles(directory=WEB_DIRECTORY),
        name="console-assets",
    )
    return app


app = create_app()
