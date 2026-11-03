"""OIDC attempts are browser-bound, short-lived, and consumed once."""

import time
from typing import cast

import fakeredis.aioredis
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from ekumidayomi.auth.oidc.attempts import AttemptStore, state_hash
from ekumidayomi.auth.oidc.contracts import Attempt
from ekumidayomi.auth.oidc.providers import challenge
from ekumidayomi.auth.oidc.settings import ProviderName
from ekumidayomi.users.errors import ExternalLoginFailedError, IdentityUnavailableError


def attempt(provider: ProviderName = ProviderName.GOOGLE) -> Attempt:
    return Attempt(
        provider=provider,
        intent="login",
        browser_hash=state_hash("browser-binding-" + "x" * 32),
        nonce="nonce",
        verifier="v" * 64,
        redirect_uri="https://api.example.com/callback",
        started_at=int(time.time()),
    )


@pytest.mark.parametrize("provider", list(ProviderName))
async def test_attempt_is_browser_bound_and_one_time(
    fake_redis: fakeredis.aioredis.FakeRedis,
    provider: ProviderName,
) -> None:
    store = AttemptStore(fake_redis, namespace="test", ttl=600)
    browser = "browser-binding-" + "x" * 32
    value = attempt(provider)

    state = await store.create(value)

    assert await store.consume(state, browser, provider) == value
    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, browser, provider)


async def test_mismatched_browser_or_provider_consumes_attempt(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    store = AttemptStore(fake_redis, namespace="test", ttl=600)
    browser = "browser-binding-" + "x" * 32
    state = await store.create(attempt())

    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, "wrong-browser-" + "y" * 32, ProviderName.GOOGLE)
    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, browser, ProviderName.GOOGLE)

    state = await store.create(attempt())
    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, browser, ProviderName.YAHOO)
    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, browser, ProviderName.GOOGLE)


async def test_malformed_attempt_is_rejected_without_replay(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    store = AttemptStore(fake_redis, namespace="test", ttl=600)
    state = "s" * 32
    await fake_redis.set(store.key(state), "not-json", ex=600)

    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, "b" * 32, ProviderName.GOOGLE)
    assert await fake_redis.get(store.key(state)) is None


@pytest.mark.parametrize("state,browser", [("short", "b" * 32), ("s" * 32, "short")])
async def test_attempt_rejects_unbounded_identifiers_before_redis(
    fake_redis: fakeredis.aioredis.FakeRedis,
    state: str,
    browser: str,
) -> None:
    store = AttemptStore(fake_redis, namespace="test", ttl=600)

    with pytest.raises(ExternalLoginFailedError):
        await store.consume(state, browser, ProviderName.GOOGLE)


def test_rfc7636_pkce_vector() -> None:
    assert challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


class BrokenRedis:
    async def set(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisConnectionError("unavailable")

    async def getdel(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisConnectionError("unavailable")


async def test_redis_outage_fails_closed() -> None:
    store = AttemptStore(cast(Redis, BrokenRedis()), namespace="test", ttl=600)

    with pytest.raises(IdentityUnavailableError):
        await store.create(attempt())
    with pytest.raises(IdentityUnavailableError):
        await store.consume("s" * 32, "b" * 32, ProviderName.GOOGLE)
