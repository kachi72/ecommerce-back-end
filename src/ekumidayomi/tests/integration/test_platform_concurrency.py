"""PostgreSQL concurrency evidence for shared platform contracts."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from ekumidayomi.db.uow import SqlAlchemyUnitOfWork
from ekumidayomi.jobs.service import JobService
from ekumidayomi.tests.integration.conftest import set_search_path

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def session_factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Create sessions bound to one independently managed connection."""
    return async_sessionmaker(bind=connection, expire_on_commit=False)


async def test_two_workers_do_not_claim_the_same_job(
    database_connection: AsyncConnection,
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory(database_connection)) as uow:
        JobService(uow.session).enqueue(
            job_type="platform_probe",
            payload={},
            idempotency_key="platform:probe:single-claim",
            available_at=NOW,
        )
        await uow.commit()

    schema = await database_connection.scalar(text("SELECT current_schema()"))
    assert isinstance(schema, str)
    first_connection = await database_connection.engine.connect()
    second_connection = await database_connection.engine.connect()
    try:
        await set_search_path(first_connection, f'"{schema}", public')
        await set_search_path(second_connection, f'"{schema}", public')
        await first_connection.commit()
        await second_connection.commit()

        async with SqlAlchemyUnitOfWork(session_factory(first_connection)) as first:
            first_claim = await JobService(first.session).claim(
                worker="platform-worker-first",
                lease=timedelta(seconds=30),
                now=NOW,
            )
            async with SqlAlchemyUnitOfWork(session_factory(second_connection)) as second:
                second_claim = await JobService(second.session).claim(
                    worker="platform-worker-second",
                    lease=timedelta(seconds=30),
                    now=NOW,
                )

                assert second_claim == ()
                await second.commit()

            assert len(first_claim) == 1
            await first.commit()
    finally:
        await first_connection.close()
        await second_connection.close()
