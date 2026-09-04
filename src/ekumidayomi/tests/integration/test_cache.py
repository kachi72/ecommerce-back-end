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


async def test_real_redis_ttl_and_environment_isolation(
    test_settings: Settings,
) -> None:
    redis = create_redis_client(test_settings)
    identifier = uuid4().hex
    test_key = CacheKey("test", "platform", 1, "probe", identifier)
    production_key = CacheKey("production", "platform", 1, "probe", identifier)
    cache = CacheClient[dict[str, bool]](redis, fail_open=False)

    try:
        try:
            await check_redis_connection(redis)
        except (OSError, RedisError):
            pytest.fail(
                "Integration Redis is unavailable; start it with "
                "`just containers-up-deps` and verify the Redis URL.",
                pytrace=False,
            )

        assert await cache.set(test_key, {"ready": True}, ttl_seconds=5)
        assert await cache.get(test_key) == {"ready": True}
        assert await cache.get(production_key) is None
        assert 0 < await redis.ttl(test_key.render()) <= 5
        assert "{test:platform:probe:" in test_key.render()
        assert "{production:platform:probe:" in production_key.render()
    finally:
        await redis.delete(
            test_key.render(),
            test_key.lock_key(),
            production_key.render(),
            production_key.lock_key(),
        )
        await close_redis_client(redis)
