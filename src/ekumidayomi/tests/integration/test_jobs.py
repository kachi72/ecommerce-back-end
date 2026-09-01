"""PostgreSQL integration tests for durable background jobs."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from ekumidayomi.db.uow import SqlAlchemyUnitOfWork
from ekumidayomi.jobs.models import Job, JobStatus
from ekumidayomi.jobs.service import JobService
from ekumidayomi.tests.integration.conftest import set_search_path

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=connection, expire_on_commit=False)


async def enqueue_job(
    sessions: async_sessionmaker[AsyncSession],
    *,
    key: str,
    max_attempts: int = 3,
    available_at: datetime = NOW,
) -> Job:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        job = JobService(uow.session).enqueue(
            job_type="send_email",
            payload={"recipient": "customer@example.com"},
            idempotency_key=key,
            max_attempts=max_attempts,
            available_at=available_at,
        )
        await uow.commit()
        return job


async def test_duplicate_enqueue_is_rejected(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    await enqueue_job(sessions, key="order:one:email")

    with pytest.raises(IntegrityError):
        await enqueue_job(sessions, key="order:one:email")


async def test_claim_heartbeat_complete_and_safe_polling(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    queued = await enqueue_job(sessions, key="order:two:email")

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        service = JobService(uow.session)
        claimed = (
            await service.claim(
                worker="worker-1",
                lease=timedelta(seconds=30),
                now=NOW,
            )
        )[0]
        assert claimed.id == queued.id
        assert claimed.lease_token is not None
        token = claimed.lease_token
        assert await service.heartbeat(
            claimed.id,
            token,
            lease_expires_at=NOW + timedelta(minutes=1),
            now=NOW,
        )
        assert await service.complete(
            claimed.id,
            token,
            result={"sent": True},
            now=NOW + timedelta(seconds=1),
        )
        await uow.commit()

    async with sessions() as session:
        view = await JobService(session).get_status(queued.id)
        assert view is not None
        assert view.status == JobStatus.SUCCEEDED.value
        assert view.finished_at == NOW + timedelta(seconds=1)
        assert not hasattr(view, "payload")
        assert not hasattr(view, "result")


async def test_retry_exhaustion_and_cancellation_are_retained(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    failing = await enqueue_job(sessions, key="order:three:email", max_attempts=1)
    cancelled = await enqueue_job(
        sessions,
        key="order:four:email",
        available_at=NOW + timedelta(minutes=1),
    )

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        service = JobService(uow.session)
        claimed = (
            await service.claim(
                worker="worker-1",
                lease=timedelta(minutes=1),
                now=NOW,
            )
        )[0]
        assert claimed.id == failing.id
        assert claimed.lease_token is not None
        assert await service.retry(
            claimed.id,
            claimed.lease_token,
            error_code="provider_unavailable",
            now=NOW,
        )
        assert await service.cancel(cancelled.id, now=NOW)
        await uow.commit()

    async with sessions() as session:
        failed = await session.get(Job, failing.id)
        cancelled_job = await session.get(Job, cancelled.id)
        assert failed is not None
        assert failed.status == JobStatus.FAILED.value
        assert failed.last_error_code == "provider_unavailable"
        assert cancelled_job is not None
        assert cancelled_job.status == JobStatus.CANCELLED.value


async def test_expired_lease_is_recovered_after_restart(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    queued = await enqueue_job(sessions, key="order:five:email")

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        claimed = (
            await JobService(uow.session).claim(
                worker="worker-before-restart",
                lease=timedelta(seconds=10),
                now=NOW,
            )
        )[0]
        assert claimed.id == queued.id
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        service = JobService(uow.session)
        assert await service.recover_expired(now=NOW + timedelta(seconds=11)) == 1
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        recovered = (
            await JobService(uow.session).claim(
                worker="worker-after-restart",
                lease=timedelta(seconds=10),
                now=NOW + timedelta(seconds=11),
            )
        )[0]
        assert recovered.id == queued.id
        assert recovered.attempts == 2
        assert recovered.status == JobStatus.RUNNING.value


async def test_concurrent_workers_claim_non_overlapping_jobs(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    await enqueue_job(sessions, key="order:six:email")
    await enqueue_job(sessions, key="order:seven:email")

    schema = await database_connection.scalar(text("SELECT current_schema()"))
    assert isinstance(schema, str)
    first_connection = await database_connection.engine.connect()
    second_connection = await database_connection.engine.connect()
    try:
        await set_search_path(first_connection, f'"{schema}", public')
        await set_search_path(second_connection, f'"{schema}", public')
        first_factory = factory(first_connection)
        second_factory = factory(second_connection)
        async with SqlAlchemyUnitOfWork(first_factory) as first_uow:
            first = await JobService(first_uow.session).claim(
                worker="worker-1",
                lease=timedelta(seconds=30),
                now=NOW,
            )
            async with SqlAlchemyUnitOfWork(second_factory) as second_uow:
                second = await JobService(second_uow.session).claim(
                    worker="worker-2",
                    lease=timedelta(seconds=30),
                    now=NOW,
                )
                assert len(first) == len(second) == 1
                assert first[0].id != second[0].id
                await second_uow.commit()
            await first_uow.commit()
    finally:
        await first_connection.close()
        await second_connection.close()
