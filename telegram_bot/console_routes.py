"""Read-only Web Console routes and secret-safe runtime summaries."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from . import __version__

WEB_DIRECTORY = Path(__file__).with_name("web")

console_router = APIRouter()


def sanitize_endpoint_for_display(endpoint: str) -> str:
    """Return a routable-looking endpoint with every credential channel removed."""
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname or ""
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        display_host = f"{display_host}:{port}"
    return urlunsplit((parsed.scheme, display_host, parsed.path, "", ""))


def _polling_status(request: Request) -> str:
    task = getattr(request.app.state, "polling_task", None)
    if task is None:
        return "unavailable"
    return "stopped" if task.done() else "running"


@console_router.get("/console", include_in_schema=False)
async def console_index() -> FileResponse:
    return FileResponse(WEB_DIRECTORY / "index.html")


@console_router.get("/api/v1/console/status")
async def console_status(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    targets = [
        {
            "name": name,
            "endpoint_display": sanitize_endpoint_for_display(endpoint),
        }
        for name, endpoint in sorted(settings.callback_targets.items())
    ]
    fallback = settings.callback_forward_url
    return {
        "service": {"status": "ok", "version": __version__},
        "telegram": {
            "token_configured": bool(settings.telegram_token),
            "default_chat_configured": settings.telegram_chat_id is not None,
            "proxy_configured": settings.telegram_proxy is not None,
            "client_initialized": bool(
                getattr(request.app.state, "telegram_client_initialized", False)
            ),
        },
        "callback": {
            "targets": targets,
            "legacy_fallback_configured": fallback is not None,
            "legacy_endpoint_display": (
                sanitize_endpoint_for_display(fallback) if fallback is not None else None
            ),
        },
        "runtime": {"polling": _polling_status(request)},
    }
