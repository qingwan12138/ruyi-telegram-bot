import asyncio

from fastapi.testclient import TestClient

from telegram_bot.config import Settings
from telegram_bot.main import create_app


class LifecycleTelegramClient:
    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False
        self.poll_cancelled = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def poll_callbacks(self, handler) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.poll_cancelled = True
            raise

    async def send_message(self, *args, **kwargs):
        raise AssertionError("not used")

    async def answer_callback_query(self, callback_query_id: str) -> None:
        return None


def test_lifespan_initializes_poller_and_shuts_down_client() -> None:
    telegram = LifecycleTelegramClient()
    app = create_app(
        settings=Settings(telegram_token="test-token"),
        telegram_client=telegram,
    )

    with TestClient(app) as client:
        assert telegram.initialized is True
        assert client.get("/health").status_code == 200
        assert hasattr(app.state, "callback_service")

    assert telegram.poll_cancelled is True
    assert telegram.shutdown_called is True
