"""Atomic security limits; Redis failure is not permission to proceed."""

import hashlib
import hmac
import secrets
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ekumidayomi.users.errors import (
    IdentityRateLimitExceededError,
    IdentityUnavailableError,
)

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
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


async def enforce(
    redis: Redis,
    *,
    namespace: str,
    operation: str,
    identity: str,
    secret: str,
    limit: int,
    window_seconds: int,
) -> None:
    key = (
        f"ekumidayomi:{namespace}:auth:v1:limit:{operation}:{private_identifier(identity, secret)}"
    )
    try:
        retry = int(
            # Redis shares this command's annotation with its synchronous client.
            # This client is asynchronous and the Lua script returns an integer.
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
    except RedisError:
        raise IdentityUnavailableError() from None
    if retry > 0:
        raise IdentityRateLimitExceededError(retry_after=retry)
