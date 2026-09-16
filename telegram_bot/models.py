"""Pydantic request/response models for the public HTTP contract."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Button(BaseModel):
    """A Telegram inline button.

    URL buttons navigate to an HTTP(S) URL. Action buttons emit short callback_data.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["url", "action"]
    text: str = Field(min_length=1)
    url: str | None = None
    option_id: str | None = None
    action: str | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("button text must not be blank")
        return value

    @field_validator("option_id", "action")
    @classmethod
    def strip_identifier(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_target(self) -> "Button":
        if self.type == "url":
            if not self.url:
                raise ValueError("url button requires url")
            if self.action is not None:
                raise ValueError("url button must not include action")
            if self.option_id is not None:
                raise ValueError("url button must not include option_id")
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("url button only supports http:// or https:// URLs")
        else:
            if self.url is not None:
                raise ValueError("action button must not include url")
            if self.option_id is None and self.action is None:
                raise ValueError("action button requires option_id or action")
            if self.option_id is not None and self.action is not None:
                raise ValueError("action button must not include both option_id and action")
            if self.action is not None:
                if self.action.startswith("h1|"):
                    raise ValueError("legacy action must not use reserved prefix h1|")
                if len(self.action.encode("utf-8")) > 64:
                    raise ValueError("action must be at most 64 UTF-8 bytes")
        return self


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4096)
    chat_id: int | None = None
    interaction_id: str | None = None
    callback_target: str | None = None
    buttons: list[Button] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value

    @field_validator("interaction_id", "callback_target")
    @classmethod
    def strip_interaction_field(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_interaction_mode(self) -> "MessageRequest":
        new_actions = [
            button
            for button in self.buttons
            if button.type == "action" and button.option_id is not None
        ]
        legacy_actions = [
            button
            for button in self.buttons
            if button.type == "action" and button.action is not None
        ]
        if new_actions and legacy_actions:
            raise ValueError("request must not mix new and legacy action buttons")
        if new_actions:
            if self.interaction_id is None:
                raise ValueError("new action buttons require interaction_id")
        elif self.interaction_id is not None or self.callback_target is not None:
            raise ValueError("interaction fields require new action buttons")
        return self


class MessageResponse(BaseModel):
    success: bool
    chat_id: int
    message_id: int


class CallbackEvent(BaseModel):
    event: Literal["telegram.action"] = "telegram.action"
    action: str
    chat_id: int
    message_id: int
    user_id: int
    username: str | None = None
    callback_query_id: str


class InteractionResult(BaseModel):
    event: Literal["telegram.interaction.selected"] = "telegram.interaction.selected"
    interaction_id: str
    option_id: str
    chat_id: int
    message_id: int
    user_id: int
    username: str | None = None
    callback_query_id: str
