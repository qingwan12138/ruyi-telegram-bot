from types import SimpleNamespace

import pytest

from telegram_bot.config import Settings
from telegram_bot.callback_data import decode_interaction_callback
from telegram_bot.telegram_client import MissingChatIdError, TelegramClient


class FakeBot:
    def __init__(self) -> None:
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=777)


@pytest.mark.asyncio
async def test_default_chat_id_is_used() -> None:
    bot = FakeBot()
    client = TelegramClient(
        Settings(telegram_token="x", telegram_chat_id=123),
        bot=bot,
    )

    result = await client.send_message("hello")

    assert result.chat_id == 123
    assert result.message_id == 777
    assert bot.calls[0]["chat_id"] == 123
    assert bot.calls[0]["reply_markup"] is None


@pytest.mark.asyncio
async def test_explicit_chat_id_overrides_default() -> None:
    bot = FakeBot()
    client = TelegramClient(
        Settings(telegram_token="x", telegram_chat_id=123),
        bot=bot,
    )

    result = await client.send_message("hello", chat_id=456)

    assert result.chat_id == 456
    assert bot.calls[0]["chat_id"] == 456


def test_missing_chat_id_is_clear_error() -> None:
    client = TelegramClient(Settings(telegram_token="x"), bot=FakeBot())
    with pytest.raises(MissingChatIdError, match="chat_id is required"):
        client.resolve_chat_id(None)


def test_build_keyboard_renders_url_and_action_buttons() -> None:
    from telegram_bot.models import Button

    keyboard = TelegramClient.build_keyboard(
        [
            Button(type="url", text="View PR", url="https://example.com/pr/1"),
            Button(type="action", text="Solution A", action="task:solution_a"),
        ]
    )

    assert keyboard is not None
    row = keyboard.inline_keyboard[0]
    assert row[0].text == "View PR"
    assert row[0].url == "https://example.com/pr/1"
    assert row[0].callback_data is None
    assert row[1].text == "Solution A"
    assert row[1].callback_data == "task:solution_a"
    assert row[1].url is None


def test_keyboard_uses_at_most_two_buttons_per_row() -> None:
    from telegram_bot.models import Button

    buttons = [
        Button(type="action", text=f"B{i}", action=f"task:{i}") for i in range(5)
    ]
    keyboard = TelegramClient.build_keyboard(buttons)

    assert keyboard is not None
    assert [len(row) for row in keyboard.inline_keyboard] == [2, 2, 1]


def test_build_keyboard_encodes_new_interaction_button() -> None:
    from telegram_bot.models import Button

    keyboard = TelegramClient.build_keyboard(
        [Button(type="action", text="Retry", option_id="retry")],
        interaction_id="decision-1",
        callback_target="target-a",
    )

    assert keyboard is not None
    decoded = decode_interaction_callback(keyboard.inline_keyboard[0][0].callback_data)
    assert decoded.callback_target == "target-a"
    assert decoded.interaction_id == "decision-1"
    assert decoded.option_id == "retry"


def test_build_keyboard_encodes_empty_target_for_new_fallback() -> None:
    from telegram_bot.models import Button

    keyboard = TelegramClient.build_keyboard(
        [Button(type="action", text="Manual", option_id="manual")],
        interaction_id="decision-2",
        callback_target=None,
    )

    assert keyboard is not None
    callback_data = keyboard.inline_keyboard[0][0].callback_data
    assert callback_data.startswith("h1|0|")
    assert decode_interaction_callback(callback_data).callback_target is None


@pytest.mark.asyncio
async def test_answer_callback_query_passes_feedback_text() -> None:
    class CallbackBot:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def answer_callback_query(self, **kwargs) -> None:
            self.calls.append(kwargs)

    bot = CallbackBot()
    client = TelegramClient(Settings(telegram_token="x"), bot=bot)

    await client.answer_callback_query(
        "callback-1",
        text="Selection received.",
    )

    assert bot.calls == [
        {
            "callback_query_id": "callback-1",
            "text": "Selection received.",
        }
    ]


@pytest.mark.asyncio
async def test_send_error_log_does_not_echo_token(caplog) -> None:
    class SecretLeakingBot:
        async def send_message(self, **kwargs):
            raise RuntimeError("https://api.telegram.org/botSUPERSECRET/sendMessage")

    client = TelegramClient(
        Settings(telegram_token="SUPERSECRET", telegram_chat_id=123),
        bot=SecretLeakingBot(),
    )

    from telegram_bot.telegram_client import TelegramSendError

    with pytest.raises(TelegramSendError):
        await client.send_message("hello")

    assert "SUPERSECRET" not in caplog.text
