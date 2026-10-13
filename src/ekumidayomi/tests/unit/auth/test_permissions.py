"""Durable permission checks reject stale or ineligible identity state."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.auth import permissions
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.permissions import Permission
from ekumidayomi.auth.sessions import Actor
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    AuthenticationRequiredError,
    PermissionDeniedError,
    ReauthenticationRequiredError,
)
from ekumidayomi.users.model import Role, User

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def state() -> tuple[Actor, User, AuthSession]:
    user = User(
        id=uuid4(),
        email="customer@example.com",
        role=Role.CUSTOMER.value,
        is_active=True,
        email_verified_at=NOW,
    )
    session = AuthSession(
        id=uuid4(),
        user_id=user.id,
        secret_hash="a" * 64,
        created_at=NOW,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    actor = Actor(user.id, session.id, Role.CUSTOMER, NOW)
    return actor, user, session


def uow_mock() -> Mock:
    uow = Mock(spec=UnitOfWork)
    uow.session = AsyncMock(spec=AsyncSession)
    return uow


@pytest.mark.parametrize(
    "invalid_state",
    [
        "missing_user",
        "inactive",
        "unverified",
        "missing_session",
        "wrong_user",
        "revoked",
        "expired",
    ],
)
async def test_authorize_rejects_invalid_durable_state(
    monkeypatch: pytest.MonkeyPatch,
    invalid_state: str,
) -> None:
    actor, user, session = state()
    uow = uow_mock()
    found_user: User | None = user
    found_session: AuthSession | None = session
    if invalid_state == "missing_user":
        found_user = None
    elif invalid_state == "inactive":
        user.is_active = False
    elif invalid_state == "unverified":
        user.email_verified_at = None
    elif invalid_state == "missing_session":
        found_session = None
    elif invalid_state == "wrong_user":
        session.user_id = uuid4()
    elif invalid_state == "revoked":
        session.revoked_at = NOW
    else:
        session.expires_at = NOW
    monkeypatch.setattr(permissions, "find_user_by_id", AsyncMock(return_value=found_user))
    monkeypatch.setattr(permissions, "utc_now", lambda: NOW)
    uow.session.get.return_value = found_session

    with pytest.raises(AuthenticationRequiredError):
        await permissions.authorize(
            cast(UnitOfWork, uow),
            actor,
            Permission.PROFILE_WRITE,
        )


async def test_unknown_and_customer_roles_cannot_gain_admin_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, user, session = state()
    uow = uow_mock()
    monkeypatch.setattr(permissions, "find_user_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(permissions, "utc_now", lambda: NOW)
    uow.session.get.return_value = session

    with pytest.raises(PermissionDeniedError):
        await permissions.authorize(cast(UnitOfWork, uow), actor, Permission.USERS_READ)
    user.role = "owner"
    with pytest.raises(PermissionDeniedError):
        await permissions.authorize(cast(UnitOfWork, uow), actor, Permission.PROFILE_WRITE)


async def test_recent_authentication_and_lock_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, user, session = state()
    uow = uow_mock()
    finder = AsyncMock(return_value=user)
    monkeypatch.setattr(permissions, "find_user_by_id", finder)
    monkeypatch.setattr(permissions, "utc_now", lambda: NOW)
    uow.session.get.return_value = session

    assert (
        await permissions.authorize(
            cast(UnitOfWork, uow),
            actor,
            Permission.PROFILE_WRITE,
            recent_seconds=60,
            lock=True,
        )
        is user
    )
    finder.assert_awaited_with(uow.session, actor.user_id, lock=True)

    session.authenticated_at = NOW - timedelta(seconds=61)
    with pytest.raises(ReauthenticationRequiredError):
        await permissions.authorize(
            cast(UnitOfWork, uow),
            actor,
            Permission.PROFILE_WRITE,
            recent_seconds=60,
        )
