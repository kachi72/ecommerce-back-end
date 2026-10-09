import asyncio
from uuid import uuid4

from redis.asyncio import Redis

from ekumidayomi.auth.rate_limits import enforce
from ekumidayomi.core.settings import Settings
from ekumidayomi.users.errors import IdentityRateLimitExceededError


async def test_window_admits_exact_limit_under_concurrency(test_settings: Settings) -> None:
    # The namespace is isolated; keys expire after five seconds. No FLUSHDB.
    namespace = f"test-{uuid4().hex}"
    async with Redis.from_url(test_settings.redis_url, decode_responses=True) as redis:

        async def attempt() -> bool:
            try:
                await enforce(
                    redis,
                    namespace=namespace,
                    operation="login",
                    identity="test-actor",
                    secret="test-key",
                    limit=5,
                    window_seconds=5,
                )
                return True
            except IdentityRateLimitExceededError:
                return False

        assert sum(await asyncio.gather(*(attempt() for _ in range(15)))) == 5
