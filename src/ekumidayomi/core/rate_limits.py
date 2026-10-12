"""Provider-neutral Redis sliding-window rate-limit primitives."""

import hashlib
import hmac
import secrets
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

SLIDING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.max(1, math.ceil((tonumber(first[2]) + window - now) / 1000))
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""


def private_identifier(value: str, key: str) -> str:
    """Return a stable keyed identifier without exposing the source value."""

    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def rate_limit_key(
    *, namespace: str, scope: str, operation: str, identity: str, secret: str, version: str = "v1"
) -> str:
    """Build a namespaced key."""

    return (
        f"ekumidayomi:{namespace}:{scope}:{version}:limit:{operation}:"
        f"{private_identifier(identity, secret)}"
    )


async def sliding_window_retry_after(
    redis: Redis, *, key: str, limit: int, window_seconds: int
) -> int:
    """Admit one request or return the positive number of seconds until retry."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if (
        isinstance(window_seconds, bool)
        or not isinstance(window_seconds, int)
        or window_seconds < 1
    ):
        raise ValueError("window_seconds must be a positive integer")
    retry = int(
        await cast(
            Awaitable[int],
            redis.eval(
                SLIDING_WINDOW,
                1,
                key,
                str(window_seconds * 1000),
                str(limit),
                secrets.token_hex(16),
            ),
        )
    )
    if retry < 0:
        raise RuntimeError("rate limiter returned an invalid retry delay")
    return retry
