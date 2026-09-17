from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from telegram_bot.config import Settings
from telegram_bot.console_routes import WEB_DIRECTORY, sanitize_endpoint_for_display
from telegram_bot.main import create_app


def make_client(settings: Settings | None = None) -> tuple[TestClient, object]:
    app = create_app(settings=settings or Settings(), enable_lifespan=False)
    return TestClient(app), app


def test_console_index_and_static_assets_are_available() -> None:
    client, _ = make_client()
    with client:
        index = client.get("/console")
        script = client.get("/console/assets/app.js")
        styles = client.get("/console/assets/styles.css")

    assert index.status_code == 200
    assert "Ruyi Telegram Bot Console" in index.text
    assert "Human Interaction Builder" in index.text
    assert 'id="theme-toggle"' in index.text
    assert 'id="message-validation"' in index.text
    for page in ("overview", "send-message", "interaction", "routing", "about"):
        assert f'data-page-panel="{page}"' in index.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]


def test_sanitize_endpoint_removes_every_credential_channel() -> None:
    endpoint = (
        "https://user:pass@example.com:8443/callback/path/SECRET"
        "?token=ABC#debug"
    )

    assert sanitize_endpoint_for_display(endpoint) == "https://example.com:8443"


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://example.com:443/callback", "https://example.com"),
        ("http://example.com:80/callback", "http://example.com"),
        ("http://example.com:8080/callback", "http://example.com:8080"),
        ("https://[2001:db8::1]:8443/callback", "https://[2001:db8::1]:8443"),
        ("https://example.com:not-a-port/callback", "https://example.com"),
    ],
)
def test_sanitize_endpoint_preserves_safe_location(endpoint: str, expected: str) -> None:
    assert sanitize_endpoint_for_display(endpoint) == expected


def test_console_status_exposes_only_safe_configuration_summary() -> None:
    settings = Settings(
        telegram_token="123456:SUPERSECRET",
        telegram_chat_id=-100123456,
        http_proxy="http://proxy-user:proxy-pass@proxy.local:8080",
        callback_forward_url=(
            "https://fallback-user:fallback-pass@fallback.local/legacy/FALLBACKPATH"
            "?token=FALLBACKSECRET#debug"
        ),
        callback_targets={
            "test-workflow": (
                "https://user:pass@test.local/callback/path/SECRET"
                "?token=ABC#debug"
            ),
            "package-pr-workflow": "http://package.local:8080/result/PACKAGEPATH",
        },
    )
    client, _ = make_client(settings)

    with client:
        response = client.get("/api/v1/console/status")

    assert response.status_code == 200
    assert response.json() == {
        "service": {"status": "ok", "version": "0.1.0"},
        "telegram": {
            "token_configured": True,
            "default_chat_configured": True,
            "proxy_configured": True,
            "client_initialized": False,
        },
        "callback": {
            "targets": [
                {
                    "name": "package-pr-workflow",
                    "endpoint_display": "http://package.local:8080",
                },
                {
                    "name": "test-workflow",
                    "endpoint_display": "https://test.local",
                },
            ],
            "legacy_fallback_configured": True,
            "legacy_endpoint_display": "https://fallback.local",
        },
        "runtime": {"polling": "unavailable"},
    }
    serialized = response.text
    for secret in (
        "123456:SUPERSECRET",
        "-100123456",
        "proxy-user",
        "proxy-pass",
        "user",
        "pass",
        "callback/path/SECRET",
        "ABC",
        "fallback-user",
        "fallback-pass",
        "legacy/FALLBACKPATH",
        "FALLBACKSECRET",
        "debug",
        "result/PACKAGEPATH",
    ):
        assert secret not in serialized


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        (SimpleNamespace(done=lambda: False), "running"),
        (SimpleNamespace(done=lambda: True), "stopped"),
        (None, "unavailable"),
    ],
)
def test_console_status_reports_polling_runtime(task, expected: str) -> None:
    client, app = make_client()
    if task is not None:
        app.state.polling_task = task

    with client:
        response = client.get("/api/v1/console/status")

    assert response.status_code == 200
    assert response.json()["runtime"]["polling"] == expected


def test_console_status_reports_initialized_client_without_exposing_it() -> None:
    client, app = make_client(Settings(telegram_token="secret"))
    app.state.telegram_client_initialized = True

    with client:
        response = client.get("/api/v1/console/status")

    assert response.json()["telegram"]["client_initialized"] is True
    assert "secret" not in response.text


def test_console_package_contains_required_static_assets() -> None:
    assert WEB_DIRECTORY.is_dir()
    for asset in ("index.html", "app.js", "styles.css"):
        assert (WEB_DIRECTORY / asset).is_file()
