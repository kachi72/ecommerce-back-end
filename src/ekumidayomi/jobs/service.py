"""Durable background-job lifecycle operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.core.types import require_utc, utc_now
from ekumidayomi.jobs.models import Job, JobStatus

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_JOB_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_WORKER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_MAX_BATCH_SIZE = 100
_MAX_LEASE = timedelta(hours=24)
_MAX_RETRY_DELAY_SECONDS = 300


@dataclass(frozen=True, slots=True)
class JobStatusView:
    """Safe polling projection that excludes private payloads and results."""

    job_id: UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error_code: str | None


class JobService:
    """Stage and transition jobs without owning transaction commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        job_type: str,
        payload: dict[str, object],
        idempotency_key: str,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> Job:
        """Stage one durable job in the caller's current transaction."""

        _validate_job_type(job_type)
        _validate_idempotency_key(idempotency_key)
        _validate_max_attempts(max_attempts)
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")

        job = Job(
            job_type=job_type,
            payload=dict(payload),
            idempotency_key=idempotency_key,
            status=JobStatus.PENDING.value,
            attempts=0,
            max_attempts=max_attempts,
            available_at=require_utc(available_at or utc_now()),
        )
        self._session.add(job)
        return job

    async def claim(
        self,
        *,
        worker: str,
        lease: timedelta,
        limit: int = 1,
        now: datetime | None = None,
    ) -> tuple[Job, ...]:
        """Claim an ordered batch using PostgreSQL skip-locked semantics."""

        _validate_worker(worker)
        _validate_lease(lease)
        _validate_limit(limit)
        claimed_at = require_utc(now or utc_now())
        statement = (
            sa.select(Job)
            .where(
                Job.status.in_((JobStatus.PENDING.value, JobStatus.RETRYING.value)),
                Job.available_at <= claimed_at,
                Job.attempts < Job.max_attempts,
            )
            .order_by(Job.available_at, Job.created_at, Job.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = tuple((await self._session.scalars(statement)).all())
        for job in jobs:
            job.status = JobStatus.RUNNING.value
            job.attempts += 1
            job.started_at = claimed_at
            job.finished_at = None
            job.lease_owner = worker
            job.lease_token = uuid4()
            job.lease_expires_at = claimed_at + lease
            job.last_error_code = None
        await self._session.flush()
        return jobs

    async def heartbeat(
        self,
        job_id: UUID,
        token: UUID,
        *,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> bool:
        """Extend a live lease only for the worker holding its token."""

        current_time = require_utc(now or utc_now())
        next_expiry = require_utc(lease_expires_at)
        if next_expiry <= current_time:
            raise ValueError("lease_expires_at must be in the future")
        result = await self._session.execute(
            sa.update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.lease_token == token,
                Job.lease_expires_at > current_time,
            )
            .values(lease_expires_at=next_expiry)
        )
        return cast(CursorResult[Any], result).rowcount > 0

    async def complete(
        self,
        job_id: UUID,
        token: UUID,
        *,
        result: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Complete a job only while the caller owns a live lease."""

        completed_at = require_utc(now or utc_now())
        query = await self._session.execute(
            sa.update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.lease_token == token,
                Job.lease_expires_at > completed_at,
            )
            .values(
                status=JobStatus.SUCCEEDED.value,
                result=None if result is None else dict(result),
                finished_at=completed_at,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                last_error_code=None,
            )
        )
        return cast(CursorResult[Any], query).rowcount > 0

    async def retry(
        self,
        job_id: UUID,
        token: UUID,
        *,
        error_code: str,
        jitter_seconds: float = 0,
        now: datetime | None = None,
    ) -> bool:
        """Release a live claim for bounded retry or retain dead-letter evidence."""

        _validate_error_code(error_code)
        _validate_jitter(jitter_seconds)
        failed_at = require_utc(now or utc_now())
        job = await self._session.get(Job, job_id, with_for_update=True)
        if (
            job is None
            or job.status != JobStatus.RUNNING.value
            or job.lease_token != token
            or job.lease_expires_at is None
            or require_utc(job.lease_expires_at) <= failed_at
        ):
            return False

        exhausted = job.attempts >= job.max_attempts
        job.status = JobStatus.FAILED.value if exhausted else JobStatus.RETRYING.value
        if exhausted:
            job.finished_at = failed_at
        else:
            delay = min(2**job.attempts, _MAX_RETRY_DELAY_SECONDS) + jitter_seconds
            job.available_at = failed_at + timedelta(seconds=delay)
            job.finished_at = None
        job.last_error_code = error_code
        _clear_lease(job)
        await self._session.flush()
        return True

    async def cancel(self, job_id: UUID, *, now: datetime | None = None) -> bool:
        """Cancel queued work without interrupting a running lease holder."""

        cancelled_at = require_utc(now or utc_now())
        result = await self._session.execute(
            sa.update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_((JobStatus.PENDING.value, JobStatus.RETRYING.value)),
            )
            .values(
                status=JobStatus.CANCELLED.value,
                finished_at=cancelled_at,
            )
        )
        return cast(CursorResult[Any], result).rowcount > 0

    async def recover_expired(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """Release expired claims after a worker crash or process restart."""

        _validate_limit(limit)
        recovered_at = require_utc(now or utc_now())
        statement = (
            sa.select(Job)
            .where(
                Job.status == JobStatus.RUNNING.value,
                Job.lease_expires_at <= recovered_at,
            )
            .order_by(Job.lease_expires_at, Job.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = tuple((await self._session.scalars(statement)).all())
        for job in jobs:
            exhausted = job.attempts >= job.max_attempts
            job.status = JobStatus.FAILED.value if exhausted else JobStatus.RETRYING.value
            job.available_at = recovered_at
            job.finished_at = recovered_at if exhausted else None
            job.last_error_code = "lease_expired"
            _clear_lease(job)
        await self._session.flush()
        return len(jobs)

    async def get_status(self, job_id: UUID) -> JobStatusView | None:
        """Return a polling-safe view without private job input or output data."""

        job = await self._session.get(Job, job_id)
        if job is None:
            return None
        return JobStatusView(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            available_at=job.available_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            last_error_code=job.last_error_code,
        )


def _clear_lease(job: Job) -> None:
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None


def _validate_job_type(value: object) -> None:
    if not isinstance(value, str) or len(value) > 100 or _JOB_TYPE_PATTERN.fullmatch(value) is None:
        raise ValueError("job_type must use 1-100 safe lowercase characters")


def _validate_idempotency_key(value: object) -> None:
    if not isinstance(value, str) or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("idempotency_key must use 1-255 safe characters")


def _validate_max_attempts(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_attempts must be an integer")
    if not 1 <= value <= 100:
        raise ValueError("max_attempts must be between 1 and 100")


def _validate_limit(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("limit must be an integer")
    if not 1 <= value <= _MAX_BATCH_SIZE:
        raise ValueError(f"limit must be between 1 and {_MAX_BATCH_SIZE}")


def _validate_worker(value: object) -> None:
    if not isinstance(value, str) or _WORKER_PATTERN.fullmatch(value) is None:
        raise ValueError("worker must use 1-100 safe characters")


def _validate_lease(value: object) -> None:
    if not isinstance(value, timedelta):
        raise TypeError("lease must be a timedelta")
    if value <= timedelta(0) or value > _MAX_LEASE:
        raise ValueError("lease must be greater than zero and at most 24 hours")


def _validate_error_code(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 100
        or _ERROR_CODE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("error_code must use lowercase snake case")


def _validate_jitter(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("jitter_seconds must be a number")
    if not 0 <= value <= 30:
        raise ValueError("jitter_seconds must be between 0 and 30")
