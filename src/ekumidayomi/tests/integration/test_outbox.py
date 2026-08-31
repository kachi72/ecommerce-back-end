"""PostgreSQL integration tests for the transactional outbox."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from ekumidayomi.db.uow import SqlAlchemyUnitOfWork
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.model import OutboxMessage, OutboxStatus
from ekumidayomi.outbox.repository import OutboxRepository
from ekumidayomi.tests.integration.conftest import set_search_path

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def event(
    *,
    aggregate_id: UUID | None = None,
    version: int = 1,
    occurred_at: datetime = NOW,
) -> DomainEvent:
    return DomainEvent(
        event_id=uuid4(),
        event_type="product_updated",
        aggregate_type="product",
        aggregate_id=aggregate_id or uuid4(),
        aggregate_version=version,
        occurred_at=occurred_at,
        payload={"version": version},
    )


def factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=connection, expire_on_commit=False)


async def test_business_state_and_outbox_intent_are_atomic(
    database_connection: AsyncConnection,
) -> None:
    await database_connection.execute(
        text("CREATE TABLE business_probe (id uuid PRIMARY KEY, name text NOT NULL)")
    )
    await database_connection.commit()
    sessions = factory(database_connection)

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await uow.session.execute(
            text("INSERT INTO business_probe (id, name) VALUES (:id, :name)"),
            {"id": uuid4(), "name": "rolled back"},
        )
        OutboxRepository(uow.session).add(event())

    async with sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM business_probe")) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 0

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await uow.session.execute(
            text("INSERT INTO business_probe (id, name) VALUES (:id, :name)"),
            {"id": uuid4(), "name": "committed"},
        )
        OutboxRepository(uow.session).add(event())
        await uow.commit()

    async with sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM business_probe")) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1


async def test_duplicate_idempotency_key_cannot_create_two_intents(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    key = "product:one:version:one"
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        OutboxRepository(uow.session).add(event(), idempotency_key=key)
        await uow.commit()

    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            OutboxRepository(uow.session).add(event(), idempotency_key=key)
            await uow.commit()

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1


async def test_claiming_preserves_aggregate_version_order(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    aggregate_id = uuid4()
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        repository = OutboxRepository(uow.session)
        repository.add(event(aggregate_id=aggregate_id, version=1))
        repository.add(event(aggregate_id=aggregate_id, version=2))
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        repository = OutboxRepository(uow.session)
        claimed = await repository.claim_batch(limit=2, now=NOW + timedelta(seconds=1))
        assert [message.aggregate_version for message in claimed] == [1]
        assert await repository.mark_published(claimed[0].id, published_at=NOW)
        assert not await repository.mark_published(claimed[0].id, published_at=NOW)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        claimed = await OutboxRepository(uow.session).claim_batch(
            limit=2, now=NOW + timedelta(seconds=1)
        )
        assert [message.aggregate_version for message in claimed] == [2]


async def test_concurrent_workers_claim_non_overlapping_rows(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        repository = OutboxRepository(uow.session)
        repository.add(event(occurred_at=NOW))
        repository.add(event(occurred_at=NOW + timedelta(microseconds=1)))
        await uow.commit()

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
            first = await OutboxRepository(first_uow.session).claim_batch(
                limit=1, now=NOW + timedelta(seconds=1)
            )
            async with SqlAlchemyUnitOfWork(second_factory) as second_uow:
                second = await OutboxRepository(second_uow.session).claim_batch(
                    limit=1, now=NOW + timedelta(seconds=1)
                )
                assert len(first) == len(second) == 1
                assert first[0].id != second[0].id
                await second_uow.commit()
            await first_uow.commit()
    finally:
        await first_connection.close()
        await second_connection.close()


async def test_failed_delivery_is_visible_and_retryable(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        OutboxRepository(uow.session).add(event())
        await uow.commit()

    retry_at = NOW + timedelta(minutes=1)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        repository = OutboxRepository(uow.session)
        claimed = (await repository.claim_batch(now=NOW + timedelta(seconds=1)))[0]
        assert await repository.mark_failed(
            claimed.id,
            error_code="provider_unavailable",
            available_at=retry_at,
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        repository = OutboxRepository(uow.session)
        assert await repository.claim_batch(now=retry_at - timedelta(seconds=1)) == ()
        retried = (await repository.claim_batch(now=retry_at))[0]
        assert retried.attempts == 2
        assert retried.status is OutboxStatus.PROCESSING
