"""FastAPI routes exposed by the service."""

from fastapi import APIRouter, HTTPException, Request

from . import __version__
from .models import MessageRequest, MessageResponse
from .telegram_client import MissingChatIdError, TelegramSendError

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.post("/api/v1/messages", response_model=MessageResponse)
async def send_message(payload: MessageRequest, request: Request) -> MessageResponse:
    client = request.app.state.telegram_client
    try:
        result = await client.send_message(
            payload.text,
            chat_id=payload.chat_id,
            buttons=payload.buttons,
        )
    except MissingChatIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TelegramSendError as exc:
        raise HTTPException(status_code=503, detail="Telegram notification failed") from exc

    return MessageResponse(success=True, chat_id=result.chat_id, message_id=result.message_id)
