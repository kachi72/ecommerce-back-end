"""Settings validation tests."""

import pytest
from pydantic import ValidationError

from ekumidayomi.core.settings import (
    AppEnvironment,
    LogFormat,
    LogLevel,
    Settings,
    get_settings,
)


def test_development_defaults_use_the_development_database() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env is AppEnvironment.DEVELOPMENT
    assert settings.active_database_url == settings.database_url


def test_test_database_must_differ_from_development_database() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            app_env=AppEnvironment.TEST,
            database_url="postgresql+asyncpg://user:pass@db/app",
            test_database_url="postgresql+asyncpg://user:pass@db/app",
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"debug": True}, "debug"),
        ({"secure_cookies": False}, "secure_cookies"),
        ({"allowed_hosts": ["*"]}, "wildcard allowed_hosts"),
        ({"cors_origins": ["*"]}, "wildcard cors_origins"),
        ({"allowed_hosts": []}, "allowed_hosts must not be empty"),
        ({"secret_key": "change-me"}, "non-placeholder secret_key"),
    ],
)
def test_production_rejects_unsafe_values(
    override: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "app_env": AppEnvironment.PRODUCTION,
        "allowed_hosts": ["api.example.com"],
        "secure_cookies": True,
        "secret_key": "a-production-secret-provided-by-the-secret-store",
    }
    values.update(override)

    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(values)


def test_active_database_url_uses_test_database_in_test_environment() -> None:
    settings = Settings(app_env=AppEnvironment.TEST)

    assert settings.active_database_url == settings.test_database_url


def test_valid_production_settings_are_accepted() -> None:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.PRODUCTION,
        allowed_hosts=["api.example.com"],
        cors_origins=["https://shop.example.com"],
        secure_cookies=True,
        secret_key="a-production-secret-provided-by-the-secret-store",
    )

    assert settings.app_env is AppEnvironment.PRODUCTION
    assert settings.active_database_url == settings.database_url


def test_secret_value_is_masked_in_settings_representation() -> None:
    secret = "a-value-that-must-not-appear"
    settings = Settings(_env_file=None, secret_key=secret)

    assert secret not in repr(settings)
    assert "**********" in repr(settings)


def test_prefixed_json_environment_lists_are_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_ALLOWED_HOSTS", '["api.example.com"]')
    monkeypatch.setenv("EKUMIDAYOMI_CORS_ORIGINS", '["https://shop.example.com"]')

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == ["api.example.com"]
    assert settings.cors_origins == ["https://shop.example.com"]


def test_get_settings_returns_one_cached_instance() -> None:
    get_settings.cache_clear()
    try:
        first = get_settings()
        second = get_settings()

        assert first is second
    finally:
        get_settings.cache_clear()


def test_observability_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.service_name == "ekumidayomi-api"
    assert settings.log_level is LogLevel.INFO
    assert settings.log_format is LogFormat.JSON
    assert settings.trust_incoming_request_ids is False
    assert settings.tracing_endpoint is None


def test_prefixed_observability_settings_are_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("EKUMIDAYOMI_LOG_FORMAT", "console")
    monkeypatch.setenv("EKUMIDAYOMI_TRUST_INCOMING_REQUEST_IDS", "true")
    monkeypatch.setenv("EKUMIDAYOMI_TRACING_ENDPOINT", "https://telemetry.example.com")

    settings = Settings(_env_file=None)

    assert settings.log_level is LogLevel.ERROR
    assert settings.log_format is LogFormat.CONSOLE
    assert settings.trust_incoming_request_ids is True
    assert settings.tracing_endpoint is not None
