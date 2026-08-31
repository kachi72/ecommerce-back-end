"""Transactional outbox persistence and claiming operations."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ekumidayomi.core.types import require_utc, utc_now
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.model import OutboxMessage, OutboxStatus

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class OutboxRepository:
    """Write and transition outbox rows without owning transaction commits."""

    def __init__(self, session: AsyncSession, *, max_attempts: int = 10) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise TypeError("max_attempts must be an integer")
        if not 1 <= max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        self._session = session
        self._max_attempts = max_attempts

    def add(
        self,
        event: DomainEvent,
        *,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
    ) -> OutboxMessage:
        """Stage an event intent in the caller's current transaction."""

        resolved_key = f"event:{event.event_id}" if idempotency_key is None else idempotency_key
        _validate_idempotency_key(resolved_key)
        resolved_available_at = require_utc(available_at or event.occurred_at)
        message = OutboxMessage(
            event_id=event.event_id,
            idempotency_key=resolved_key,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            aggregate_version=event.aggregate_version,
            occurred_at=event.occurred_at,
            payload=event.payload_dict(),
            status=OutboxStatus.PENDING,
            attempts=0,
            available_at=resolved_available_at,
        )
        self._session.add(message)
        return message

    async def claim_batch(
        self,
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> tuple[OutboxMessage, ...]:
        """Lock and claim one bounded, aggregate-ordered delivery batch."""

        _validate_limit(limit)
        claimed_at = require_utc(now or utc_now())
        earlier = aliased(OutboxMessage)
        earlier_unpublished = exists(
            select(earlier.id).where(
                earlier.aggregate_type == OutboxMessage.aggregate_type,
                earlier.aggregate_id == OutboxMessage.aggregate_id,
                earlier.aggregate_version < OutboxMessage.aggregate_version,
                earlier.status != OutboxStatus.PUBLISHED,
            )
        )
        statement = (
            select(OutboxMessage)
            .where(
                OutboxMessage.status.in_((OutboxStatus.PENDING, OutboxStatus.FAILED)),
                OutboxMessage.attempts < self._max_attempts,
                OutboxMessage.available_at <= claimed_at,
                ~earlier_unpublished,
            )
            .order_by(
                OutboxMessage.available_at,
                OutboxMessage.occurred_at,
                OutboxMessage.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        messages = tuple((await self._session.scalars(statement)).all())
        for message in messages:
            message.status = OutboxStatus.PROCESSING
            message.attempts += 1
            message.claimed_at = claimed_at
            message.published_at = None
            message.last_error_code = None
        await self._session.flush()
        return messages

    async def mark_published(
        self,
        message_id: UUID,
        *,
        published_at: datetime | None = None,
    ) -> bool:
        """Idempotently record successful delivery of a claimed message."""

        message = await self._session.get(OutboxMessage, message_id, with_for_update=True)
        if message is None or message.status is OutboxStatus.PUBLISHED:
            return False
        if message.status is not OutboxStatus.PROCESSING:
            return False
        message.status = OutboxStatus.PUBLISHED
        message.claimed_at = None
        message.published_at = require_utc(published_at or utc_now())
        message.last_error_code = None
        await self._session.flush()
        return True

    async def mark_failed(
        self,
        message_id: UUID,
        *,
        error_code: str,
        available_at: datetime,
    ) -> bool:
        """Idempotently retain safe failure evidence for a later retry."""

        _validate_error_code(error_code)
        next_available_at = require_utc(available_at)
        message = await self._session.get(OutboxMessage, message_id, with_for_update=True)
        if message is None or message.status is not OutboxStatus.PROCESSING:
            return False
        message.status = OutboxStatus.FAILED
        message.claimed_at = None
        message.published_at = None
        message.last_error_code = error_code
        message.available_at = next_available_at
        await self._session.flush()
        return True

    async def recover_stale_claims(
        self,
        *,
        stale_before: datetime,
        available_at: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """Release stale processing claims without deleting delivery evidence."""

        _validate_limit(limit)
        resolved_stale_before = require_utc(stale_before)
        resolved_available_at = require_utc(available_at or utc_now())
        statement = (
            select(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxStatus.PROCESSING,
                OutboxMessage.claimed_at <= resolved_stale_before,
            )
            .order_by(OutboxMessage.claimed_at, OutboxMessage.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        messages = tuple((await self._session.scalars(statement)).all())
        for message in messages:
            message.status = OutboxStatus.FAILED
            message.claimed_at = None
            message.published_at = None
            message.last_error_code = "claim_expired"
            message.available_at = resolved_available_at
        await self._session.flush()
        return len(messages)


def _validate_idempotency_key(value: object) -> None:
    if not isinstance(value, str) or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("idempotency_key must use 1-255 safe characters")


def _validate_error_code(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 100
        or _ERROR_CODE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("error_code must use lowercase snake case")


def _validate_limit(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("limit must be an integer")
    if not 1 <= value <= 100:
        raise ValueError("limit must be between 1 and 100")
