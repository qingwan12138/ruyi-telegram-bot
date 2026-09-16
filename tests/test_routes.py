from dataclasses import dataclass

from fastapi.testclient import TestClient

from telegram_bot.config import Settings
from telegram_bot.main import create_app
from telegram_bot.telegram_client import SendResult, TelegramSendError


@dataclass
class FakeTelegramClient:
    result: SendResult = SendResult(chat_id=100, message_id=200)
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict] = []

    async def send_message(
        self,
        text,
        *,
        chat_id=None,
        buttons=(),
        interaction_id=None,
        callback_target=None,
    ):
        self.calls.append(
            {
                "text": text,
                "chat_id": chat_id,
                "buttons": list(buttons),
                "interaction_id": interaction_id,
                "callback_target": callback_target,
            }
        )
        if self.error:
            raise self.error
        return SendResult(
            chat_id=chat_id if chat_id is not None else self.result.chat_id,
            message_id=self.result.message_id,
        )


def make_client(
    fake: FakeTelegramClient,
    settings: Settings | None = None,
) -> TestClient:
    app = create_app(
        settings=settings
        or Settings(
            telegram_token="test-token",
            telegram_chat_id=100,
            callback_forward_url="http://fallback.local/callback",
        ),
        telegram_client=fake,
        enable_lifespan=False,
    )
    return TestClient(app)


def test_plain_text_message_succeeds() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post("/api/v1/messages", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json() == {"success": True, "chat_id": 100, "message_id": 200}
    assert fake.calls[0]["text"] == "hello"
    assert fake.calls[0]["chat_id"] is None


def test_request_chat_id_is_passed_as_override() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={"text": "override", "chat_id": -123456},
        )

    assert response.status_code == 200
    assert response.json()["chat_id"] == -123456
    assert fake.calls[0]["chat_id"] == -123456


def test_telegram_send_error_maps_to_503() -> None:
    fake = FakeTelegramClient(error=TelegramSendError("boom"))
    with make_client(fake) as client:
        response = client.post("/api/v1/messages", json={"text": "hello"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Telegram notification failed"}


def test_url_button_reaches_telegram_client() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "PR created",
                "buttons": [
                    {"type": "url", "text": "View PR", "url": "https://example.com/pr/1"}
                ],
            },
        )

    assert response.status_code == 200
    button = fake.calls[0]["buttons"][0]
    assert button.type == "url"
    assert button.url == "https://example.com/pr/1"


def test_action_button_reaches_telegram_client() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "buttons": [
                    {"type": "action", "text": "Solution A", "action": "task:solution_a"}
                ],
            },
        )

    assert response.status_code == 200
    button = fake.calls[0]["buttons"][0]
    assert button.type == "action"
    assert button.action == "task:solution_a"


def test_known_interaction_target_reaches_telegram_client() -> None:
    fake = FakeTelegramClient()
    settings = Settings(
        telegram_token="test-token",
        telegram_chat_id=100,
        callback_targets={"target-a": "http://a.local/callback"},
    )
    with make_client(fake, settings) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "interaction_id": "decision-1",
                "callback_target": "target-a",
                "buttons": [
                    {"type": "action", "text": "Retry", "option_id": "retry"}
                ],
            },
        )

    assert response.status_code == 200
    assert fake.calls[0]["interaction_id"] == "decision-1"
    assert fake.calls[0]["callback_target"] == "target-a"


def test_new_interaction_without_target_uses_configured_fallback() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "interaction_id": "decision-2",
                "buttons": [
                    {"type": "action", "text": "Manual", "option_id": "manual"}
                ],
            },
        )

    assert response.status_code == 200
    assert fake.calls[0]["callback_target"] is None


def test_duplicate_option_id_is_rejected_before_telegram_send() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "interaction_id": "decision-duplicate",
                "buttons": [
                    {"type": "action", "text": "Retry now", "option_id": "retry"},
                    {"type": "action", "text": "Retry later", "option_id": "retry"},
                ],
            },
        )

    assert response.status_code == 422
    assert "option_id must be unique within an interaction" in response.text
    assert fake.calls == []


def test_unknown_explicit_target_is_rejected_without_fallback() -> None:
    fake = FakeTelegramClient()
    settings = Settings(
        telegram_token="test-token",
        telegram_chat_id=100,
        callback_forward_url="http://fallback.local/callback",
        callback_targets={"known": "http://known.local/callback"},
    )
    with make_client(fake, settings) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "interaction_id": "decision-3",
                "callback_target": "missing",
                "buttons": [
                    {"type": "action", "text": "Retry", "option_id": "retry"}
                ],
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "unknown callback target: missing"}
    assert fake.calls == []


def test_action_button_without_any_delivery_route_is_rejected() -> None:
    settings = Settings(telegram_token="test-token", telegram_chat_id=100)
    for payload in (
        {
            "text": "New",
            "interaction_id": "decision-4",
            "buttons": [{"type": "action", "text": "Retry", "option_id": "retry"}],
        },
        {
            "text": "Legacy",
            "buttons": [{"type": "action", "text": "Old", "action": "task:old"}],
        },
    ):
        fake = FakeTelegramClient()
        with make_client(fake, settings) as client:
            response = client.post("/api/v1/messages", json=payload)
        assert response.status_code == 422
        assert response.json() == {
            "detail": "action buttons require a callback delivery route"
        }
        assert fake.calls == []


def test_caller_cannot_submit_arbitrary_callback_url() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "interaction_id": "decision-5",
                "callback_url": "http://attacker.local/callback",
                "buttons": [
                    {"type": "action", "text": "Retry", "option_id": "retry"}
                ],
            },
        )

    assert response.status_code == 422
    assert fake.calls == []


def test_interaction_callback_data_over_limit_is_rejected_before_send() -> None:
    fake = FakeTelegramClient()
    with make_client(fake) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "text": "Choose",
                "interaction_id": "i",
                "buttons": [
                    {"type": "action", "text": "Too long", "option_id": "o" * 57}
                ],
            },
        )

    assert response.status_code == 422
    assert "64 UTF-8 bytes" in response.json()["detail"]
    assert fake.calls == []


def test_missing_chat_id_error_maps_to_422() -> None:
    from telegram_bot.telegram_client import MissingChatIdError

    fake = FakeTelegramClient(error=MissingChatIdError("chat_id is required"))
    with make_client(fake) as client:
        response = client.post("/api/v1/messages", json={"text": "hello"})

    assert response.status_code == 422
    assert response.json() == {"detail": "chat_id is required"}
