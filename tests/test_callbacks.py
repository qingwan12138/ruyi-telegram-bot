import json
from types import SimpleNamespace

import httpx
import pytest

from telegram_bot.callback_data import encode_interaction_callback
from telegram_bot.callback_service import CallbackService
from telegram_bot.config import Settings


class FakeTelegramClient:
    def __init__(self, *, answer_error=None, send_error=None, trace=None) -> None:
        self.answered: list[str] = []
        self.answer_texts: list[str | None] = []
        self.sent: list[dict] = []
        self.answer_error = answer_error
        self.send_error = send_error
        self.trace = trace

    async def answer_callback_query(self, callback_query_id, *, text=None) -> None:
        self.answered.append(callback_query_id)
        self.answer_texts.append(text)
        if self.trace is not None:
            self.trace.append("acknowledge")
        if self.answer_error:
            raise self.answer_error

    async def send_message(self, text, *, chat_id=None, **kwargs):
        self.sent.append({"text": text, "chat_id": chat_id})
        if self.trace is not None:
            self.trace.append("feedback")
        if self.send_error:
            raise self.send_error
        return SimpleNamespace(chat_id=chat_id, message_id=999)


def make_query(data: str = "task123:solution_a"):
    return SimpleNamespace(
        id="callback-1",
        data=data,
        message=SimpleNamespace(chat_id=123456789, message_id=456),
        from_user=SimpleNamespace(id=789, username="example"),
    )


def interaction_query(
    *,
    target: str | None = "target-a",
    interaction_id: str = "decision-789",
    option_id: str = "option-2",
):
    return make_query(encode_interaction_callback(target, interaction_id, option_id))


async def run_service(settings, telegram, receiver, query=None):
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    service = CallbackService(settings, telegram, http_client)
    try:
        return await service.handle(query or interaction_query())
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_interaction_is_acknowledged_parsed_and_delivered() -> None:
    captured: list[dict] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(204)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert telegram.answered == ["callback-1"]
    assert telegram.answer_texts == ["Selection received."]
    assert event is not None
    assert event.event == "telegram.interaction.selected"
    assert event.interaction_id == "decision-789"
    assert event.option_id == "option-2"
    assert event.chat_id == 123456789
    assert event.message_id == 456
    assert event.user_id == 789
    assert event.username == "example"
    assert event.callback_query_id == "callback-1"
    assert captured == [event.model_dump(mode="json")]
    assert telegram.sent == [
        {"text": "Selection delivered successfully.", "chat_id": 123456789}
    ]


@pytest.mark.asyncio
async def test_callback_is_acknowledged_before_delivery_and_feedback() -> None:
    trace: list[str] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        trace.append("forward")
        return httpx.Response(204)

    await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        FakeTelegramClient(trace=trace),
        receiver,
    )

    assert trace == ["acknowledge", "forward", "feedback"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "expected_host"),
    [("target-a", "a.local"), ("target-b", "b.local")],
)
async def test_explicit_target_routes_to_its_configured_endpoint(target, expected_host) -> None:
    requested_hosts: list[str] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(200)

    await run_service(
        Settings(
            callback_targets={
                "target-a": "http://a.local/callback",
                "target-b": "http://b.local/callback",
            }
        ),
        FakeTelegramClient(),
        receiver,
        interaction_query(target=target),
    )

    assert requested_hosts == [expected_host]


@pytest.mark.asyncio
async def test_new_interaction_with_empty_target_uses_legacy_fallback() -> None:
    requested_urls: list[str] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200)

    event = await run_service(
        Settings(callback_forward_url="http://fallback.local/callback"),
        FakeTelegramClient(),
        receiver,
        interaction_query(target=None),
    )

    assert event is not None
    assert event.event == "telegram.interaction.selected"
    assert requested_urls == ["http://fallback.local/callback"]


