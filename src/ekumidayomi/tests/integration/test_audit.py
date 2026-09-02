"""PostgreSQL-backed immutable audit integration tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from ekumidayomi.audit.model import ActorKind, AuditOutcome, AuditRecord
from ekumidayomi.audit.service import AuditActor, AuditFilters, query_records, record
from ekumidayomi.core.types import PageRequest
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=connection, expire_on_commit=False)


def stage_record(
    uow: SqlAlchemyUnitOfWork,
    *,
    action: str = "product.created",
    target_id: UUID | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
    correlation_id: str = "request-1",
    occurred_at: datetime = NOW,
) -> AuditRecord:
    return record(
        uow,
        actor=AuditActor(ActorKind.SYSTEM),
        action=action,
        target_type="product",
        target_id=target_id or uuid4(),
        outcome=outcome,
        metadata={"source": "admin", "password": "never-store"},
        allowed_metadata_keys=frozenset({"source", "password"}),
        correlation_id=correlation_id,
        occurred_at=occurred_at,
    )


async def test_audit_rolls_back_with_the_business_transaction(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        stage_record(uow)

    async with sessions() as session:
        count = await session.scalar(sa.select(sa.func.count()).select_from(AuditRecord))

    assert count == 0


async def test_audit_commits_sanitized_evidence_with_the_transaction(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        audit = stage_record(uow)
        await uow.session.flush()
        audit_id = audit.id
        await uow.commit()

    async with sessions() as session:
        persisted = await session.get(AuditRecord, audit_id)

    assert persisted is not None
    assert persisted.actor_kind == "system"
    assert persisted.actor_id is None
    assert persisted.metadata_ == {
        "source": "admin",
        "password": "[REDACTED]",
    }
    assert persisted.occurred_at == NOW


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_orm_rejects_mutating_existing_audit_records(
    database_connection: AsyncConnection,
    operation: str,
) -> None:
    sessions = factory(database_connection)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        audit = stage_record(uow)
        await uow.session.flush()
        audit_id = audit.id
        await uow.commit()

    with pytest.raises(sa.exc.InvalidRequestError, match="append-only"):
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            persisted = await uow.session.get(AuditRecord, audit_id)
            assert persisted is not None
            if operation == "update":
                persisted.action = "product.changed"
            else:
                await uow.session.delete(persisted)
            await uow.commit()

    async with sessions() as session:
        persisted = await session.get(AuditRecord, audit_id)

    assert persisted is not None
    assert persisted.action == "product.created"


async def test_query_records_applies_filters_and_stable_newest_first_order(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    target_id = uuid4()
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        first = stage_record(
            uow,
            target_id=target_id,
            correlation_id="request-first",
            occurred_at=NOW,
        )
        stage_record(
            uow,
            action="product.updated",
            target_id=target_id,
            outcome=AuditOutcome.FAILED,
            correlation_id="request-excluded",
            occurred_at=NOW + timedelta(hours=1),
        )
        newest = stage_record(
            uow,
            target_id=target_id,
            correlation_id="request-newest",
            occurred_at=NOW + timedelta(hours=2),
        )
        await uow.session.flush()
        first_id = first.id
        newest_id = newest.id
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        page = await query_records(
            uow,
            filters=AuditFilters(
                action="product.created",
                actor_kind=ActorKind.SYSTEM,
                target_type="product",
                target_id=target_id,
                outcome=AuditOutcome.SUCCEEDED,
                occurred_from=NOW,
                occurred_to=NOW + timedelta(hours=2),
            ),
            page_request=PageRequest(page=1, page_size=20),
        )
        result_ids = [item.id for item in page.items]

    assert page.total_items == 2
    assert result_ids == [newest_id, first_id]


async def test_query_records_supports_actor_correlation_and_empty_pages(
    database_connection: AsyncConnection,
) -> None:
    sessions = factory(database_connection)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        expected = stage_record(uow, correlation_id="request-match")
        stage_record(uow, correlation_id="request-other", occurred_at=NOW + timedelta(seconds=1))
        await uow.session.flush()
        expected_id = expected.id
        await uow.commit()

    async with SqlAlchemyUnitOfWork(sessions) as uow:
        matched = await query_records(
            uow,
            filters=AuditFilters(
                actor_kind=ActorKind.SYSTEM,
                correlation_id="request-match",
            ),
            page_request=PageRequest(),
        )
        empty = await query_records(
            uow,
            filters=AuditFilters(action="order.created"),
            page_request=PageRequest(page=2, page_size=1),
        )
        matched_ids = [item.id for item in matched.items]

    assert matched_ids == [expected_id]
    assert empty.items == ()
    assert empty.total_items == 0
    assert empty.total_pages == 0
