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

    async def send_message(self, text, *, chat_id=None, buttons=()):
        self.calls.append({"text": text, "chat_id": chat_id, "buttons": list(buttons)})
        if self.error:
            raise self.error
        return SendResult(
            chat_id=chat_id if chat_id is not None else self.result.chat_id,
            message_id=self.result.message_id,
        )


def make_client(fake: FakeTelegramClient) -> TestClient:
    app = create_app(
        settings=Settings(telegram_token="test-token", telegram_chat_id=100),
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


def test_missing_chat_id_error_maps_to_422() -> None:
    from telegram_bot.telegram_client import MissingChatIdError

    fake = FakeTelegramClient(error=MissingChatIdError("chat_id is required"))
    with make_client(fake) as client:
        response = client.post("/api/v1/messages", json={"text": "hello"})

    assert response.status_code == 422
    assert response.json() == {"detail": "chat_id is required"}