@pytest.mark.asyncio
async def test_legacy_action_contract_is_preserved_with_fallback() -> None:
    captured: list[dict] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(204)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_forward_url="http://fallback.local/callback"),
        telegram,
        receiver,
        make_query(),
    )

    assert event is not None
    assert event.event == "telegram.action"
    assert event.action == "task123:solution_a"
    assert captured == [event.model_dump(mode="json")]
    assert telegram.sent[0]["text"] == "Selection delivered successfully."


@pytest.mark.asyncio
async def test_incomplete_callback_is_acknowledged_but_not_forwarded() -> None:
    forwarded = False

    async def receiver(request: httpx.Request) -> httpx.Response:
        nonlocal forwarded
        forwarded = True
        return httpx.Response(204)

    query = interaction_query()
    query.message = None
    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
        query,
    )

    assert event is None
    assert telegram.answer_texts == ["Selection received."]
    assert telegram.sent == []
    assert forwarded is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 500])
async def test_http_error_sends_delivery_failure_feedback(status_code: int) -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert event is not None
    assert telegram.sent == [
        {"text": "Failed to deliver your selection.", "chat_id": 123456789}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", ["timeout", "network"])
async def test_transport_error_sends_delivery_failure_feedback(failure_type: str) -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        if failure_type == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        raise httpx.ConnectError("unavailable", request=request)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert event is not None
    assert telegram.sent[0]["text"] == "Failed to deliver your selection."


@pytest.mark.asyncio
async def test_unknown_explicit_target_sends_failure_without_fallback() -> None:
    forwarded = False

    async def receiver(request: httpx.Request) -> httpx.Response:
        nonlocal forwarded
        forwarded = True
        return httpx.Response(200)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(
            callback_forward_url="http://fallback.local/callback",
            callback_targets={"known": "http://known.local/callback"},
        ),
        telegram,
        receiver,
        interaction_query(target="missing"),
    )

    assert event is not None
    assert forwarded is False
    assert telegram.sent[0]["text"] == "Failed to deliver your selection."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed",
    [
        "h1|x|1|ia",
        "h1|0|0|option",
        "h1|0|1|i",
        "h1|5|1|abc",
        "h1|0|1|i" + "o" * 57,
    ],
)
async def test_malformed_new_callback_is_safely_rejected(malformed: str) -> None:
    forwarded = False

    async def receiver(request: httpx.Request) -> httpx.Response:
        nonlocal forwarded
        forwarded = True
        return httpx.Response(200)

    telegram = FakeTelegramClient()
    event = await run_service(Settings(), telegram, receiver, make_query(malformed))

    assert event is None
    assert forwarded is False
    assert telegram.sent[0]["text"] == "Failed to deliver your selection."


@pytest.mark.asyncio
async def test_answer_failure_does_not_block_callback_delivery() -> None:
    captured: list[httpx.Request] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    telegram = FakeTelegramClient(answer_error=RuntimeError("telegram down"))
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert event is not None
    assert len(captured) == 1
    assert telegram.sent[0]["text"] == "Selection delivered successfully."


@pytest.mark.asyncio
async def test_feedback_send_failure_does_not_escape_handler() -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    telegram = FakeTelegramClient(send_error=RuntimeError("telegram down"))
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert event is not None
    assert telegram.sent[0]["text"] == "Selection delivered successfully."


@pytest.mark.asyncio
async def test_delivery_error_log_does_not_echo_endpoint_secret(caplog) -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed request to http://a.local/callback?token=FORWARDSECRET",
            request=request,
        )

    await run_service(
        Settings(
            callback_targets={
                "target-a": "http://a.local/callback?token=FORWARDSECRET"
            }
        ),
        FakeTelegramClient(),
        receiver,
    )

    assert "FORWARDSECRET" not in caplog.text
    assert "http://a.local" not in caplog.text


@pytest.mark.asyncio
async def test_feedback_never_claims_business_success() -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    telegram = FakeTelegramClient()
    await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    feedback = telegram.sent[0]["text"]
    assert feedback == "Selection delivered successfully."
    assert all(word not in feedback.lower() for word in ("ai", "test passed", "pr created"))
