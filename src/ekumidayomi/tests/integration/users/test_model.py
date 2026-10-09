"""Real PostgreSQL persistence and concurrent normalized-email uniqueness."""

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from ekumidayomi.tests.integration.conftest import set_search_path
from ekumidayomi.users.errors import InvalidEmailError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import create_customer, find_user_by_email, find_user_by_id


async def test_customer_defaults_and_unicode_profile_round_trip(
    database_session: AsyncSession,
) -> None:
    user = await create_customer(database_session, email="customer@example.com")
    assert isinstance(user.id, UUID)
    assert user.role == Role.CUSTOMER.value
    assert user.is_active is True
    assert user.email_verified_at is None
    assert user.display_name == ""
    assert user.phone is None
    assert user.created_at.utcoffset() is not None
    assert user.updated_at.utcoffset() is not None
    user.display_name = "Ẹkúmidáyọ̀mí"
    user.phone = "+2348012345678"
    user_id = user.id
    await database_session.commit()
    database_session.expunge_all()
    restored = await find_user_by_id(database_session, user_id)
    assert restored is not None
    assert restored.display_name == "Ẹkúmidáyọ̀mí"
    assert restored.phone == "+2348012345678"


async def test_normalized_email_is_unique(database_session: AsyncSession) -> None:
    await create_customer(database_session, email="Customer@example.com")
    with pytest.raises(IntegrityError) as caught:
        async with database_session.begin_nested():
            await create_customer(database_session, email=" customer@EXAMPLE.com ")
    assert "uq_users_email" in str(caught.value.orig)
    assert await database_session.scalar(sa.select(sa.func.count()).select_from(User)) == 1


async def test_email_lookup_is_case_insensitive(database_session: AsyncSession) -> None:
    user = await create_customer(database_session, email="customer@example.com")
    found = await find_user_by_email(database_session, " CUSTOMER@EXAMPLE.com ")
    assert found is not None
    assert found.id == user.id
    assert await find_user_by_email(database_session, "missing@example.com") is None
    assert await find_user_by_id(database_session, uuid4()) is None


async def test_repository_leaves_rollback_to_caller(database_session: AsyncSession) -> None:
    user = await create_customer(database_session, email="rollback@example.com")
    user_id = user.id
    await database_session.rollback()
    assert await find_user_by_id(database_session, user_id) is None


async def test_invalid_email_does_not_add_a_user(database_session: AsyncSession) -> None:
    with pytest.raises(InvalidEmailError):
        await create_customer(database_session, email="invalid")
    assert await database_session.scalar(sa.select(sa.func.count()).select_from(User)) == 0


@pytest.mark.parametrize(
    "emails",
    [
        ("customer@example.com", "customer@example.com"),
        ("Customer@example.com", " customer@EXAMPLE.com "),
    ],
    ids=["identical-email", "mixed-case-email"],
)
async def test_concurrent_inserts_allow_exactly_one_customer(
    database_connection: AsyncConnection,
    emails: tuple[str, str],
) -> None:
    search_path = await database_connection.scalar(sa.text("SHOW search_path"))
    assert isinstance(search_path, str)
    await database_connection.commit()
    start = asyncio.Event()
    ready = [asyncio.Event(), asyncio.Event()]

    async def insert(index: int, email: str) -> str:
        async with database_connection.engine.connect() as connection:
            await set_search_path(connection, search_path)
            await connection.commit()
            async with AsyncSession(connection, expire_on_commit=False) as session:
                ready[index].set()
                await start.wait()
                try:
                    await create_customer(session, email=email)
                    await session.commit()
                except IntegrityError as error:
                    await session.rollback()
                    assert "uq_users_email" in str(error.orig)
                    return "duplicate"
                return "created"

    async with asyncio.timeout(15):
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(insert(index, email)) for index, email in enumerate(emails)]
            await asyncio.gather(*(event.wait() for event in ready))
            start.set()
    assert sorted(task.result() for task in tasks) == ["created", "duplicate"]
    assert await database_connection.scalar(sa.select(sa.func.count()).select_from(User)) == 1
