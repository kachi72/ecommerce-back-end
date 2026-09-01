"""Unit tests for durable background-job lifecycle operations."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.jobs.models import Job, JobStatus
from ekumidayomi.jobs.service import JobService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def session_mock() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    return session


def job(
    status: JobStatus = JobStatus.PENDING,
    *,
    attempts: int = 0,
    max_attempts: int = 3,
) -> Job:
    return Job(
        id=uuid4(),
        job_type="send_email",
        payload={"recipient": "customer"},
        idempotency_key=f"order:{uuid4()}:email",
        status=status.value,
        attempts=attempts,
        max_attempts=max_attempts,
        available_at=NOW,
    )


def test_enqueue_stages_validated_job_without_committing() -> None:
    session = session_mock()

    result = JobService(session).enqueue(
        job_type="send_email",
        payload={"order_id": "one"},
        idempotency_key="order:one:email",
        available_at=NOW,
    )

    assert result.status == JobStatus.PENDING.value
    assert result.available_at == NOW
    assert result.max_attempts == 5
    session.add.assert_called_once_with(result)
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"job_type": "Bad Type"}, ValueError),
        ({"idempotency_key": "bad key"}, ValueError),
        ({"max_attempts": True}, TypeError),
        ({"max_attempts": 0}, ValueError),
        ({"payload": []}, TypeError),
    ],
)
def test_enqueue_rejects_invalid_inputs(
    arguments: dict[str, object],
    error: type[Exception],
) -> None:
    values: dict[str, object] = {
        "job_type": "send_email",
        "payload": {},
        "idempotency_key": "order:one:email",
        "available_at": NOW,
    }
    values.update(arguments)

    with pytest.raises(error):
        JobService(session_mock()).enqueue(**values)  # type: ignore[arg-type]


async def test_claim_uses_skip_locked_and_assigns_a_bounded_lease() -> None:
    session = session_mock()
    queued = job()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [queued]
    session.scalars.return_value = scalar_result

    result = await JobService(session).claim(
        worker="worker-1",
        lease=timedelta(seconds=30),
        limit=2,
        now=NOW,
    )

    assert result == (queued,)
    assert queued.status == JobStatus.RUNNING.value
    assert queued.attempts == 1
    assert queued.lease_owner == "worker-1"
    assert queued.lease_token is not None
    assert queued.lease_expires_at == NOW + timedelta(seconds=30)
    statement = session.scalars.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).upper()  # type: ignore[no-untyped-call]
    assert "FOR UPDATE SKIP LOCKED" in sql
    session.flush.assert_awaited_once()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"worker": "bad worker"}, ValueError),
        ({"lease": timedelta(0)}, ValueError),
        ({"lease": "30 seconds"}, TypeError),
        ({"limit": True}, TypeError),
        ({"limit": 101}, ValueError),
    ],
)
async def test_claim_rejects_invalid_inputs(
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    values: dict[str, object] = {
        "worker": "worker-1",
        "lease": timedelta(seconds=30),
        "now": NOW,
    }
    values.update(kwargs)
    with pytest.raises(error):
        await JobService(session_mock()).claim(**values)  # type: ignore[arg-type]


async def test_retry_uses_deterministic_backoff_and_clears_the_lease() -> None:
    session = session_mock()
    running = job(JobStatus.RUNNING, attempts=2)
    running.lease_owner = "worker-1"
    running.lease_token = uuid4()
    running.lease_expires_at = NOW + timedelta(minutes=1)
    session.get.return_value = running

    assert await JobService(session).retry(
        running.id,
        running.lease_token,
        error_code="provider_unavailable",
        jitter_seconds=0.5,
        now=NOW,
    )
    assert running.status == JobStatus.RETRYING.value
    assert running.available_at == NOW + timedelta(seconds=4.5)
    assert running.last_error_code == "provider_unavailable"
    assert running.lease_owner is None
    assert running.lease_token is None
    assert running.lease_expires_at is None


async def test_retry_exhaustion_retains_dead_letter_evidence() -> None:
    session = session_mock()
    running = job(JobStatus.RUNNING, attempts=3, max_attempts=3)
    token = uuid4()
    running.lease_token = token
    running.lease_expires_at = NOW + timedelta(minutes=1)
    session.get.return_value = running

    assert await JobService(session).retry(
        running.id,
        token,
        error_code="delivery_failed",
        now=NOW,
    )
    assert running.status == JobStatus.FAILED.value
    assert running.finished_at == NOW
    assert running.last_error_code == "delivery_failed"
    session.delete.assert_not_awaited()


async def test_expired_claim_is_recovered_for_restart() -> None:
    session = session_mock()
    expired = job(JobStatus.RUNNING, attempts=1)
    expired.lease_token = uuid4()
    expired.lease_owner = "dead-worker"
    expired.lease_expires_at = NOW - timedelta(seconds=1)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [expired]
    session.scalars.return_value = scalar_result

    assert await JobService(session).recover_expired(now=NOW) == 1
    assert expired.status == JobStatus.RETRYING.value
    assert expired.available_at == NOW
    assert expired.last_error_code == "lease_expired"
    assert expired.lease_token is None


async def test_status_view_does_not_expose_payload_or_result() -> None:
    session = session_mock()
    queued = job()
    queued.result = {"private": "result"}
    session.get.return_value = queued

    view = await JobService(session).get_status(queued.id)

    assert view is not None
    fields = asdict(view)
    assert fields["job_id"] == queued.id
    assert "payload" not in fields
    assert "result" not in fields


async def test_status_view_returns_none_for_missing_job() -> None:
    session = session_mock()
    session.get.return_value = None

    assert await JobService(session).get_status(uuid4()) is None
