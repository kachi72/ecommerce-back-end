"""Repository query and transaction-ownership contracts without PostgreSQL."""

from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.users.errors import InvalidEmailError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import by_email, by_id, create_customer


async def test_create_customer_flushes_but_does_not_own_the_transaction() -> None:
    session = AsyncMock(spec=AsyncSession)
    user = await create_customer(cast(AsyncSession, session), email="customer@EXAMPLE.com")
    assert user.email == "customer@example.com"
    assert user.role == Role.CUSTOMER.value
    assert user.is_active is True
    assert user.email_verified_at is None
    session.add.assert_called_once_with(user)
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_invalid_email_is_rejected_before_persistence() -> None:
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(InvalidEmailError):
        await create_customer(cast(AsyncSession, session), email="invalid")
    with pytest.raises(InvalidEmailError):
        await by_email(cast(AsyncSession, session), "invalid")
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    session.scalar.assert_not_awaited()


async def test_email_lookup_uses_the_same_normalization_policy() -> None:
    session = AsyncMock(spec=AsyncSession)
    user = User(email="customer@example.com")
    session.scalar.return_value = user
    assert await by_email(cast(AsyncSession, session), " Customer@EXAMPLE.com ") is user
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=sa.engine.make_url("postgresql://").get_dialect()())
    assert list(compiled.params.values()) == ["customer@example.com"]
    assert "users.email =" in str(compiled)


@pytest.mark.parametrize("lock", [False, True])
async def test_id_lookup_refreshes_existing_state_and_only_locks_when_requested(lock: bool) -> None:
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    user = User(id=user_id, email="customer@example.com")
    session.scalar.return_value = user
    assert await by_id(cast(AsyncSession, session), user_id, lock=lock) is user
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=sa.engine.make_url("postgresql://").get_dialect()())
    assert list(compiled.params.values()) == [user_id]
    assert "users.id =" in str(compiled)
    assert ("FOR UPDATE" in str(compiled)) is lock
    assert statement.get_execution_options()["populate_existing"] is True
    session.commit.assert_not_awaited()


async def test_missing_users_return_none() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    assert await by_id(cast(AsyncSession, session), uuid4()) is None
    assert await by_email(cast(AsyncSession, session), "missing@example.com") is None
