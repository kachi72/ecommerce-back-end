"""Short, fenced PostgreSQL claim transactions; no external I/O."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.model import OutboxMessage, WorkerControl
from ekumidayomi.outbox.outcomes import DeliveryOutcome
from ekumidayomi.outbox.retry import next_status
from ekumidayomi.outbox.settings import OutboxWorkerSettings


@dataclass(frozen=True, slots=True)
class Claim:
    message_id: UUID
    token: UUID
    event: DomainEvent | None
    attempts: int
    retry_budget: int
    deadline: datetime
    receipts: dict[str, str] = field(repr=False)


class LeasedOutboxRepository:
    def __init__(self, session: AsyncSession, worker_group: str = "auth_email") -> None:
        self.session = session
        self.worker_group = worker_group

    async def now(self) -> datetime:
        value = await self.session.scalar(sa.select(sa.func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("database clock unavailable")
        return value

    async def claim(
        self, event_types: tuple[str, ...], settings: OutboxWorkerSettings
    ) -> Claim | None:
        if not event_types or any(
            re.fullmatch(r"[a-z][a-z0-9_]{0,99}", name) is None for name in event_types
        ):
            raise ValueError("register safe event types")
        now = await self.now()
        await self.session.execute(
            insert(WorkerControl)
            .values(worker_group=self.worker_group, paused=False, heartbeat_at=now)
            .on_conflict_do_nothing()
        )
        control = await self.session.get(WorkerControl, self.worker_group, with_for_update=True)
        if control is None:
            raise RuntimeError("worker control missing")
        control.heartbeat_at = now
        if control.paused:
            return None
        expired = list(
            await self.session.scalars(
                sa.select(OutboxMessage)
                .where(
                    OutboxMessage.event_type.in_(event_types),
                    sa.or_(
                        sa.and_(
                            OutboxMessage.status == "processing",
                            OutboxMessage.lease_expires_at <= now,
                        ),
                        OutboxMessage.status.in_(("pending", "failed")),
                    ),
                    sa.or_(
                        OutboxMessage.attempts >= OutboxMessage.retry_budget,
                        OutboxMessage.deadline_at <= now,
                    ),
                )
                .order_by(OutboxMessage.id)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        for expired_row in expired:
            expired_row.status = "uncertain" if expired_row.delivery_fingerprint else "dead"
            expired_row.last_error_code = "delivery_budget_expired"
            expired_row.claim_token = None
            expired_row.lease_expires_at = None
        await self.session.flush()
        earlier = aliased(OutboxMessage)
        blocked = sa.exists(
            sa.select(earlier.id).where(
                earlier.aggregate_type == OutboxMessage.aggregate_type,
                earlier.aggregate_id == OutboxMessage.aggregate_id,
                earlier.aggregate_version < OutboxMessage.aggregate_version,
                earlier.status.not_in(("published", "skipped")),
            )
        )
        row = await self.session.scalar(
            sa.select(OutboxMessage)
            .where(
                OutboxMessage.event_type.in_(event_types),
                sa.or_(
                    sa.and_(
                        OutboxMessage.status.in_(("pending", "failed")),
                        OutboxMessage.available_at <= now,
                    ),
                    sa.and_(
                        OutboxMessage.status == "processing", OutboxMessage.lease_expires_at <= now
                    ),
                ),
                OutboxMessage.attempts < OutboxMessage.retry_budget,
                ~blocked,
            )
            .order_by(OutboxMessage.available_at, OutboxMessage.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        deadline = min(
            row.deadline_at or now + timedelta(seconds=settings.max_age_seconds),
            row.occurred_at + timedelta(seconds=settings.max_age_seconds),
        )
        row.deadline_at = deadline
        if deadline is None:
            raise RuntimeError("claimed delivery has no deadline")

        if deadline <= now:
            row.status = "uncertain" if row.delivery_fingerprint else "dead"
            row.last_error_code = "delivery_too_old"
            await self.session.flush()
            return None
        if row.attempts == 0:
            row.retry_budget = settings.max_attempts
        row.status = "processing"
        row.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
        row.claimed_at = now
        row.attempts += 1
        token = uuid4()
        row.claim_token = token
        try:
            event = row.to_event()
        except (TypeError, ValueError):
            event = None
        await self.session.flush()
        return Claim(
            row.id,
            token,
            event,
            row.attempts,
            row.retry_budget,
            deadline,
            dict(row.delivery_receipts),
        )

    async def owned(self, claim: Claim) -> OutboxMessage | None:
        rows = await self.session.scalars(
            sa.select(OutboxMessage)
            .where(
                OutboxMessage.id == claim.message_id,
                OutboxMessage.claim_token == claim.token,
                OutboxMessage.status == "processing",
                OutboxMessage.lease_expires_at > sa.func.clock_timestamp(),
            )
            .with_for_update()
        )
        return rows.one_or_none()

    async def bind(self, claim: Claim, fingerprint: str, expires_at: datetime) -> bool:
        if re.fullmatch(r"[a-f0-9]{64}", fingerprint) is None:
            raise ValueError("invalid delivery fingerprint")
        await self.session.get(WorkerControl, self.worker_group, with_for_update=True)
        row = await self.owned(claim)
        if row is None:
            return False
        now = await self.now()
        if row.delivery_fingerprint is not None and row.delivery_fingerprint != fingerprint:
            row.status = "blocked"
            row.last_error_code = "delivery_content_changed"
            control = await self.session.get(WorkerControl, self.worker_group)
            if control is not None:
                control.paused = True
            row.claim_token = None
            row.lease_expires_at = None
            return False
        deadline = min(claim.deadline, expires_at)
        row.deadline_at = deadline
        if deadline <= now:
            row.status = "uncertain" if row.delivery_fingerprint else "skipped"
            row.last_error_code = "delivery_expired"
            row.claim_token = None
            row.lease_expires_at = None
            return False
        row.delivery_fingerprint = fingerprint
        await self.session.flush()
        return True

    async def finish(self, claim: Claim, result: DeliveryOutcome, delay: float) -> bool:
        await self.session.get(WorkerControl, self.worker_group, with_for_update=True)
        row = await self.owned(claim)
        if row is None:
            return False
        now = await self.now()
        row.delivery_receipts = {**row.delivery_receipts, **result.receipts}
        row.status = next_status(result, attempt=row.attempts, max_attempts=row.retry_budget)
        row.available_at = now + timedelta(seconds=delay)
        row.last_error_code = result.code
        if row.status == "failed" and row.available_at >= (row.deadline_at or claim.deadline):
            row.status = "uncertain" if row.delivery_fingerprint else "dead"
        if row.status == "blocked":
            control = await self.session.get(WorkerControl, self.worker_group)
            if control is not None:
                control.paused = True
        row.published_at = now if row.status == "published" else None
        row.claim_token = None
        row.lease_expires_at = None
        row.claimed_at = None
        await self.session.flush()
        return True
