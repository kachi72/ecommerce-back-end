"""Shared test fixtures and marker classification."""

import asyncio
import socket
from collections.abc import AsyncIterator, Iterator
from typing import NoReturn

import fakeredis.aioredis
import pytest

from ekumidayomi.core.settings import AppEnvironment, Settings
from ekumidayomi.tests.factories import DeterministicValues, build_deterministic_values


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify tests by their directory when no explicit marker is present."""
    for item in items:
        if "integration" in item.path.parts:
            if item.get_closest_marker("integration") is None:
                item.add_marker(pytest.mark.integration)
        elif "unit" in item.path.parts and item.get_closest_marker("unit") is None:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(autouse=True)
def block_unit_network(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Forbid accidental socket access outside explicit integration tests."""
    if request.node.get_closest_marker("integration") is not None:
        yield
        return

    def fail_network(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("network access is forbidden in unit tests")

    async def fail_async_network(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("network access is forbidden in unit tests")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(asyncio, "open_connection", fail_async_network)
    yield


@pytest.fixture
def test_settings() -> Settings:
    """Return safe test settings without reading a developer .env file."""
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        debug=False,
        check_dependencies_on_startup=False,
        allowed_hosts=["testserver"],
        cors_origins=[],
        secret_key="test-only-secret",
    )


@pytest.fixture
def deterministic_values() -> DeterministicValues:
    """Return stable identifiers and timestamps for repeatable tests."""
    return build_deterministic_values()


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Provide an empty decoded Redis-compatible client per test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
