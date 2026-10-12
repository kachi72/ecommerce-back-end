"""Atomic security limits; Redis failure is not permission to proceed."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ekumidayomi.core.rate_limits import (
    private_identifier,
    rate_limit_key,
    sliding_window_retry_after,
)
from ekumidayomi.users.errors import (
    IdentityRateLimitExceededError,
    IdentityUnavailableError,
)

__all__ = ["enforce", "private_identifier"]


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
    key = rate_limit_key(
        namespace=namespace, scope="auth", operation=operation, identity=identity, secret=secret
    )
    try:
        retry = await sliding_window_retry_after(
            redis, key=key, limit=limit, window_seconds=window_seconds
        )
    except RedisError:
        raise IdentityUnavailableError() from None
    if retry > 0:
        raise IdentityRateLimitExceededError(retry_after=retry)
