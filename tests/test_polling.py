import asyncio
from types import SimpleNamespace

import pytest
from telegram.error import NetworkError

from telegram_bot.config import Settings
from telegram_bot.telegram_client import TelegramClient


class PollingBot:
    def __init__(self) -> None:
        self.calls = 0

    async def get_updates(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise NetworkError("temporary network problem")
        if self.calls == 2:
            return [
                SimpleNamespace(
                    update_id=41,
                    callback_query=SimpleNamespace(id="callback-41"),
                )
            ]
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_polling_recovers_from_network_error(monkeypatch) -> None:
    bot = PollingBot()
    client = TelegramClient(Settings(telegram_token="x"), bot=bot)
    handled = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def handler(query) -> None:
        handled.append(query.id)

    monkeypatch.setattr("telegram_bot.telegram_client.asyncio.sleep", no_sleep)

    with pytest.raises(asyncio.CancelledError):
        await client.poll_callbacks(handler)

    assert bot.calls == 3
    assert handled == ["callback-41"]


@pytest.mark.asyncio
async def test_polling_continues_after_callback_handler_failure() -> None:
    class TwoUpdateBot:
        def __init__(self) -> None:
            self.calls = 0

        async def get_updates(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return [
                    SimpleNamespace(
                        update_id=1,
                        callback_query=SimpleNamespace(id="first"),
                    ),
                    SimpleNamespace(
                        update_id=2,
                        callback_query=SimpleNamespace(id="second"),
                    ),
                ]
            raise asyncio.CancelledError

    handled: list[str] = []

    async def handler(query) -> None:
        handled.append(query.id)
        if query.id == "first":
            raise RuntimeError("delivery failed")

    client = TelegramClient(Settings(telegram_token="x"), bot=TwoUpdateBot())
    with pytest.raises(asyncio.CancelledError):
        await client.poll_callbacks(handler)

    assert handled == ["first", "second"]
