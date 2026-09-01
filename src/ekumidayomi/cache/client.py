"""Typed Redis cache operations with bounded fail-open and single-flight behavior."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError, WatchError

from ekumidayomi.cache.codec import CacheDecodeError, JsonCacheCodec
from ekumidayomi.cache.keys import CacheKey

T = TypeVar("T")
_MAX_TTL_SECONDS = 86_400
_MAX_INVALIDATION_KEYS = 100
_MAX_LEASE_MS = 30_000
_MAX_WAIT_MS = 10_000
_POLL_INTERVAL_SECONDS = 0.025


class CacheUnavailableError(RuntimeError):
    """Redis is unavailable for an operation that may not fail open."""


class CacheClient[T]:
    """Operate a non-authoritative cache without owning durable state."""

    def __init__(
        self,
        redis: Redis,
        *,
        codec: JsonCacheCodec | None = None,
        fail_open: bool = True,
        operation_timeout_seconds: float = 2.0,
    ) -> None:
        if not isinstance(fail_open, bool):
            raise TypeError("fail_open must be a boolean")
        if isinstance(operation_timeout_seconds, bool) or not isinstance(
            operation_timeout_seconds, int | float
        ):
            raise TypeError("operation_timeout_seconds must be a number")
        if not 0 < operation_timeout_seconds <= 30:
            raise ValueError("operation_timeout_seconds must be between 0 and 30")
        self._redis = redis
        self._codec = codec or JsonCacheCodec()
        self._fail_open = fail_open
        self._operation_timeout_seconds = float(operation_timeout_seconds)

    async def get(self, key: CacheKey) -> T | None:
        """Return a decoded value, treating corruption and allowed outages as misses."""

        _, value = await self._read(key)
        return value

    async def set(self, key: CacheKey, value: T, *, ttl_seconds: int) -> bool:
        """Store one value with a mandatory bounded TTL."""

        _validate_ttl(ttl_seconds)
        encoded = self._codec.encode(value)
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                await self._redis.set(key.render(), encoded, ex=ttl_seconds)
        except (RedisError, TimeoutError) as error:
            return self._handle_write_failure(error)
        return True

    async def delete(self, key: CacheKey) -> bool:
        """Delete one explicitly owned cache key."""

        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                deleted = await self._redis.delete(key.render())
        except (RedisError, TimeoutError) as error:
            return self._handle_write_failure(error)
        return bool(deleted)

    async def invalidate(self, *keys: CacheKey) -> int:
        """Invalidate a bounded set without cross-slot multi-key commands."""

        if len(keys) > _MAX_INVALIDATION_KEYS:
            raise ValueError(f"cannot invalidate more than {_MAX_INVALIDATION_KEYS} keys")
        deleted = 0
        for key in keys:
            deleted += int(await self.delete(key))
        return deleted

    async def get_or_load(
        self,
        key: CacheKey,
        loader: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: int,
        lease_ms: int = 5_000,
        wait_ms: int = 2_000,
    ) -> T:
        """Load once per live lease, then let bounded waiters read the cache."""

        if not callable(loader):
            raise TypeError("loader must be callable")
        _validate_ttl(ttl_seconds)
        _validate_milliseconds("lease_ms", lease_ms, minimum=100, maximum=_MAX_LEASE_MS)
        _validate_milliseconds("wait_ms", wait_ms, minimum=0, maximum=_MAX_WAIT_MS)

        available, cached = await self._read(key)
        if cached is not None:
            return cached
        if not available:
            return await loader()

        token = secrets.token_urlsafe(24)
        acquired = await self._acquire_lock(key.lock_key(), token, lease_ms)
        if acquired is None:
            return await loader()
        if acquired:
            try:
                value = await loader()
                await self.set(key, value, ttl_seconds=ttl_seconds)
                return value
            finally:
                await self._release_lock(key.lock_key(), token)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_ms / 1000
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, remaining))
            available, cached = await self._read(key)
            if cached is not None:
                return cached
            if not available:
                return await loader()

        value = await loader()
        await self.set(key, value, ttl_seconds=ttl_seconds)
        return value

    async def _read(self, key: CacheKey) -> tuple[bool, T | None]:
        rendered = key.render()
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                encoded = await self._redis.get(rendered)
        except (RedisError, TimeoutError) as error:
            if self._fail_open:
                return False, None
            raise CacheUnavailableError("cache backend is unavailable") from error
        if encoded is None:
            return True, None
        try:
            return True, cast(T, self._codec.decode(encoded))
        except CacheDecodeError:
            await self._delete_corrupt(rendered)
            return True, None

    async def _delete_corrupt(self, rendered: str) -> None:
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                await self._redis.delete(rendered)
        except (RedisError, TimeoutError):
            return

    async def _acquire_lock(
        self,
        lock_key: str,
        token: str,
        lease_ms: int,
    ) -> bool | None:
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                acquired = await self._redis.set(
                    lock_key,
                    token,
                    nx=True,
                    px=lease_ms,
                )
        except (RedisError, TimeoutError) as error:
            if self._fail_open:
                return None
            raise CacheUnavailableError("cache backend is unavailable") from error
        return bool(acquired)

    async def _release_lock(self, lock_key: str, token: str) -> bool:
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(lock_key)
                    current = await pipeline.get(lock_key)
                    if _decode_token(current) != token:
                        await pipeline.unwatch()  # type: ignore[no-untyped-call]
                        return False
                    pipeline.multi()  # type: ignore[no-untyped-call]
                    pipeline.delete(lock_key)
                    results = await pipeline.execute()
        except WatchError:
            return False
        except (RedisError, TimeoutError) as error:
            if self._fail_open:
                return False
            raise CacheUnavailableError("cache backend is unavailable") from error
        return bool(results[0])

    def _handle_write_failure(self, error: BaseException) -> bool:
        if self._fail_open:
            return False
        raise CacheUnavailableError("cache backend is unavailable") from error


def _decode_token(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def _validate_ttl(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("ttl_seconds must be an integer")
    if not 1 <= value <= _MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {_MAX_TTL_SECONDS}")


def _validate_milliseconds(
    name: str,
    value: object,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
