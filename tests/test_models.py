import pytest
from pydantic import ValidationError

from telegram_bot.models import Button, MessageRequest


def test_blank_message_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MessageRequest(text="   ")


def test_url_button_without_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires url"):
        Button(type="url", text="View")


def test_url_button_with_action_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not include action"):
        Button(type="url", text="View", url="https://example.com", action="x")


def test_url_button_rejects_non_http_scheme() -> None:
    with pytest.raises(ValidationError, match="http:// or https://"):
        Button(type="url", text="View", url="ftp://example.com/file")


def test_action_button_without_action_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires action"):
        Button(type="action", text="Choose")


def test_action_button_with_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not include url"):
        Button(type="action", text="Choose", action="task:a", url="https://example.com")


def test_action_over_64_utf8_bytes_is_rejected() -> None:
    with pytest.raises(ValidationError, match="64 UTF-8 bytes"):
        Button(type="action", text="Choose", action="你" * 22)


def test_valid_url_and_action_buttons() -> None:
    url = Button(type="url", text="View PR", url="https://example.com/pr/1")
    action = Button(type="action", text="Solution A", action="task123:solution_a")
    assert url.url == "https://example.com/pr/1"
    assert action.action == "task123:solution_a"
