"""Shared test-harness unit tests."""

import socket
from datetime import UTC, datetime
from uuid import UUID

import fakeredis.aioredis
import pytest
from fastapi import FastAPI

from ekumidayomi.core.settings import AppEnvironment, Settings
from ekumidayomi.tests.factories import DeterministicValues
from ekumidayomi.tests.helpers import override_dependencies


def test_settings_are_safe_and_do_not_load_dotenv(test_settings: Settings) -> None:
    assert test_settings.app_env is AppEnvironment.TEST
    assert test_settings.check_dependencies_on_startup is False
    assert test_settings.allowed_hosts == ["testserver"]
    assert test_settings.database_url != test_settings.test_database_url


def test_deterministic_values_are_stable(deterministic_values: DeterministicValues) -> None:
    assert deterministic_values.identifier == UUID("00000000-0000-4000-8000-000000000001")
    assert deterministic_values.now == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fake_redis_returns_decoded_values(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await fake_redis.set("test:key", "value")

    assert await fake_redis.get("test:key") == "value"


def test_dependency_overrides_restore_previous_mapping() -> None:
    app = FastAPI()

    def original_dependency() -> str:
        return "original"

    def original_override() -> str:
        return "original override"

    def temporary_dependency() -> str:
        return "temporary"

    def temporary_override() -> str:
        return "temporary override"

    app.dependency_overrides[original_dependency] = original_override

    with override_dependencies(app, {temporary_dependency: temporary_override}):
        assert app.dependency_overrides == {
            original_dependency: original_override,
            temporary_dependency: temporary_override,
        }

    assert app.dependency_overrides == {original_dependency: original_override}


def test_unit_network_access_is_blocked() -> None:
    with pytest.raises(AssertionError, match="network access is forbidden"):
        socket.create_connection(("example.com", 443))
