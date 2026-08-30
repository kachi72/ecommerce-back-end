"""PostgreSQL-backed unit-of-work transaction tests."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from ekumidayomi.db.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


async def test_unit_of_work_commit_and_implicit_rollback(
    database_connection: AsyncConnection,
) -> None:
    await database_connection.execute(
        text("CREATE TABLE uow_probe (id integer PRIMARY KEY, value text NOT NULL)")
    )
    await database_connection.commit()
    factory = async_sessionmaker(
        bind=database_connection,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        await unit_of_work.session.execute(
            text("INSERT INTO uow_probe (id, value) VALUES (1, 'rolled-back')")
        )

    rolled_back_count = await database_connection.scalar(
        text("SELECT count(*) FROM uow_probe WHERE id = 1")
    )
    assert rolled_back_count == 0

    async with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        await unit_of_work.session.execute(
            text("INSERT INTO uow_probe (id, value) VALUES (2, 'committed')")
        )
        await unit_of_work.commit()

    committed_value = await database_connection.scalar(
        text("SELECT value FROM uow_probe WHERE id = 2")
    )
    assert committed_value == "committed"
