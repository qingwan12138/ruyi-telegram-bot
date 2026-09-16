import json
from types import SimpleNamespace

import httpx
import pytest

from telegram_bot.callback_data import encode_interaction_callback
from telegram_bot.callback_service import CallbackService, DeliveryOutcome
from telegram_bot.config import Settings
from telegram_bot.models import CallbackEvent, InteractionResult


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


async def run_delivery(
    settings,
    receiver,
    *,
    target="target-a",
    event=None,
    follow_redirects=False,
):
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(receiver),
        follow_redirects=follow_redirects,
    )
    service = CallbackService(settings, FakeTelegramClient(), http_client)
    event = event or InteractionResult(
        interaction_id="decision-789",
        option_id="option-2",
        chat_id=123456789,
        message_id=456,
        user_id=789,
        callback_query_id="callback-1",
    )
    try:
        return await service._deliver(event, target)
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
    assert event.option_text is None
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
async def test_interaction_option_text_is_recovered_from_matching_button() -> None:
    captured: list[dict] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(204)

    query = interaction_query()
    option_text = "更换 upstream 版本并重新生成 package"
    query.message.reply_markup = SimpleNamespace(
        inline_keyboard=[
            [SimpleNamespace(text="View", url="https://example.com")],
            [
                SimpleNamespace(callback_data="unrelated", text="Other"),
                SimpleNamespace(callback_data=query.data, text=option_text),
            ],
        ]
    )

    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        FakeTelegramClient(),
        receiver,
        query,
    )

    assert event is not None
    assert event.option_text == option_text
    assert captured[0]["option_text"] == option_text
    assert option_text not in query.data


@pytest.mark.parametrize(
    "query",
    [
        SimpleNamespace(message=None, data="callback"),
        SimpleNamespace(
            message=SimpleNamespace(reply_markup=None),
            data="callback",
        ),
        SimpleNamespace(
            message=SimpleNamespace(
                reply_markup=SimpleNamespace(
                    inline_keyboard=[
                        [SimpleNamespace(callback_data="different", text="Other")]
                    ]
                )
            ),
            data="callback",
        ),
        SimpleNamespace(message=SimpleNamespace(), data="callback"),
    ],
)
def test_find_option_text_safely_returns_none_when_unavailable(query) -> None:
    assert CallbackService._find_option_text(query, query.data) is None


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
    assert "option_text" not in captured[0]
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
@pytest.mark.parametrize("status_code", [400, 404, 500])
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
@pytest.mark.parametrize(
    "failure",
    [
        lambda request: httpx.ReadTimeout("slow", request=request),
        lambda request: httpx.ConnectTimeout("slow", request=request),
        lambda request: httpx.ConnectError("unavailable", request=request),
        lambda request: httpx.ReadError("connection reset", request=request),
    ],
)
async def test_transport_uncertainty_sends_unknown_feedback_without_retry(failure) -> None:
    attempts = 0

    async def receiver(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise failure(request)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert event is not None
    assert attempts == 1
    assert telegram.sent[0]["text"] == (
        "Could not confirm delivery of your selection."
    )


@pytest.mark.asyncio
async def test_http_409_sends_already_resolved_feedback() -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        telegram,
        receiver,
    )

    assert event is not None
    assert telegram.sent == [
        {
            "text": "This interaction has already been resolved.",
            "chat_id": 123456789,
        }
    ]


@pytest.mark.asyncio
async def test_legacy_http_409_is_failed_with_failure_feedback() -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409)

    telegram = FakeTelegramClient()
    event = await run_service(
        Settings(callback_forward_url="http://fallback.local/callback"),
        telegram,
        receiver,
        make_query(),
    )

    assert isinstance(event, CallbackEvent)
    assert telegram.sent == [
        {"text": "Failed to deliver your selection.", "chat_id": 123456789}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, DeliveryOutcome.DELIVERED),
        (204, DeliveryOutcome.DELIVERED),
        (409, DeliveryOutcome.ALREADY_RESOLVED),
        (400, DeliveryOutcome.FAILED),
        (404, DeliveryOutcome.FAILED),
        (500, DeliveryOutcome.FAILED),
    ],
)
async def test_delivery_http_status_outcomes(status_code, expected) -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    outcome = await run_delivery(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        receiver,
    )

    assert outcome is expected


@pytest.mark.asyncio
async def test_legacy_http_409_outcome_is_failed() -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409)

    legacy_event = CallbackEvent(
        action="task123:solution_a",
        chat_id=123456789,
        message_id=456,
        user_id=789,
        callback_query_id="callback-1",
    )
    outcome = await run_delivery(
        Settings(callback_forward_url="http://fallback.local/callback"),
        receiver,
        target=None,
        event=legacy_event,
    )

    assert outcome is DeliveryOutcome.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [302, 307])
async def test_redirect_is_failed_without_following_location(status_code: int) -> None:
    requested_hosts: list[str] = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.host == "a.local":
            return httpx.Response(
                status_code,
                headers={"Location": "http://redirected.local/callback"},
            )
        return httpx.Response(204)

    outcome = await run_delivery(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        receiver,
        follow_redirects=True,
    )

    assert outcome is DeliveryOutcome.FAILED
    assert requested_hosts == ["a.local"]


@pytest.mark.asyncio
async def test_route_resolution_failure_outcome_is_failed() -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        raise AssertionError("route failure must not attempt HTTP delivery")

    outcome = await run_delivery(Settings(), receiver, target=None)

    assert outcome is DeliveryOutcome.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        lambda request: httpx.ReadTimeout("slow", request=request),
        lambda request: httpx.ConnectTimeout("slow", request=request),
        lambda request: httpx.ConnectError("unavailable", request=request),
        lambda request: httpx.ReadError("connection reset", request=request),
    ],
)
async def test_transport_uncertainty_outcome_is_unknown(failure) -> None:
    async def receiver(request: httpx.Request) -> httpx.Response:
        raise failure(request)

    outcome = await run_delivery(
        Settings(callback_targets={"target-a": "http://a.local/callback"}),
        receiver,
    )

    assert outcome is DeliveryOutcome.UNKNOWN


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
