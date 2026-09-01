"""Unit tests for namespaced, versioned Redis caching."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ekumidayomi.cache.client import CacheClient, CacheUnavailableError
from ekumidayomi.cache.codec import CacheDecodeError, JsonCacheCodec
from ekumidayomi.cache.keys import CacheKey


def key(
    *,
    environment: str = "test",
    identifier: str = "123",
) -> CacheKey:
    return CacheKey(environment, "catalogue", 1, "product", identifier)


def test_key_is_owned_versioned_and_cluster_compatible() -> None:
    cache_key = key()

    assert cache_key.render() == "ekumidayomi:{test:catalogue:product:123}:v1"
    assert cache_key.lock_key() == "ekumidayomi:{test:catalogue:product:123}:v1:lock"
    assert (
        cache_key.render().split("{")[1].split("}")[0]
        == cache_key.lock_key().split("{")[1].split("}")[0]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "bad:environment"),
        ("owner", "bad owner"),
        ("scope", "{product}"),
        ("identifier", "x" * 65),
    ],
)
def test_key_rejects_unsafe_segments(field: str, value: str) -> None:
    values = {
        "environment": "test",
        "owner": "catalogue",
        "version": 1,
        "scope": "product",
        "identifier": "123",
    }
    values[field] = value

    with pytest.raises(ValueError, match=f"unsafe cache key segment: {field}"):
        CacheKey(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("version", [True, "1", 0, 1000])
def test_key_requires_a_bounded_integer_version(version: object) -> None:
    with pytest.raises(ValueError, match="version must be an integer"):
        CacheKey("test", "catalogue", version, "product", "123")  # type: ignore[arg-type]


def test_codec_round_trips_decoded_strings_and_raw_bytes() -> None:
    codec = JsonCacheCodec()
    encoded = codec.encode({"name": "Àdìrẹ"})

    assert codec.decode(encoded) == {"name": "Àdìrẹ"}
    assert codec.decode(encoded.decode("utf-8")) == {"name": "Àdìrẹ"}


@pytest.mark.parametrize(
    "encoded",
    [
        b"not-json",
        b'{"schema_version":2,"value":{}}',
        b'{"schema_version":1}',
        b'{"schema_version":1,"value":null}',
    ],
)
def test_codec_rejects_corruption_and_unsupported_envelopes(encoded: bytes) -> None:
    with pytest.raises(CacheDecodeError):
        JsonCacheCodec().decode(encoded)


@pytest.mark.parametrize("value", [None, float("nan"), {"unsupported": object()}])
def test_codec_rejects_values_that_are_not_cache_safe(value: object) -> None:
    with pytest.raises(ValueError):
        JsonCacheCodec().encode(value)


def test_codec_enforces_encoded_byte_limit() -> None:
    codec = JsonCacheCodec(max_bytes=50)

    with pytest.raises(ValueError, match="byte limit"):
        codec.encode({"value": "x" * 100})
    with pytest.raises(CacheDecodeError, match="byte limit"):
        codec.decode(b"x" * 51)


async def test_set_get_delete_and_invalidate_require_owned_ttls(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[dict[str, str]](cast(Redis, fake_redis))
    first = key(identifier="one")
    second = key(identifier="two")

    assert await client.set(first, {"name": "dress"}, ttl_seconds=10)
    assert await client.set(second, {"name": "skirt"}, ttl_seconds=10)
    assert await client.get(first) == {"name": "dress"}
    assert 0 < await fake_redis.ttl(first.render()) <= 10
    assert await client.invalidate(first, second) == 2
    assert await client.get(first) is None
    assert not await client.delete(first)


@pytest.mark.parametrize("ttl", [True, 0, 86_401])
async def test_set_rejects_invalid_ttls(
    fake_redis: fakeredis.aioredis.FakeRedis,
    ttl: object,
) -> None:
    with pytest.raises(TypeError if ttl is True else ValueError):
        await CacheClient[object](cast(Redis, fake_redis)).set(
            key(),
            {},
            ttl_seconds=ttl,  # type: ignore[arg-type]
        )


async def test_expiry_and_environment_isolation(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[dict[str, str]](cast(Redis, fake_redis))
    test_key = key(environment="test")
    production_key = key(environment="production")

    await client.set(test_key, {"source": "test"}, ttl_seconds=1)
    await client.set(production_key, {"source": "production"}, ttl_seconds=10)
    await asyncio.sleep(1.05)

    assert await client.get(test_key) is None
    assert await client.get(production_key) == {"source": "production"}


async def test_corruption_becomes_a_miss_and_is_deleted(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[object](cast(Redis, fake_redis))
    await fake_redis.set(key().render(), "broken")

    assert await client.get(key()) is None
    assert await fake_redis.exists(key().render()) == 0


async def test_single_flight_loads_once_for_concurrent_callers(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[dict[str, str]](cast(Redis, fake_redis))
    loader = AsyncMock(return_value={"name": "dress"})

    first, second = await asyncio.gather(
        client.get_or_load(key(), loader, ttl_seconds=10),
        client.get_or_load(key(), loader, ttl_seconds=10),
    )

    assert first == second == {"name": "dress"}
    loader.assert_awaited_once()


async def test_unlock_cannot_delete_another_callers_lease(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[object](cast(Redis, fake_redis))
    await fake_redis.set(key().lock_key(), "new-owner", px=5_000)

    assert not await client._release_lock(key().lock_key(), "old-owner")
    assert await fake_redis.get(key().lock_key()) == "new-owner"


async def test_expired_lock_allows_a_new_loader(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[dict[str, str]](cast(Redis, fake_redis))
    await fake_redis.set(key().lock_key(), "stale", px=1)
    await asyncio.sleep(0.01)
    loader = AsyncMock(return_value={"name": "dress"})

    assert await client.get_or_load(key(), loader, ttl_seconds=10) == {"name": "dress"}
    loader.assert_awaited_once()


async def test_wait_timeout_is_bounded_before_fallback_load(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[dict[str, str]](cast(Redis, fake_redis))
    await fake_redis.set(key().lock_key(), "other-owner", px=5_000)
    loader = AsyncMock(return_value={"name": "dress"})

    assert await client.get_or_load(key(), loader, ttl_seconds=10, wait_ms=0) == {"name": "dress"}
    loader.assert_awaited_once()


async def test_fail_open_outage_loads_authoritative_data_without_caching() -> None:
    redis = MagicMock(spec=Redis)
    redis.get = AsyncMock(side_effect=RedisError("private endpoint"))
    loader = AsyncMock(return_value={"name": "dress"})

    result = await CacheClient[dict[str, str]](redis).get_or_load(
        key(),
        loader,
        ttl_seconds=10,
    )

    assert result == {"name": "dress"}
    loader.assert_awaited_once()


async def test_fail_closed_outage_raises_a_safe_cache_error() -> None:
    redis = MagicMock(spec=Redis)
    redis.get = AsyncMock(side_effect=RedisError("redis://:secret@private-cache"))

    with pytest.raises(CacheUnavailableError, match="cache backend is unavailable") as caught:
        await CacheClient[object](redis, fail_open=False).get(key())
    assert "private-cache" not in str(caught.value)


async def test_fail_open_write_returns_false() -> None:
    redis = MagicMock(spec=Redis)
    redis.set = AsyncMock(side_effect=RedisError("unavailable"))

    assert not await CacheClient[object](redis).set(key(), {}, ttl_seconds=10)


async def test_invalidation_is_bounded(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = CacheClient[object](cast(Redis, fake_redis))
    keys = tuple(key(identifier=f"item-{index}") for index in range(101))

    with pytest.raises(ValueError, match="cannot invalidate more than 100"):
        await client.invalidate(*keys)
