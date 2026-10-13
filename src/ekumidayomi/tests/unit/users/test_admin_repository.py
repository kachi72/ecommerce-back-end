"""Behavioral coverage for bounded administrator user queries."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.auth.sessions import Actor
from ekumidayomi.core.types import PageRequest
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users import admin_repository
from ekumidayomi.users.errors import PermissionDeniedError
from ekumidayomi.users.model import Role, User


def _actor(role: Role = Role.ADMIN) -> Actor:
    return Actor(
        user_id=UUID("00000000-0000-4000-8000-000000000001"),
        session_id=UUID("00000000-0000-4000-8000-000000000002"),
        role=role,
        authenticated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _uow() -> Mock:
    uow = Mock(spec=UnitOfWork)
    uow.session = AsyncMock(spec=AsyncSession)
    return uow


@pytest.mark.asyncio
async def test_list_users_applies_filters_and_stable_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    authorize = AsyncMock()
    monkeypatch.setattr(admin_repository, "authorize", authorize)
    user = User(
        id=UUID("00000000-0000-4000-8000-000000000010"),
        email="owner@example.com",
        role=Role.ADMIN.value,
        is_active=True,
    )
    scalar_result = Mock()
    scalar_result.all.return_value = [user]
    uow.session.scalar.return_value = 1
    uow.session.scalars.return_value = scalar_result

    result = await admin_repository.list_users(
        cast(UnitOfWork, uow),
        _actor(),
        page=PageRequest(page=2, page_size=10),
        role=Role.ADMIN,
        is_active=True,
        email="  OWNER@EXAMPLE.COM ",
    )

    assert result.items == (user,)
    assert (result.total_items, result.page, result.page_size) == (1, 2, 10)
    authorize.assert_awaited_once()
    statement = uow.session.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "users.role = 'admin'" in sql
    assert "users.is_active = true" in sql
    assert "users.email = 'owner@example.com'" in sql
    assert "ORDER BY users.created_at DESC, users.id DESC" in sql
    assert "LIMIT 10 OFFSET 10" in sql


@pytest.mark.asyncio
async def test_list_users_stops_before_query_when_customer_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    authorize = AsyncMock(side_effect=PermissionDeniedError())
    monkeypatch.setattr(admin_repository, "authorize", authorize)

    with pytest.raises(PermissionDeniedError):
        await admin_repository.list_users(
            cast(UnitOfWork, uow),
            _actor(Role.CUSTOMER),
            page=PageRequest(),
        )

    uow.session.scalar.assert_not_awaited()
    uow.session.scalars.assert_not_awaited()
