"""Session security, cache fallback and transaction-ownership contracts."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.auth import sessions as session_module
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.sessions import SessionService, digest
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import AuthenticationRequiredError
from ekumidayomi.users.model import Role, User

NOW = datetime(2026, 9, 8, tzinfo=UTC)
SECRET = "s" * 43


@pytest.fixture
def uow() -> Mock:
    value = Mock(spec=UnitOfWork)
    value.session = AsyncMock(spec=AsyncSession)
    return value


@pytest.fixture
def redis() -> AsyncMock:
    value = AsyncMock(spec=Redis)
    # Redis command mixins return awaitables without declaring async methods,
    # so spec alone would create synchronous mocks for these commands.
    value.get = AsyncMock(return_value=None)
    value.set = AsyncMock(return_value=True)
    value.delete = AsyncMock(return_value=1)
    return value


@pytest.fixture
def service(redis: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> SessionService:
    monkeypatch.setattr(session_module, "utc_now", lambda: NOW)
    return SessionService(cast(Redis, redis), namespace="test", settings=AuthSettings())


def identity() -> tuple[AuthSession, User]:
    user = User(id=uuid4(), email="session@example.com", role="customer", is_active=True)
    user.email_verified_at = NOW
    row = AuthSession(
        id=uuid4(),
        user_id=user.id,
        secret_hash=digest(SECRET),
        created_at=NOW,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )
    return row, user


def result(value: tuple[AuthSession, User] | None) -> Mock:
    return Mock(first=Mock(return_value=value))


def test_session_hash_and_bounds() -> None:
    assert digest("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert len(digest(SECRET)) == 64
    assert digest(SECRET) != SECRET
    assert AuthSettings().session_seconds == 604800
    assert AuthSettings().cache_seconds == 60


async def test_issue_stores_digest_and_absolute_expiry_without_committing(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = Mock(return_value=SECRET)
    monkeypatch.setattr("ekumidayomi.auth.sessions.secrets.token_urlsafe", token)
    _, user = identity()
    assert await service.issue(cast(UnitOfWork, uow), user) == SECRET
    token.assert_called_once_with(32)
    row = uow.session.add.call_args.args[0]
    assert row.user_id == user.id
    assert row.secret_hash == digest(SECRET)
    assert row.created_at == row.authenticated_at == NOW
    assert row.expires_at == NOW + timedelta(days=7)
    uow.session.flush.assert_awaited_once_with()
    uow.commit.assert_not_called()
    uow.session.commit.assert_not_awaited()
    redis.set.assert_not_awaited()


@pytest.mark.parametrize(("active", "verified"), [(False, True), (True, False), (False, False)])
async def test_issue_rejects_ineligible_users(
    uow: Mock,
    service: SessionService,
    active: bool,
    verified: bool,
) -> None:
    _, user = identity()
    user.is_active = active
    user.email_verified_at = NOW if verified else None
    with pytest.raises(AuthenticationRequiredError):
        await service.issue(cast(UnitOfWork, uow), user)
    uow.session.add.assert_not_called()
    uow.session.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "secret", [None, "", "s" * 42, "s" * 44, "!" * 43, "é" * 43, " " + "s" * 42]
)
async def test_malformed_secrets_fail_before_database_or_cache_access(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
    secret: str | None,
) -> None:
    with pytest.raises(AuthenticationRequiredError) as caught:
        await service.resolve(cast(UnitOfWork, uow), secret)
    assert caught.value.code == "authentication_required"
    redis.get.assert_not_awaited()
    uow.session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "hint_kind", ["missing", "string", "bytes", "invalid", "invalid-bytes", "stale", "outage"]
)
async def test_resolve_always_checks_durable_state_and_repairs_cache(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
    hint_kind: str,
) -> None:
    row, user = identity()
    calls = 1
    uow.session.execute.return_value = result((row, user))
    if hint_kind == "string":
        redis.get.return_value = str(row.id)
    elif hint_kind == "bytes":
        redis.get.return_value = str(row.id).encode()
    elif hint_kind == "invalid":
        redis.get.return_value = "not-a-uuid"
    elif hint_kind == "invalid-bytes":
        redis.get.return_value = b"\xff"
    elif hint_kind == "stale":
        redis.get.return_value = str(uuid4())
        uow.session.execute.side_effect = [result(None), result((row, user))]
        calls = 2
    elif hint_kind == "outage":
        redis.get.side_effect = RedisError("unavailable")
    actor = await service.resolve(cast(UnitOfWork, uow), SECRET)
    assert (actor.user_id, actor.session_id, actor.role, actor.authenticated_at) == (
        user.id,
        row.id,
        Role.CUSTOMER,
        NOW,
    )
    assert uow.session.execute.await_count == calls
    for call in uow.session.execute.call_args_list:
        compiled = call.args[0].compile(dialect=sa.engine.make_url("postgresql://").get_dialect()())
        sql = str(compiled)
        for predicate in (
            "auth_sessions.secret_hash =",
            "auth_sessions.revoked_at IS NULL",
            "auth_sessions.expires_at >",
            "users.is_active IS true",
            "users.email_verified_at IS NOT NULL",
        ):
            assert predicate in sql
        assert digest(SECRET) in compiled.params.values()
        assert SECRET not in compiled.params.values()
    redis.set.assert_awaited_once_with(service.key(digest(SECRET)), str(row.id), ex=60)
    assert SECRET not in service.key(digest(SECRET))
    assert row.authenticated_at == NOW
    uow.session.commit.assert_not_awaited()


async def test_cache_write_failure_does_not_deny_a_valid_durable_session(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
) -> None:
    row, user = identity()
    uow.session.execute.return_value = result((row, user))
    redis.set.side_effect = RedisError("unavailable")
    assert (await service.resolve(cast(UnitOfWork, uow), SECRET)).user_id == user.id


@pytest.mark.parametrize("warm", [False, True])
async def test_missing_durable_session_is_not_authorized_by_a_cache_hit(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
    warm: bool,
) -> None:
    redis.get.return_value = str(uuid4()) if warm else None
    uow.session.execute.return_value = result(None)
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(cast(UnitOfWork, uow), SECRET)
    redis.set.assert_not_awaited()


async def test_unknown_persisted_role_fails_closed(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
) -> None:
    row, user = identity()
    user.role = "owner"
    uow.session.execute.return_value = result((row, user))
    with pytest.raises(AuthenticationRequiredError):
        await service.resolve(cast(UnitOfWork, uow), SECRET)
    redis.set.assert_not_awaited()


@pytest.mark.parametrize("target_one", [False, True])
@pytest.mark.parametrize("cache_case", ["normal", "empty", "outage"])
async def test_revoke_scopes_update_and_defers_invalidation_until_after_commit(
    uow: Mock,
    redis: AsyncMock,
    service: SessionService,
    target_one: bool,
    cache_case: str,
) -> None:
    user_id, session_id = uuid4(), uuid4()
    hashes = () if cache_case == "empty" else (digest(SECRET), digest("other"))
    uow.session.scalars.return_value = Mock(all=Mock(return_value=hashes))
    if cache_case == "outage":
        redis.delete.side_effect = RedisError("unavailable")
    await service.revoke(
        cast(UnitOfWork, uow), user_id=user_id, session_id=session_id if target_one else None
    )
    statement = uow.session.scalars.call_args.args[0]
    compiled = statement.compile(dialect=sa.engine.make_url("postgresql://").get_dialect()())
    assert "auth_sessions.user_id =" in str(compiled)
    assert "auth_sessions.revoked_at IS NULL" in str(compiled)
    assert ("auth_sessions.id =" in str(compiled)) is target_one
    assert "RETURNING auth_sessions.secret_hash" in str(compiled)
    assert user_id in compiled.params.values()
    assert NOW in compiled.params.values()
    uow.commit.assert_not_called()
    uow.session.commit.assert_not_awaited()
    redis.delete.assert_not_awaited()
    uow.after_commit.assert_called_once()
    await uow.after_commit.call_args.args[0]()
    if hashes:
        redis.delete.assert_awaited_once_with(*(service.key(value) for value in hashes))
    else:
        redis.delete.assert_not_awaited()
