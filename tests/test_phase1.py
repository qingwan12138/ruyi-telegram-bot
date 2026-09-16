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


def test_callback_targets_are_loaded_and_resolved() -> None:
    settings = Settings.load(
        {
            "CALLBACK_TARGETS_JSON": (
                '{"target-a":"http://a.local/callback",'
                '"target-b":"https://b.local/callback"}'
            )
        }
    )

    assert settings.callback_targets == {
        "target-a": "http://a.local/callback",
        "target-b": "https://b.local/callback",
    }
    assert settings.resolve_callback_url("target-a") == "http://a.local/callback"
    assert settings.resolve_callback_url("target-b") == "https://b.local/callback"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not-json", "valid JSON object"),
        ("[]", "JSON object"),
        ('{" ":"http://a.local/callback"}', "non-blank"),
        ('{"target":42}', "string URL"),
        ('{"target":"ftp://a.local/callback"}', "http:// or https://"),
    ],
)
def test_invalid_callback_target_registry_fails_during_load(
    raw: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.load({"CALLBACK_TARGETS_JSON": raw})


def test_callback_forward_url_is_used_for_missing_target() -> None:
    settings = Settings(callback_forward_url="http://fallback.local/callback")

    assert settings.resolve_callback_url(None) == "http://fallback.local/callback"


def test_unknown_explicit_target_never_uses_fallback() -> None:
    settings = Settings(
        callback_forward_url="http://fallback.local/callback",
        callback_targets={"known": "http://known.local/callback"},
    )

    with pytest.raises(ValueError, match="unknown callback target"):
        settings.resolve_callback_url("missing")


def test_missing_target_and_fallback_has_no_delivery_route() -> None:
    with pytest.raises(ValueError, match="no callback delivery route"):
        Settings().resolve_callback_url(None)
