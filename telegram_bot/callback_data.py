"""Stateless encoding for versioned human-interaction callback data."""

from __future__ import annotations

from dataclasses import dataclass

CALLBACK_DATA_PREFIX = "h1|"
CALLBACK_DATA_MAX_BYTES = 64


class CallbackDataError(ValueError):
    """Raised when interaction callback data cannot be safely encoded or decoded."""


@dataclass(frozen=True, slots=True)
class InteractionCallbackData:
    callback_target: str | None
    interaction_id: str
    option_id: str


def _require_non_blank(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise CallbackDataError(f"{field_name} must not be empty")


def _validate_size(data: str) -> None:
    if len(data.encode("utf-8")) > CALLBACK_DATA_MAX_BYTES:
        raise CallbackDataError("callback_data must be at most 64 UTF-8 bytes")


def encode_interaction_callback(
    callback_target: str | None,
    interaction_id: str,
    option_id: str,
) -> str:
    """Encode routing identifiers using Unicode character-count prefixes."""
    if callback_target == "":
        raise CallbackDataError("callback_target must be None or non-empty")
    if callback_target is not None:
        _require_non_blank(callback_target, "callback_target")
    _require_non_blank(interaction_id, "interaction_id")
    _require_non_blank(option_id, "option_id")

    target = callback_target or ""
    data = (
        f"{CALLBACK_DATA_PREFIX}{len(target)}|{len(interaction_id)}|"
        f"{target}{interaction_id}{option_id}"
    )
    _validate_size(data)
    return data


def decode_interaction_callback(data: str) -> InteractionCallbackData:
    """Decode new-protocol callback data or raise a controlled validation error."""
    if not isinstance(data, str) or not data.startswith(CALLBACK_DATA_PREFIX):
        raise CallbackDataError("invalid interaction callback_data prefix")
    _validate_size(data)

    parts = data.split("|", 3)
    if len(parts) != 4:
        raise CallbackDataError("invalid callback_data length header")
    _, target_length_raw, interaction_length_raw, payload = parts
    if (
        not target_length_raw
        or not interaction_length_raw
        or any(character not in "0123456789" for character in target_length_raw)
        or any(character not in "0123456789" for character in interaction_length_raw)
    ):
        raise CallbackDataError("callback_data lengths must be decimal integers")

    target_length = int(target_length_raw)
    interaction_length = int(interaction_length_raw)
    if interaction_length == 0:
        raise CallbackDataError("interaction_id must not be empty")

    target_end = target_length
    interaction_end = target_end + interaction_length
    if target_end > len(payload) or interaction_end > len(payload):
        raise CallbackDataError("callback_data length is outside payload bounds")

    target = payload[:target_end]
    interaction_id = payload[target_end:interaction_end]
    option_id = payload[interaction_end:]
    if target_length and not target.strip():
        raise CallbackDataError("callback_target must not be empty")
    _require_non_blank(interaction_id, "interaction_id")
    _require_non_blank(option_id, "option_id")

    return InteractionCallbackData(
        callback_target=target or None,
        interaction_id=interaction_id,
        option_id=option_id,
    )
