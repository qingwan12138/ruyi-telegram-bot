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
    action: str | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("button text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "Button":
        if self.type == "url":
            if not self.url:
                raise ValueError("url button requires url")
            if self.action is not None:
                raise ValueError("url button must not include action")
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("url button only supports http:// or https:// URLs")
        else:
            if not self.action or not self.action.strip():
                raise ValueError("action button requires action")
            if self.url is not None:
                raise ValueError("action button must not include url")
            self.action = self.action.strip()
            if len(self.action.encode("utf-8")) > 64:
                raise ValueError("action must be at most 64 UTF-8 bytes")
        return self


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4096)
    chat_id: int | None = None
    buttons: list[Button] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


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
