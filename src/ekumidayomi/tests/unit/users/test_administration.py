"""Behavioral coverage for administrator-owned identity mutations."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.audit.model import AuditRecord
from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users import administration
from ekumidayomi.users.errors import UserNotFoundError
from ekumidayomi.users.model import Role, User


def _actor() -> Actor:
    return Actor(
        user_id=UUID("00000000-0000-4000-8000-000000000001"),
        session_id=UUID("00000000-0000-4000-8000-000000000002"),
        role=Role.ADMIN,
        authenticated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _uow() -> Mock:
    uow = Mock(spec=UnitOfWork)
    uow.session = AsyncMock(spec=AsyncSession)
    uow.commit = AsyncMock()
    return uow


def _sessions() -> Mock:
    sessions = Mock()
    sessions.settings = AuthSettings()
    sessions.revoke = AsyncMock()
    return sessions


@pytest.mark.asyncio
async def test_change_access_revokes_sessions_audits_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    sessions = _sessions()
    target = User(
        id=UUID("00000000-0000-4000-8000-000000000010"),
        email="customer@example.com",
        role=Role.CUSTOMER.value,
        is_active=True,
        email_verified_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(administration, "lock_membership", AsyncMock())
    monkeypatch.setattr(administration, "authorize", AsyncMock())
    monkeypatch.setattr(administration, "find_user_by_id", AsyncMock(return_value=target))

    await administration.change_access(
        cast(UnitOfWork, uow),
        cast(SessionService, sessions),
        actor=_actor(),
        target_id=target.id,
        role=None,
        is_active=False,
        correlation_id="admin-access-test",
    )

    assert target.is_active is False
    sessions.revoke.assert_awaited_once_with(cast(UnitOfWork, uow), user_id=target.id)
    uow.commit.assert_awaited_once_with()
    audit = uow.session.add.call_args.args[0]
    assert isinstance(audit, AuditRecord)
    assert audit.action == "identity.access_changed"
    assert audit.target_id == target.id
    assert audit.metadata_ == {
        "old_role": Role.CUSTOMER.value,
        "new_role": Role.CUSTOMER.value,
        "old_active": True,
        "new_active": False,
    }


@pytest.mark.asyncio
async def test_change_access_unknown_user_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    sessions = _sessions()
    monkeypatch.setattr(administration, "lock_membership", AsyncMock())
    monkeypatch.setattr(administration, "authorize", AsyncMock())
    monkeypatch.setattr(administration, "find_user_by_id", AsyncMock(return_value=None))

    with pytest.raises(UserNotFoundError):
        await administration.change_access(
            cast(UnitOfWork, uow),
            cast(SessionService, sessions),
            actor=_actor(),
            target_id=UUID("00000000-0000-4000-8000-000000000099"),
            role=Role.ADMIN,
            is_active=None,
            correlation_id="admin-missing-test",
        )

    sessions.revoke.assert_not_awaited()
    uow.session.add.assert_not_called()
    uow.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_access_noop_does_not_commit_or_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    sessions = _sessions()
    target = User(
        id=UUID("00000000-0000-4000-8000-000000000010"),
        email="customer@example.com",
        role=Role.CUSTOMER.value,
        is_active=True,
    )
    monkeypatch.setattr(administration, "lock_membership", AsyncMock())
    monkeypatch.setattr(administration, "authorize", AsyncMock())
    monkeypatch.setattr(administration, "find_user_by_id", AsyncMock(return_value=target))

    await administration.change_access(
        cast(UnitOfWork, uow),
        cast(SessionService, sessions),
        actor=_actor(),
        target_id=target.id,
        role=Role.CUSTOMER,
        is_active=True,
        correlation_id="admin-noop-test",
    )

    sessions.revoke.assert_not_awaited()
    uow.session.add.assert_not_called()
    uow.commit.assert_not_awaited()
