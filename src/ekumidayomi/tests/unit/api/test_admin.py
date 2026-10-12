"""Behavioral tests for administration HTTP adapters."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.api.v1 import admin
from ekumidayomi.audit import service as audit_service
from ekumidayomi.auth.sessions import Actor
from ekumidayomi.core.types import Page
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import PermissionDeniedError
from ekumidayomi.users.model import Role


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
async def test_audit_listing_authorizes_and_returns_a_bounded_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    authorize = AsyncMock()
    query_records = AsyncMock(return_value=Page(items=(), total_items=0, page=2, page_size=25))
    monkeypatch.setattr(admin, "authorize", authorize)
    monkeypatch.setattr(audit_service, "query_records", query_records)
    response = Response()

    result = await admin.audits(
        actor=_actor(),
        uow=cast(UnitOfWork, uow),
        response=response,
        page=2,
        page_size=25,
        action="identity.access_changed",
        actor_kind=None,
        actor_id=None,
        target_type="user",
        target_id=None,
        outcome=None,
        occurred_from=None,
        occurred_to=None,
    )

    authorize.assert_awaited_once()
    query_records.assert_awaited_once()
    query_call = query_records.await_args
    assert query_call is not None
    filters = query_call.kwargs["filters"]
    assert filters.action == "identity.access_changed"
    assert filters.target_type == "user"
    assert result.pagination.page == 2
    assert result.pagination.page_size == 25
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_customer_cannot_query_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = _uow()
    authorize = AsyncMock(side_effect=PermissionDeniedError())
    query_records = AsyncMock()
    monkeypatch.setattr(admin, "authorize", authorize)
    monkeypatch.setattr(audit_service, "query_records", query_records)

    with pytest.raises(PermissionDeniedError):
        await admin.audits(
            actor=_actor(Role.CUSTOMER),
            uow=cast(UnitOfWork, uow),
            response=Response(),
            page=1,
            page_size=20,
            action=None,
            actor_kind=None,
            actor_id=None,
            target_type=None,
            target_id=None,
            outcome=None,
            occurred_from=None,
            occurred_to=None,
        )

    query_records.assert_not_awaited()
