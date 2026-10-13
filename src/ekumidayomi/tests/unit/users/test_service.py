"""User application services own mutations and enforce address boundaries."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.auth.sessions import Actor
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users import service
from ekumidayomi.users.address import Address
from ekumidayomi.users.errors import AddressLimitReachedError, AddressNotFoundError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.schemas import AddressInput, ProfileInput


def actor() -> Actor:
    return Actor(
        user_id=uuid4(),
        session_id=uuid4(),
        role=Role.CUSTOMER,
        authenticated_at=datetime(2026, 10, 13, tzinfo=UTC),
    )


def uow_mock() -> Mock:
    uow = Mock(spec=UnitOfWork)
    uow.session = AsyncMock(spec=AsyncSession)
    uow.commit = AsyncMock()
    return uow


def address_input(*, is_default: bool = False) -> AddressInput:
    return AddressInput(
        kind="shipping",
        recipient="Customer",
        line1="1 Main Street",
        city="Lagos",
        region="Lagos",
        country_code="NG",
        is_default=is_default,
    )


async def test_update_profile_commits_authorized_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_mock()
    current = User(email="customer@example.com")
    authorize = AsyncMock(return_value=current)
    monkeypatch.setattr(service, "authorize", authorize)

    result = await service.update_profile(
        cast(UnitOfWork, uow),
        actor(),
        ProfileInput(display_name="Ẹkúmidáyọ̀mí", phone="+2348000000000"),
    )

    assert result is current
    assert (current.display_name, current.phone) == ("Ẹkúmidáyọ̀mí", "+2348000000000")
    uow.commit.assert_awaited_once_with()


async def test_replace_address_updates_owned_row_without_creating_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_mock()
    current_actor = actor()
    row = Address(id=uuid4(), user_id=current_actor.user_id)
    monkeypatch.setattr(service, "authorize", AsyncMock())
    uow.session.scalar.return_value = row

    result = await service.save_address(
        cast(UnitOfWork, uow),
        current_actor,
        address_input(),
        address_id=row.id,
    )

    assert result is row
    assert row.recipient == "Customer"
    uow.session.add.assert_not_called()
    uow.commit.assert_awaited_once_with()


async def test_replace_missing_address_and_address_limit_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_mock()
    current_actor = actor()
    monkeypatch.setattr(service, "authorize", AsyncMock())
    uow.session.scalar.return_value = None

    with pytest.raises(AddressNotFoundError):
        await service.save_address(
            cast(UnitOfWork, uow),
            current_actor,
            address_input(),
            address_id=uuid4(),
        )

    uow.session.scalar.return_value = 20
    with pytest.raises(AddressLimitReachedError):
        await service.save_address(
            cast(UnitOfWork, uow),
            current_actor,
            address_input(),
        )
    uow.commit.assert_not_awaited()


async def test_delete_owned_address_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_mock()
    current_actor = actor()
    row = Address(id=uuid4(), user_id=current_actor.user_id)
    monkeypatch.setattr(service, "authorize", AsyncMock())
    uow.session.scalar.return_value = row

    await service.delete_address(cast(UnitOfWork, uow), current_actor, row.id)

    uow.session.delete.assert_awaited_once_with(row)
    uow.commit.assert_awaited_once_with()
