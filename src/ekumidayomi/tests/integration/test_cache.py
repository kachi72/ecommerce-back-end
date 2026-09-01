"""Redis-backed integration tests for the cache contract."""

from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from ekumidayomi.cache.client import CacheClient
from ekumidayomi.cache.keys import CacheKey
from ekumidayomi.core.redis import (
    check_redis_connection,
    close_redis_client,
    create_redis_client,
)
from ekumidayomi.core.settings import Settings


async def test_real_redis_round_trip_ttl_and_invalidation(
    test_settings: Settings,
) -> None:
    redis = create_redis_client(test_settings)
    cache_key = CacheKey(
        environment="test",
        owner="cache-contract",
        version=1,
        scope="probe",
        identifier=uuid4().hex,
    )
    cache = CacheClient[dict[str, str]](redis, fail_open=False)

    try:
        try:
            await check_redis_connection(redis)
        except (OSError, RedisError):
            pytest.fail(
                "Integration Redis is unavailable; start it with "
                "`just containers-up-deps` and verify the Redis URL.",
                pytrace=False,
            )
        assert await cache.set(cache_key, {"name": "dress"}, ttl_seconds=30)
        assert await cache.get(cache_key) == {"name": "dress"}
        assert 0 < await redis.ttl(cache_key.render()) <= 30
        assert await cache.delete(cache_key)
        assert await cache.get(cache_key) is None
    finally:
        await redis.delete(cache_key.render(), cache_key.lock_key())
        await close_redis_client(redis)
