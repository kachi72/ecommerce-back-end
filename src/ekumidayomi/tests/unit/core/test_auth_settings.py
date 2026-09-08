"""One settings boundary for environment loading, validation and HTTP injection."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.application import create_app
from ekumidayomi.core.dependencies import get_auth_settings, get_request_settings
from ekumidayomi.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_auth_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in os.environ:
        if name.upper().startswith("EKUMIDAYOMI_AUTH"):
            monkeypatch.delenv(name)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_root_owns_auth_group_without_inheritance_or_shared_mutable_defaults() -> None:
    first = Settings(_env_file=None)
    second = Settings(_env_file=None)
    assert isinstance(first.auth, AuthSettings)
    assert first.auth.session_seconds == 604800
    assert not issubclass(AuthSettings, Settings)
    first.auth.allowed_origins.append("https://shop.example.com")
    first.auth.challenge_keys["v1"] = SecretStr("k" * 32)
    assert second.auth.allowed_origins == ["http://localhost:3000"]
    assert second.auth.challenge_keys == {}


def test_root_loads_nested_environment_but_auth_model_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "1200")
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__ALLOWED_ORIGINS", '["https://shop.example.com"]')
    root = Settings(_env_file=None)
    assert root.auth.session_seconds == 1200
    assert root.auth.allowed_origins == ["https://shop.example.com"]
    assert AuthSettings().session_seconds == 604800


def test_root_loads_secret_map_and_nested_override_precedes_group_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_AUTH", '{"session_seconds":1800,"cache_seconds":30}')
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "1200")
    secret = "k" * 32
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__CHALLENGE_KEYS", '{"v1":"' + secret + '"}')
    root = Settings(_env_file=None)
    assert root.auth.session_seconds == 1200
    assert root.auth.cache_seconds == 30
    assert root.auth.challenge_keys["v1"].get_secret_value() == secret
    assert secret not in repr(root)
    assert secret not in root.model_dump_json()


def test_root_dotenv_can_be_disabled_without_an_independent_auth_reader(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("EKUMIDAYOMI_AUTH__SESSION_SECONDS=900\n", encoding="utf-8")
    assert Settings(_env_file=dotenv).auth.session_seconds == 900
    assert Settings(_env_file=None).auth.session_seconds == 604800


def test_explicit_root_auth_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "1200")
    config = AuthSettings(session_seconds=900)
    root = Settings(_env_file=None, auth=config)
    assert root.auth is config
    assert root.auth.session_seconds == 900


@pytest.mark.parametrize(
    "values",
    [
        {"session_seconds": 299},
        {"session_seconds": 2592001},
        {"cache_seconds": 0},
        {"challenge_seconds": 901},
        {"challenge_attempts": 11},
        {"resend_seconds": 29},
        {"recent_auth_seconds": 901},
        {"session_second": 600},
        {"challenge_keys": {"v2": "k" * 32}},
        {"challenge_keys": {"v1": "short"}},
        {"allowed_origins": ["*"]},
        {"allowed_origins": ["https://shop.example.com/"]},
    ],
)
def test_root_validates_auth_values(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, auth=values)
    assert caught.value.errors()[0]["loc"][0] == "auth"


def test_invalid_auth_environment_fails_during_application_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "0")
    with pytest.raises(ValidationError):
        create_app()


def test_one_cache_owns_root_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "1200")
    first = get_settings()
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "900")
    assert get_settings() is first
    assert get_settings().auth is first.auth
    assert first.auth.session_seconds == 1200
    get_settings.cache_clear()
    assert get_settings().auth.session_seconds == 900


@pytest.mark.parametrize("override", [False, True])
async def test_http_dependency_uses_app_root_or_explicit_root_override(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    override: bool,
) -> None:
    # A separate environment reader would return 1200 rather than the injected value.
    monkeypatch.setenv("EKUMIDAYOMI_AUTH__SESSION_SECONDS", "1200")
    app = create_app(test_settings)
    assert app.state.settings is test_settings
    expected = test_settings
    if override:
        expected = Settings(_env_file=None, auth=AuthSettings(session_seconds=900))
        app.dependency_overrides[get_request_settings] = lambda: expected

    @app.get("/settings-probe")
    async def probe(config: Annotated[AuthSettings, Depends(get_auth_settings)]) -> dict[str, int]:
        assert config is expected.auth
        return {"session_seconds": config.session_seconds}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/settings-probe")
    assert response.status_code == 200
    assert response.json() == {"session_seconds": expected.auth.session_seconds}
