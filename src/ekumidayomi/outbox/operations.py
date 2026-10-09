"""Privileged local recovery operations; never an unauthenticated HTTP endpoint."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa

from ekumidayomi.audit.events import BaseAuditEvent
from ekumidayomi.audit.model import ActorKind
from ekumidayomi.audit.service import AuditActor, record_event
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.outbox.leased_repository import LeasedOutboxRepository
from ekumidayomi.outbox.model import OutboxMessage, WorkerControl
from ekumidayomi.outbox.outcomes import DeliveryOutcome
from ekumidayomi.outbox.ports import ExternalOutboxHandler

MAX_REPLAY_ATTEMPTS: Final[int] = 100


class RecoveryReason(StrEnum):
    CONFIGURATION_FIXED = "configuration_fixed"
    TRANSIENT_RESOLVED = "transient_resolved"


@dataclass(frozen=True, kw_only=True)
class OutboxReplayRequestedEvent(BaseAuditEvent):
    reason: RecoveryReason
    action = "outbox.replay_requested"
    target_type = "outbox_message"
    allowed_metadata_keys = frozenset({"reason"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"reason": RecoveryReason(self.reason).value}


@dataclass(frozen=True, kw_only=True)
class WorkerResumedEvent(BaseAuditEvent):
    action = "outbox.worker_resumed"
    target_type = "worker_operation"

    @property
    def metadata(self) -> Mapping[str, object]:
        return {}


async def replay(
    uow: UnitOfWork,
    message_id: UUID,
    reason: RecoveryReason,
    handlers: Mapping[str, ExternalOutboxHandler],
) -> None:
    row = await uow.session.get(OutboxMessage, message_id, with_for_update=True)
    now = await LeasedOutboxRepository(uow.session).now()
    if row is None or row.event_type not in handlers or row.status not in ("dead", "blocked"):
        raise ValueError("message is not eligible for replay")
    if row.deadline_at is None or row.deadline_at <= now or row.attempts >= MAX_REPLAY_ATTEMPTS:
        raise ValueError("delivery window or lifetime attempt budget exhausted")
    prepared = await handlers[row.event_type].prepare(uow, row.to_event())
    if isinstance(prepared, DeliveryOutcome) or prepared.expires_at <= now:
        raise ValueError("domain no longer permits delivery")
    if row.delivery_fingerprint is not None and row.delivery_fingerprint != prepared.fingerprint:
        raise ValueError("restore original delivery content before replay")
    row.retry_budget = min(MAX_REPLAY_ATTEMPTS, row.attempts + 3)
    row.status = "pending"
    row.available_at = now
    row.claim_token = None
    row.lease_expires_at = None
    record_event(
        uow,
        OutboxReplayRequestedEvent(
            actor=AuditActor(ActorKind.SYSTEM),
            target_id=row.id,
            correlation_id=str(uuid4()),
            reason=reason,
        ),
    )


async def resume(uow: UnitOfWork, group: str) -> None:
    control = await uow.session.get(WorkerControl, group, with_for_update=True)
    if control is None or not control.paused:
        raise ValueError("worker group is not paused")
    control.paused = False
    record_event(
        uow,
        WorkerResumedEvent(
            actor=AuditActor(ActorKind.SYSTEM), target_id=uuid4(), correlation_id=str(uuid4())
        ),
    )


async def health(uow: UnitOfWork, group: str, event_types: tuple[str, ...]) -> dict[str, object]:
    now = await LeasedOutboxRepository(uow.session).now()
    control = await uow.session.get(WorkerControl, group)
    counts = (
        await uow.session.execute(
            sa.select(OutboxMessage.status, sa.func.count())
            .where(OutboxMessage.event_type.in_(event_types))
            .group_by(OutboxMessage.status)
        )
    ).all()
    oldest = await uow.session.scalar(
        sa.select(sa.func.min(OutboxMessage.available_at)).where(
            OutboxMessage.event_type.in_(event_types),
            OutboxMessage.status.in_(("pending", "failed")),
            OutboxMessage.available_at <= now,
        )
    )
    stale = await uow.session.scalar(
        sa.select(sa.func.count())
        .select_from(OutboxMessage)
        .where(
            OutboxMessage.event_type.in_(event_types),
            OutboxMessage.status == "processing",
            OutboxMessage.lease_expires_at <= now,
        )
    )
    age = int((now - oldest).total_seconds()) if oldest is not None else 0
    return {
        "healthy": bool(
            control is not None
            and not control.paused
            and control.heartbeat_at > now - timedelta(seconds=180)
            and age < 60
            and not stale
        ),
        "paused": control.paused if control else None,
        "oldest_due_seconds": age,
        "expired_claims": int(stale or 0),
        "counts": {str(status): int(count) for status, count in counts},
    }
