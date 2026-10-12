import asyncio
from uuid import uuid4

from redis.asyncio import Redis

from ekumidayomi.core.rate_limits import rate_limit_key, sliding_window_retry_after
from ekumidayomi.core.settings import Settings


async def test_profile_window_is_atomic_and_isolated(
    test_settings: Settings,
) -> None:
    namespace = f"test-{uuid4().hex}"
    secret = "profile-rate-limit-integration-secret"
    async with Redis.from_url(test_settings.redis_url, decode_responses=True) as redis:
        first_user_key = rate_limit_key(
            namespace=namespace,
            scope="users",
            operation="profile-update",
            identity="first-user",
            secret=secret,
        )

        async def attempt() -> bool:
            return (
                await sliding_window_retry_after(
                    redis,
                    key=first_user_key,
                    limit=5,
                    window_seconds=5,
                )
                == 0
            )

        assert sum(await asyncio.gather(*(attempt() for _ in range(15)))) == 5

        second_user_key = rate_limit_key(
            namespace=namespace,
            scope="users",
            operation="profile-update",
            identity="second-user",
            secret=secret,
        )
        address_key = rate_limit_key(
            namespace=namespace,
            scope="users",
            operation="address-create",
            identity="first-user",
            secret=secret,
        )
        assert (
            await sliding_window_retry_after(
                redis,
                key=second_user_key,
                limit=5,
                window_seconds=5,
            )
            == 0
        )
        assert (
            await sliding_window_retry_after(
                redis,
                key=address_key,
                limit=5,
                window_seconds=5,
            )
            == 0
        )


async def test_profile_window_admits_requests_after_expiry(
    test_settings: Settings,
) -> None:
    key = rate_limit_key(
        namespace=f"test-{uuid4().hex}",
        scope="users",
        operation="profile-update",
        identity="expiring-user",
        secret="profile-rate-limit-integration-secret",
    )
    async with Redis.from_url(test_settings.redis_url, decode_responses=True) as redis:
        assert (
            await sliding_window_retry_after(
                redis,
                key=key,
                limit=1,
                window_seconds=1,
            )
            == 0
        )
        assert (
            await sliding_window_retry_after(
                redis,
                key=key,
                limit=1,
                window_seconds=1,
            )
            >= 1
        )

        await asyncio.sleep(1.1)

        assert (
            await sliding_window_retry_after(
                redis,
                key=key,
                limit=1,
                window_seconds=1,
            )
            == 0
        )
