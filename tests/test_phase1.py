from fastapi.testclient import TestClient
import pytest

from telegram_bot.config import Settings
from telegram_bot.main import create_app


def test_health() -> None:
    app = create_app(settings=Settings(), enable_lifespan=False)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version() -> None:
    app = create_app(settings=Settings(), enable_lifespan=False)
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "0.1.0"}


def test_settings_defaults() -> None:
    settings = Settings.load({})
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 9878
    assert settings.telegram_chat_id is None


def test_settings_require_token_on_startup() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_TOKEN is required"):
        Settings().validate_startup()


def test_https_proxy_is_preferred_for_telegram() -> None:
    settings = Settings.load(
        {
            "HTTP_PROXY": "http://http-proxy.local:8080",
            "HTTPS_PROXY": "http://https-proxy.local:8080",
        }
    )
    assert settings.telegram_proxy == "http://https-proxy.local:8080"


def test_http_proxy_is_used_as_fallback() -> None:
    settings = Settings.load({"HTTP_PROXY": "http://proxy.local:8080"})
    assert settings.telegram_proxy == "http://proxy.local:8080"
