"""Unit tests for transactional outbox persistence operations."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.model import OutboxMessage, OutboxStatus
from ekumidayomi.outbox.repository import OutboxRepository

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def event(*, version: int = 1) -> DomainEvent:
    return DomainEvent(
        event_id=uuid4(),
        event_type="product_updated",
        aggregate_type="product",
        aggregate_id=uuid4(),
        aggregate_version=version,
        occurred_at=NOW,
        payload={"version": version},
    )


def session_mock() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    return session


def message(status: OutboxStatus = OutboxStatus.PENDING) -> OutboxMessage:
    return OutboxMessage(
        id=uuid4(),
        event_id=uuid4(),
        idempotency_key=f"event:{uuid4()}",
        event_type="product_updated",
        aggregate_type="product",
        aggregate_id=uuid4(),
        aggregate_version=1,
        occurred_at=NOW,
        payload={"version": 1},
        status=status,
        attempts=0,
        available_at=NOW,
    )


@pytest.mark.parametrize("max_attempts", [True, 1.5])
def test_repository_requires_integer_attempt_limit(max_attempts: object) -> None:
    with pytest.raises(TypeError):
        OutboxRepository(session_mock(), max_attempts=max_attempts)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_attempts", [0, 101])
def test_repository_bounds_attempt_limit(max_attempts: int) -> None:
    with pytest.raises(ValueError):
        OutboxRepository(session_mock(), max_attempts=max_attempts)


def test_add_stages_json_safe_message_without_committing() -> None:
    session = session_mock()
    domain_event = event()

    result = OutboxRepository(session).add(domain_event)

    assert result.idempotency_key == f"event:{domain_event.event_id}"
    assert result.payload == {"version": 1}
    assert result.status is OutboxStatus.PENDING
    session.add.assert_called_once_with(result)
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("key", ["", "bad key", "x" * 256])
def test_add_rejects_unsafe_idempotency_key(key: str) -> None:
    with pytest.raises(ValueError):
        OutboxRepository(session_mock()).add(event(), idempotency_key=key)


async def test_claim_batch_uses_skip_locked_and_transitions_messages() -> None:
    session = session_mock()
    claimed = message(OutboxStatus.FAILED)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [claimed]
    session.scalars.return_value = scalar_result

    result = await OutboxRepository(session, max_attempts=3).claim_batch(limit=2, now=NOW)

    assert result == (claimed,)
    assert claimed.status is OutboxStatus.PROCESSING
    assert claimed.attempts == 1
    assert claimed.claimed_at == NOW
    statement = session.scalars.await_args.args[0]
    sql = str(
        statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    ).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "NOT (EXISTS" in sql
    session.flush.assert_awaited_once()


@pytest.mark.parametrize("limit", [True, 1.5])
async def test_claim_requires_integer_limit(limit: object) -> None:
    with pytest.raises(TypeError):
        await OutboxRepository(session_mock()).claim_batch(limit=limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, 101])
async def test_claim_bounds_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        await OutboxRepository(session_mock()).claim_batch(limit=limit)


async def test_publish_is_idempotent() -> None:
    session = session_mock()
    claimed = message(OutboxStatus.PROCESSING)
    session.get.return_value = claimed
    repository = OutboxRepository(session)

    assert await repository.mark_published(claimed.id, published_at=NOW)
    assert claimed.status is OutboxStatus.PUBLISHED
    assert not await repository.mark_published(claimed.id, published_at=NOW)


@pytest.mark.parametrize("existing", [None, OutboxStatus.PENDING])
async def test_publish_requires_processing_message(existing: OutboxStatus | None) -> None:
    session = session_mock()
    session.get.return_value = None if existing is None else message(existing)
    assert not await OutboxRepository(session).mark_published(uuid4(), published_at=NOW)


async def test_failed_message_is_retained_for_retry() -> None:
    session = session_mock()
    claimed = message(OutboxStatus.PROCESSING)
    session.get.return_value = claimed
    later = NOW + timedelta(minutes=1)

    assert await OutboxRepository(session).mark_failed(
        claimed.id, error_code="provider_unavailable", available_at=later
    )
    assert claimed.status is OutboxStatus.FAILED
    assert claimed.available_at == later
    assert claimed.last_error_code == "provider_unavailable"


@pytest.mark.parametrize("error_code", ["Provider Error", "x" * 101, ""])
async def test_failure_rejects_unsafe_error_code(error_code: str) -> None:
    with pytest.raises(ValueError):
        await OutboxRepository(session_mock()).mark_failed(
            uuid4(), error_code=error_code, available_at=NOW
        )


async def test_stale_claims_are_recoverable_without_deletion() -> None:
    session = session_mock()
    claimed = message(OutboxStatus.PROCESSING)
    claimed.claimed_at = NOW - timedelta(minutes=5)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [claimed]
    session.scalars.return_value = scalar_result

    count = await OutboxRepository(session).recover_stale_claims(
        stale_before=NOW - timedelta(minutes=1), available_at=NOW
    )

    assert count == 1
    assert claimed.status is OutboxStatus.FAILED
    assert claimed.last_error_code == "claim_expired"
    session.delete.assert_not_awaited()
