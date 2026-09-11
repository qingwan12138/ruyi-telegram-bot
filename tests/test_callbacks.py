import json
from types import SimpleNamespace

import httpx
import pytest

from telegram_bot.callback_service import CallbackService
from telegram_bot.config import Settings


class FakeTelegramClient:
    def __init__(self, *, answer_error: Exception | None = None) -> None:
        self.answered: list[str] = []
        self.answer_error = answer_error

    async def answer_callback_query(self, callback_query_id: str) -> None:
        self.answered.append(callback_query_id)
        if self.answer_error:
            raise self.answer_error


def make_query(action: str = "task123:solution_a"):
    return SimpleNamespace(
        id="callback-1",
        data=action,
        message=SimpleNamespace(chat_id=123456789, message_id=456),
        from_user=SimpleNamespace(id=789, username="example"),
    )


@pytest.mark.asyncio
async def test_callback_is_answered_and_parsed_without_forward_url() -> None:
    telegram = FakeTelegramClient()
    async with httpx.AsyncClient() as http_client:
        service = CallbackService(Settings(), telegram, http_client)
        event = await service.handle(make_query())

    assert telegram.answered == ["callback-1"]
    assert event is not None
    assert event.event == "telegram.action"
    assert event.action == "task123:solution_a"
    assert event.chat_id == 123456789
    assert event.message_id == 456
    assert event.user_id == 789
    assert event.username == "example"
    assert event.callback_query_id == "callback-1"


@pytest.mark.asyncio
async def test_callback_is_forwarded_as_json() -> None:
    captured: list[dict] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(204)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    telegram = FakeTelegramClient()
    service = CallbackService(
        Settings(callback_forward_url="http://upstream.local/callback"),
        telegram,
        http_client,
    )

    try:
        event = await service.handle(make_query())
    finally:
        await http_client.aclose()

    assert event is not None
    assert captured == [
        {
            "event": "telegram.action",
            "action": "task123:solution_a",
            "chat_id": 123456789,
            "message_id": 456,
            "user_id": 789,
            "username": "example",
            "callback_query_id": "callback-1",
        }
    ]


@pytest.mark.asyncio
async def test_forward_failure_does_not_escape_handler() -> None:
    async def failing_receiver(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("upstream unavailable", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(failing_receiver))
    telegram = FakeTelegramClient()
    service = CallbackService(
        Settings(callback_forward_url="http://upstream.local/callback"),
        telegram,
        http_client,
    )

    try:
        event = await service.handle(make_query())
    finally:
        await http_client.aclose()

    assert event is not None
    assert telegram.answered == ["callback-1"]


@pytest.mark.asyncio
async def test_answer_failure_does_not_block_callback_forwarding() -> None:
    captured = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    telegram = FakeTelegramClient(answer_error=RuntimeError("telegram down"))
    service = CallbackService(
        Settings(callback_forward_url="http://upstream.local/callback"),
        telegram,
        http_client,
    )

    try:
        event = await service.handle(make_query())
    finally:
        await http_client.aclose()

    assert event is not None
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_forward_error_log_does_not_echo_forward_url_secret(caplog) -> None:
    async def failing_receiver(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed request to http://upstream.local/callback?token=FORWARDSECRET",
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(failing_receiver))
    service = CallbackService(
        Settings(callback_forward_url="http://upstream.local/callback?token=FORWARDSECRET"),
        FakeTelegramClient(),
        http_client,
    )

    try:
        await service.handle(make_query())
    finally:
        await http_client.aclose()

    assert "FORWARDSECRET" not in caplog.text
