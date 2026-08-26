"""Redis client construction and lifecycle helpers."""

from typing import cast

from redis.asyncio import Redis

from ekumidayomi.core.settings import Settings


def create_redis_client(settings: Settings) -> Redis:
    """Create a decoded async Redis client with bounded operations."""
    return cast(
        Redis,
        Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_operation_timeout_seconds,
            health_check_interval=30,
        ),
    )


async def check_redis_connection(client: Redis) -> None:
    """Raise when Redis does not answer PING."""
    await client.ping()


async def close_redis_client(client: Redis) -> None:
    """Close the Redis client and its connection pool."""
    await client.aclose()
