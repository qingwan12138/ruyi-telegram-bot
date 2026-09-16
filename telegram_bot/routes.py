"""FastAPI routes exposed by the service."""

from fastapi import APIRouter, HTTPException, Request

from . import __version__
from .callback_data import CallbackDataError, encode_interaction_callback
from .config import MissingCallbackRouteError, UnknownCallbackTargetError
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
    action_buttons = [button for button in payload.buttons if button.type == "action"]
    if action_buttons:
        try:
            request.app.state.settings.resolve_callback_url(payload.callback_target)
            if payload.interaction_id is not None:
                for button in action_buttons:
                    if button.option_id is not None:
                        encode_interaction_callback(
                            payload.callback_target,
                            payload.interaction_id,
                            button.option_id,
                        )
        except UnknownCallbackTargetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except MissingCallbackRouteError as exc:
            raise HTTPException(
                status_code=422,
                detail="action buttons require a callback delivery route",
            ) from exc
        except CallbackDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = await client.send_message(
            payload.text,
            chat_id=payload.chat_id,
            buttons=payload.buttons,
            interaction_id=payload.interaction_id,
            callback_target=payload.callback_target,
        )
    except MissingChatIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TelegramSendError as exc:
        raise HTTPException(status_code=503, detail="Telegram notification failed") from exc

    return MessageResponse(success=True, chat_id=result.chat_id, message_id=result.message_id)
