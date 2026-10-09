"""Use distinct PostgreSQL sessions: never simulate concurrency on one session."""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.leased_repository import LeasedOutboxRepository
from ekumidayomi.outbox.leased_worker import LeasedOutboxWorker
from ekumidayomi.outbox.model import OutboxMessage
from ekumidayomi.outbox.operations import RecoveryReason, replay, resume
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.ports import PreparedDelivery
from ekumidayomi.outbox.repository import OutboxRepository
from ekumidayomi.outbox.settings import OutboxWorkerSettings


@pytest.fixture
def sessions(database_connection: Any) -> Any:
    options = database_connection.sync_connection.get_execution_options()
    engine = database_connection.engine.execution_options(
        schema_translate_map=options["schema_translate_map"]
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def factory(sessions: Any) -> Any:
    return lambda: SqlAlchemyUnitOfWork(sessions)


async def seed(sessions: Any) -> Any:
    event = DomainEvent(uuid4(), "test_delivery", "test", uuid4(), 1, utc_now(), {})
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        OutboxRepository(uow.session).add(event)
        await uow.commit()
    return event


async def claim(sessions: Any) -> Any:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        result = await LeasedOutboxRepository(uow.session).claim(
            ("test_delivery",), OutboxWorkerSettings()
        )
        await uow.commit()
        return result


async def expire(sessions: Any, message_id: Any) -> Any:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.get(OutboxMessage, message_id)
        assert row is not None
        row.lease_expires_at = await LeasedOutboxRepository(uow.session).now() - timedelta(
            seconds=1
        )
        await uow.commit()


async def test_concurrent_claims_and_stale_completion(sessions: Any) -> None:
    await seed(sessions)
    claims = await asyncio.gather(claim(sessions), claim(sessions))
    winners = [value for value in claims if value is not None]
    assert len(winners) == 1
    first = winners[0]
    await expire(sessions, first.message_id)
    second = await claim(sessions)
    assert second.token != first.token
    assert second.attempts == 2
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        repo = LeasedOutboxRepository(uow.session)
        assert not await repo.finish(first, DeliveryOutcome(OutcomeKind.ACCEPTED, "accepted"), 0)
        assert await repo.finish(second, DeliveryOutcome(OutcomeKind.ACCEPTED, "accepted"), 0)
        await uow.commit()


class IdempotentHandler:
    def __init__(self) -> None:
        self.accepted: dict[object, str] = {}
        self.calls = 0
        self.active_uows: Callable[[], int] | None = None

    async def prepare(self, uow: Any, event: Any) -> Any:
        return PreparedDelivery(event.event_id, "a" * 64, utc_now() + timedelta(seconds=300))

    async def deliver(self, prepared: Any, completed: Any) -> Any:
        if self.active_uows is not None:
            assert self.active_uows() == 0
        self.calls += 1
        receipt = self.accepted.setdefault(prepared.payload, str(uuid4()))
        return DeliveryOutcome(OutcomeKind.ACCEPTED, "accepted", receipts={"0": receipt})


async def test_acceptance_then_commit_failure_retries_same_identity(
    sessions: Any, monkeypatch: Any
) -> None:
    await seed(sessions)
    handler = IdempotentHandler()
    worker = LeasedOutboxWorker(
        uow_factory=factory(sessions),
        handlers={"test_delivery": handler},
        settings=OutboxWorkerSettings(),
    )
    original = SqlAlchemyUnitOfWork.commit
    commits = 0

    async def failing_commit(self: SqlAlchemyUnitOfWork) -> None:
        nonlocal commits
        commits += 1
        if commits == 3:
            raise RuntimeError("simulated final commit failure")
        await original(self)

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        await worker.process_one()
    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", original)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.scalar(sa.select(OutboxMessage))
        assert row is not None
        message_id = row.id
        assert row.status == "processing"
        assert row.delivery_fingerprint is not None
    await expire(sessions, message_id)
    assert await worker.process_one()
    assert handler.calls == 2
    assert len(handler.accepted) == 1
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.get(OutboxMessage, message_id)
        assert row is not None
        assert row.status == "published"
        assert row.attempts == 2


async def test_external_io_has_no_active_unit_of_work(sessions: Any) -> None:
    await seed(sessions)
    active = 0

    @asynccontextmanager
    async def tracked() -> Any:
        nonlocal active
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            active += 1
            try:
                yield uow
            finally:
                active -= 1

    handler = IdempotentHandler()
    handler.active_uows = lambda: active
    assert await LeasedOutboxWorker(
        uow_factory=tracked, handlers={"test_delivery": handler}, settings=OutboxWorkerSettings()
    ).process_one()


async def test_binding_changed_content_cannot_send(sessions: Any) -> None:
    await seed(sessions)
    first = await claim(sessions)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        assert await LeasedOutboxRepository(uow.session).bind(
            first, "a" * 64, utc_now() + timedelta(seconds=300)
        )
        await uow.commit()
    await expire(sessions, first.message_id)
    second = await claim(sessions)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        assert not await LeasedOutboxRepository(uow.session).bind(
            second, "b" * 64, utc_now() + timedelta(seconds=300)
        )
        await uow.commit()
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.get(OutboxMessage, first.message_id)
        assert row is not None
        assert row.status == "blocked"
        assert row.delivery_fingerprint == "a" * 64


async def test_configuration_pause_survives_new_worker(sessions: Any) -> None:
    await seed(sessions)
    first = await claim(sessions)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await LeasedOutboxRepository(uow.session).finish(
            first, DeliveryOutcome(OutcomeKind.BLOCKED, "provider_configuration"), 0
        )
        await uow.commit()
    await seed(sessions)
    assert await claim(sessions) is None
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await resume(uow, "auth_email")
        await uow.commit()
    assert await claim(sessions) is not None


async def test_replay_preserves_attempts_key_and_receipts(sessions: Any) -> None:
    await seed(sessions)
    first = await claim(sessions)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.get(OutboxMessage, first.message_id)
        assert row is not None
        row.status = "dead"
        row.claim_token = None
        row.lease_expires_at = None
        row.delivery_fingerprint = "a" * 64
        row.delivery_receipts = {"0": str(uuid4())}
        before = (row.attempts, row.idempotency_key, dict(row.delivery_receipts))
        await uow.commit()
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await replay(
            uow,
            first.message_id,
            RecoveryReason.TRANSIENT_RESOLVED,
            {"test_delivery": IdempotentHandler()},
        )
        await uow.commit()
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.get(OutboxMessage, first.message_id)
        assert row is not None
        assert (row.attempts, row.idempotency_key, row.delivery_receipts) == before
        assert row.retry_budget == row.attempts + 3
        row.deadline_at = utc_now() - timedelta(seconds=1)
        row.status = "dead"
        await uow.commit()
        with pytest.raises(ValueError):
            await replay(
                uow,
                first.message_id,
                RecoveryReason.TRANSIENT_RESOLVED,
                {"test_delivery": IdempotentHandler()},
            )


async def test_unregistered_events_and_expired_intents_do_not_send(sessions: Any) -> None:
    await seed(sessions)
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        row = await uow.session.scalar(sa.select(OutboxMessage))
        assert row is not None
        row.deadline_at = utc_now() - timedelta(seconds=1)
        await uow.commit()
    handler = IdempotentHandler()
    worker = LeasedOutboxWorker(
        uow_factory=factory(sessions),
        handlers={"test_delivery": handler},
        settings=OutboxWorkerSettings(),
    )
    assert not await worker.process_one()
    assert handler.calls == 0


async def test_unknown_event_type_is_not_claimed(sessions: Any) -> None:
    unknown = DomainEvent(uuid4(), "other_delivery", "test", uuid4(), 1, utc_now(), {})
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        OutboxRepository(uow.session).add(unknown)
        await uow.commit()
    assert await claim(sessions) is None


async def test_shutdown_drains_current_work_and_stops_claiming(sessions: Any) -> None:
    await seed(sessions)
    await seed(sessions)
    stop = asyncio.Event()

    class StoppingHandler(IdempotentHandler):
        async def deliver(self, prepared: Any, completed: Any) -> Any:
            stop.set()
            return await super().deliver(prepared, completed)

    handler = StoppingHandler()
    runner = LeasedOutboxWorker(
        uow_factory=factory(sessions),
        handlers={"test_delivery": handler},
        settings=OutboxWorkerSettings(),
    )
    await asyncio.wait_for(runner.run(stop=stop), timeout=5)
    assert handler.calls == 1
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        pending = await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.status == "pending")
        )
        assert pending == 1
