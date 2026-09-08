"""Durable authorization remains authoritative across cache and transaction states."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError

from ekumidayomi.auth import sessions as session_module
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.sessions import SessionService, digest
from ekumidayomi.core.redis import close_redis_client, create_redis_client
from ekumidayomi.core.settings import Settings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import AuthenticationRequiredError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import create_customer

NOW = datetime(2026, 9, 8, tzinfo=UTC)


@pytest.fixture
def service(
    fake_redis: fakeredis.aioredis.FakeRedis,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> SessionService:
    monkeypatch.setattr(session_module, "utc_now", lambda: NOW)
    return SessionService(fake_redis, namespace="test", settings=test_settings.auth)


async def verified_user(uow: UnitOfWork, email: str = "session@example.com") -> User:
    user = await create_customer(uow.session, email=email)
    user.email_verified_at = NOW
    await uow.session.flush()
    return user


async def test_issue_persists_only_digest_and_resolves_without_sliding_expiry(
    identity_uow: UnitOfWork,
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await verified_user(identity_uow)
    secret = await service.issue(identity_uow, user)
    assert len(secret) == 43
    await identity_uow.commit()
    identity_uow.session.expunge_all()
    row = (await identity_uow.session.scalars(sa.select(AuthSession))).one()
    assert row.secret_hash == digest(secret)
    assert row.created_at == row.authenticated_at == NOW
    assert row.expires_at == NOW + timedelta(days=7)
    assert row.revoked_at is None
    assert row.created_at.utcoffset() == timedelta(0)
    monkeypatch.setattr(session_module, "utc_now", lambda: NOW + timedelta(days=6))
    actor = await service.resolve(identity_uow, secret)
    assert actor.authenticated_at == NOW
    await identity_uow.session.refresh(row)
    assert row.authenticated_at == NOW
    assert row.expires_at == NOW + timedelta(days=7)
    monkeypatch.setattr(session_module, "utc_now", lambda: NOW + timedelta(days=7))
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, secret)


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize(
    "state", ["revoked", "expired", "inactive", "unverified", "deleted", "unknown-role"]
)
async def test_invalid_durable_state_cannot_be_overridden_by_cache(
    identity_uow: UnitOfWork,
    service: SessionService,
    fake_redis: fakeredis.aioredis.FakeRedis,
    state: str,
    warm: bool,
) -> None:
    user = await verified_user(identity_uow)
    user_id = user.id
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    actor = await service.resolve(identity_uow, secret)
    if state == "revoked":
        await service.revoke(identity_uow, user_id=user_id)
    elif state == "expired":
        await identity_uow.session.execute(sa.update(AuthSession).values(expires_at=NOW))
    elif state == "inactive":
        user.is_active = False
    elif state == "unverified":
        user.email_verified_at = None
    elif state == "deleted":
        await identity_uow.session.execute(sa.delete(User).where(User.id == user_id))
    else:
        user.role = "owner"
    await identity_uow.commit()
    key = service.key(digest(secret))
    if warm:
        # Recreate stale data even after successful revocation invalidation.
        await fake_redis.set(key, str(actor.session_id), ex=60)
    else:
        await fake_redis.delete(key)
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, secret)
    if state == "deleted":
        assert await identity_uow.session.get(AuthSession, actor.session_id) is None


async def test_warm_cache_cannot_resurrect_revoked_session(
    identity_uow: UnitOfWork,
    service: SessionService,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user = await verified_user(identity_uow)
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    actor = await service.resolve(identity_uow, secret)
    await service.revoke(identity_uow, user_id=user.id)
    await identity_uow.commit()
    await fake_redis.set(service.key(digest(secret)), str(actor.session_id), ex=60)
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, secret)


async def test_forged_hint_cannot_switch_identity_and_is_repaired(
    identity_uow: UnitOfWork,
    service: SessionService,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    first = await verified_user(identity_uow, "first@example.com")
    second = await verified_user(identity_uow, "second@example.com")
    first_secret = await service.issue(identity_uow, first)
    second_secret = await service.issue(identity_uow, second)
    await identity_uow.commit()
    other = await service.resolve(identity_uow, second_secret)
    key = service.key(digest(first_secret))
    await fake_redis.set(key, str(other.session_id), ex=60)
    actor = await service.resolve(identity_uow, first_secret)
    assert actor.user_id == first.id
    assert await fake_redis.get(key) == str(actor.session_id)
    unknown = "x" * 43
    await fake_redis.set(service.key(digest(unknown)), str(other.session_id), ex=60)
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, unknown)


async def test_warm_cache_returns_current_user_role(
    identity_uow: UnitOfWork,
    service: SessionService,
) -> None:
    user = await verified_user(identity_uow)
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    assert (await service.resolve(identity_uow, secret)).role is Role.CUSTOMER
    user.role = Role.ADMIN.value
    await identity_uow.commit()
    identity_uow.session.expunge_all()
    assert (await service.resolve(identity_uow, secret)).role is Role.ADMIN


async def test_redis_outage_falls_back_to_postgres_without_authorizing_unknown_secret(
    identity_uow: UnitOfWork,
    service: SessionService,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await verified_user(identity_uow)
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    monkeypatch.setattr(fake_redis, "get", AsyncMock(side_effect=RedisError("offline")))
    monkeypatch.setattr(fake_redis, "set", AsyncMock(side_effect=RedisError("offline")))
    assert (await service.resolve(identity_uow, secret)).user_id == user.id
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, "z" * 43)


async def test_issuance_rolls_back_with_caller_transaction(
    identity_uow: UnitOfWork,
    service: SessionService,
) -> None:
    user = await verified_user(identity_uow)
    await identity_uow.commit()
    secret = await service.issue(identity_uow, user)
    await identity_uow.rollback()
    assert (
        await identity_uow.session.scalar(sa.select(sa.func.count()).select_from(AuthSession)) == 0
    )
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, secret)


@pytest.mark.parametrize("commit", [False, True])
async def test_cache_invalidation_occurs_only_after_successful_commit(
    identity_uow: UnitOfWork,
    service: SessionService,
    fake_redis: fakeredis.aioredis.FakeRedis,
    commit: bool,
) -> None:
    user = await verified_user(identity_uow)
    user_id = user.id
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    actor = await service.resolve(identity_uow, secret)
    key = service.key(digest(secret))
    await service.revoke(identity_uow, user_id=user_id, session_id=actor.session_id)
    assert await fake_redis.get(key) is not None
    if commit:
        await identity_uow.commit()
        assert await fake_redis.get(key) is None
        with pytest.raises(AuthenticationRequiredError):
            await service.resolve(identity_uow, secret)
    else:
        await identity_uow.rollback()
        # A later commit must not execute the rolled-back invalidation callback.
        await identity_uow.commit()
        assert await fake_redis.get(key) is not None
        assert (await service.resolve(identity_uow, secret)).session_id == actor.session_id


async def test_revocation_is_safe_when_post_commit_cache_deletion_fails(
    identity_uow: UnitOfWork,
    service: SessionService,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await verified_user(identity_uow)
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    await service.resolve(identity_uow, secret)
    monkeypatch.setattr(fake_redis, "delete", AsyncMock(side_effect=RedisError("offline")))
    await service.revoke(identity_uow, user_id=user.id)
    await identity_uow.commit()
    assert await fake_redis.get(service.key(digest(secret))) is not None
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, secret)


async def test_revocation_is_user_scoped_and_can_target_one_or_all_sessions(
    identity_uow: UnitOfWork,
    service: SessionService,
) -> None:
    user = await verified_user(identity_uow)
    other = await verified_user(identity_uow, "other@example.com")
    first, second = await service.issue(identity_uow, user), await service.issue(identity_uow, user)
    unrelated = await service.issue(identity_uow, other)
    await identity_uow.commit()
    actor = await service.resolve(identity_uow, first)
    await service.revoke(identity_uow, user_id=other.id, session_id=actor.session_id)
    await identity_uow.commit()
    assert (await service.resolve(identity_uow, first)).user_id == user.id
    await service.revoke(identity_uow, user_id=user.id, session_id=actor.session_id)
    await identity_uow.commit()
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, first)
    assert (await service.resolve(identity_uow, second)).user_id == user.id
    await service.revoke(identity_uow, user_id=user.id)
    await identity_uow.commit()
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(identity_uow, second)
    await service.revoke(identity_uow, user_id=user.id)
    await identity_uow.commit()
    assert (await service.resolve(identity_uow, unrelated)).user_id == other.id


@pytest.mark.parametrize("violation", ["duplicate-hash", "missing-user"])
async def test_database_enforces_digest_uniqueness_and_user_reference(
    identity_uow: UnitOfWork,
    service: SessionService,
    violation: str,
) -> None:
    user = await verified_user(identity_uow)
    secret = await service.issue(identity_uow, user)
    await identity_uow.commit()
    duplicate = AuthSession(
        user_id=user.id if violation == "duplicate-hash" else uuid4(),
        secret_hash=digest(secret) if violation == "duplicate-hash" else digest("different"),
        created_at=NOW,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )
    with pytest.raises(IntegrityError):
        async with identity_uow.session.begin_nested():
            identity_uow.session.add(duplicate)
            await identity_uow.session.flush()


async def test_real_redis_round_trip_ttl_and_revocation(
    identity_uow: UnitOfWork,
    test_settings: Settings,
) -> None:
    redis = create_redis_client(test_settings)
    service = SessionService(redis, namespace=f"test-{uuid4().hex}", settings=test_settings.auth)
    key: str | None = None
    try:
        try:
            await redis.ping()
        except (OSError, RedisError):
            pytest.fail(
                "Integration Redis is unavailable; verify the configured test service.",
                pytrace=False,
            )
        user = await verified_user(identity_uow)
        secret = await service.issue(identity_uow, user)
        await identity_uow.commit()
        actor = await service.resolve(identity_uow, secret)
        key = service.key(digest(secret))
        cached = await redis.get(key)
        assert cached == str(actor.session_id)
        assert secret not in key
        assert secret != cached
        assert 0 < await redis.ttl(key) <= test_settings.auth.cache_seconds
        await service.revoke(identity_uow, user_id=user.id)
        await identity_uow.commit()
        assert await redis.get(key) is None
        with pytest.raises(AuthenticationRequiredError):
            await service.resolve(identity_uow, secret)
    finally:
        try:
            if key is not None:
                await redis.delete(key)
        finally:
            await close_redis_client(redis)
