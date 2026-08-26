"""Redis lifecycle tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ekumidayomi.core import redis as redis_module
from ekumidayomi.core.redis import (
    check_redis_connection,
    close_redis_client,
    create_redis_client,
)
from ekumidayomi.core.settings import Settings


def test_create_redis_client_uses_decoding_and_bounded_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    redis_class = MagicMock()
    redis_class.from_url.return_value = client
    monkeypatch.setattr(redis_module, "Redis", redis_class)
    settings = Settings(
        _env_file=None,
        redis_url="redis://cache:6379/4",
        redis_connect_timeout_seconds=1.5,
        redis_operation_timeout_seconds=2.5,
    )

    result = create_redis_client(settings)

    assert result is client
    redis_class.from_url.assert_called_once_with(
        "redis://cache:6379/4",
        decode_responses=True,
        socket_connect_timeout=1.5,
        socket_timeout=2.5,
        health_check_interval=30,
    )


@pytest.mark.asyncio
async def test_check_redis_connection_pings_client() -> None:
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)

    await check_redis_connection(client)

    client.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_close_redis_client_closes_client() -> None:
    client = MagicMock()
    client.aclose = AsyncMock()

    await close_redis_client(client)

    client.aclose.assert_awaited_once_with()
