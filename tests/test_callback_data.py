import pytest

from telegram_bot.callback_data import (
    CallbackDataError,
    decode_interaction_callback,
    encode_interaction_callback,
)


def test_callback_data_round_trips_delimiters_and_unicode() -> None:
    encoded = encode_interaction_callback("目标|一", "决策|42", "选项|甲")
    decoded = decode_interaction_callback(encoded)

    assert decoded.callback_target == "目标|一"
    assert decoded.interaction_id == "决策|42"
    assert decoded.option_id == "选项|甲"


def test_unicode_lengths_count_characters_but_limit_counts_bytes() -> None:
    encoded = encode_interaction_callback("目标", "决策", "选项")

    assert encoded.startswith("h1|2|2|")
    assert decode_interaction_callback(encoded).option_id == "选项"


def test_empty_target_round_trips_for_fallback() -> None:
    encoded = encode_interaction_callback(None, "decision-1", "retry")
    decoded = decode_interaction_callback(encoded)

    assert encoded.startswith("h1|0|10|")
    assert decoded.callback_target is None
    assert decoded.interaction_id == "decision-1"


def test_callback_data_accepts_exactly_64_utf8_bytes() -> None:
    encoded = encode_interaction_callback(None, "i", "o" * 56)

    assert len(encoded.encode("utf-8")) == 64
    assert decode_interaction_callback(encoded).option_id == "o" * 56


def test_callback_data_rejects_more_than_64_utf8_bytes() -> None:
    with pytest.raises(CallbackDataError, match="64 UTF-8 bytes"):
        encode_interaction_callback(None, "i", "o" * 57)


def test_callback_data_enforces_multibyte_utf8_boundary() -> None:
    exact = encode_interaction_callback(None, "i", "你" * 18 + "ab")
    assert len(exact.encode("utf-8")) == 64

    with pytest.raises(CallbackDataError, match="64 UTF-8 bytes"):
        encode_interaction_callback(None, "i", "你" * 18 + "abc")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("x1|0|1|ia", "prefix"),
        ("h1|0|", "length header"),
        ("h1|x|1|ia", "decimal"),
        ("h1|0|x|ia", "decimal"),
        ("h1|-1|1|ia", "decimal"),
        ("h1|0|-1|ia", "decimal"),
        ("h1|5|1|abc", "bounds"),
        ("h1|0|0|option", "interaction_id"),
        ("h1|0|1|i", "option_id"),
        ("h1|0|1|i" + "o" * 57, "64 UTF-8 bytes"),
    ],
)
def test_malformed_callback_data_is_rejected(data: str, message: str) -> None:
    with pytest.raises(CallbackDataError, match=message):
        decode_interaction_callback(data)


@pytest.mark.parametrize(
    ("target", "interaction_id", "option_id", "message"),
    [
        (None, "", "option", "interaction_id"),
        (None, "interaction", "", "option_id"),
        ("", "interaction", "option", "callback_target"),
    ],
)
def test_encoder_rejects_empty_identifiers(
    target: str | None,
    interaction_id: str,
    option_id: str,
    message: str,
) -> None:
    with pytest.raises(CallbackDataError, match=message):
        encode_interaction_callback(target, interaction_id, option_id)
