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


def test_url_button_with_option_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not include option_id"):
        Button(type="url", text="View", url="https://example.com", option_id="x")


def test_url_button_rejects_non_http_scheme() -> None:
    with pytest.raises(ValidationError, match="http:// or https://"):
        Button(type="url", text="View", url="ftp://example.com/file")


def test_action_button_without_option_id_or_action_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires option_id or action"):
        Button(type="action", text="Choose")


def test_action_button_with_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not include url"):
        Button(type="action", text="Choose", action="task:a", url="https://example.com")


def test_action_button_cannot_mix_option_id_and_legacy_action() -> None:
    with pytest.raises(ValidationError, match="must not include both"):
        Button(type="action", text="Choose", option_id="retry", action="task:retry")


def test_blank_option_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="option_id must not be blank"):
        Button(type="action", text="Choose", option_id="   ")


def test_legacy_action_rejects_reserved_prefix() -> None:
    with pytest.raises(ValidationError, match="reserved prefix"):
        Button(type="action", text="Old", action="h1|legacy")


def test_action_over_64_utf8_bytes_is_rejected() -> None:
    with pytest.raises(ValidationError, match="64 UTF-8 bytes"):
        Button(type="action", text="Choose", action="你" * 22)


def test_valid_url_and_action_buttons() -> None:
    url = Button(type="url", text="View PR", url="https://example.com/pr/1")
    action = Button(type="action", text="Solution A", action="task123:solution_a")
    assert url.url == "https://example.com/pr/1"
    assert action.action == "task123:solution_a"


@pytest.mark.parametrize("count", [1, 2, 4])
def test_new_interaction_supports_dynamic_action_option_count(count: int) -> None:
    request = MessageRequest(
        text="Choose",
        interaction_id="decision-1",
        callback_target="test-workflow",
        buttons=[
            Button(type="action", text=f"Option {index}", option_id=f"option-{index}")
            for index in range(count)
        ],
    )

    assert len(request.buttons) == count
    assert request.interaction_id == "decision-1"
    assert request.callback_target == "test-workflow"


def test_manual_review_is_an_ordinary_option() -> None:
    request = MessageRequest(
        text="Choose",
        interaction_id="decision-2",
        buttons=[Button(type="action", text="Manual review", option_id="manual")],
    )

    assert request.buttons[0].option_id == "manual"


def test_new_action_request_requires_interaction_id() -> None:
    with pytest.raises(ValidationError, match="interaction_id"):
        MessageRequest(
            text="Choose",
            buttons=[Button(type="action", text="Retry", option_id="retry")],
        )


def test_blank_interaction_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="interaction_id must not be blank"):
        MessageRequest(
            text="Choose",
            interaction_id="   ",
            buttons=[Button(type="action", text="Retry", option_id="retry")],
        )


def test_request_cannot_mix_new_and_legacy_actions() -> None:
    with pytest.raises(ValidationError, match="must not mix"):
        MessageRequest(
            text="Choose",
            interaction_id="decision-3",
            buttons=[
                Button(type="action", text="New", option_id="new"),
                Button(type="action", text="Old", action="task:old"),
            ],
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"interaction_id": "unused"},
        {"callback_target": "unused"},
    ],
)
def test_interaction_fields_require_new_action_buttons(extra: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="new action buttons"):
        MessageRequest(text="Plain", **extra)


def test_plain_text_and_url_only_requests_need_no_interaction() -> None:
    plain = MessageRequest(text="Plain")
    linked = MessageRequest(
        text="Linked",
        buttons=[Button(type="url", text="View", url="https://example.com")],
    )

    assert plain.interaction_id is None
    assert linked.interaction_id is None


def test_unknown_request_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="callback_url"):
        MessageRequest(text="Choose", callback_url="http://attacker.local/callback")
