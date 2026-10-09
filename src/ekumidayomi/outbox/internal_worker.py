"""Database-only outbox processing; never use this runner for external I/O."""

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import timedelta

from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.ports import InternalOutboxHandler
from ekumidayomi.outbox.repository import OutboxRepository
from ekumidayomi.outbox.retry import next_delay
from ekumidayomi.outbox.settings import OutboxWorkerSettings

logger = logging.getLogger(__name__)
type UnitOfWorkFactory = Callable[[], AbstractAsyncContextManager[UnitOfWork]]
_EVENT_NAME = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")


class InternalOutboxWorker:
    """Claim ordinary outbox rows and run database-only handlers atomatically."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        handlers: Mapping[str, InternalOutboxHandler],
        settings: OutboxWorkerSettings,
    ) -> None:
        if not handlers or any(_EVENT_NAME.fullmatch(name) is None for name in handlers):
            raise ValueError("register at least one handler with a safe event name")
        self._factory = uow_factory
        self._handlers = dict(handlers)
        self._event_types = tuple(self._handlers)
        self._settings = settings.model_copy(deep=True)

    async def process_one(self) -> bool:
        """Run one internal handler and transition its ordinary claim."""
        async with self._factory() as uow:
            repository = OutboxRepository(uow.session, max_attempts=self._settings.max_attempts)
            messages = await repository.claim_batch(limit=1, event_types=self._event_types)
            if not messages:
                return False
            row = messages[0]
            try:
                async with uow.session.begin_nested():
                    await self._handlers[row.event_type].handle(uow, row.to_event())
            except Exception:
                logger.error(
                    "internal_outbox_handler_failed",
                    extra={"event_id": str(row.event_id), "event_type": row.event_type},
                )
                retry_at = utc_now() + timedelta(
                    seconds=next_delay(
                        row.attempts,
                        DeliveryOutcome(OutcomeKind.RETRY, "internal_handler_failed"),
                        self._settings,
                    )
                )
                changed = await repository.mark_failed(
                    row.id, error_code="internal_handler_failed", available_at=retry_at
                )
            else:
                changed = await repository.mark_published(row.id)
            if not changed:
                raise RuntimeError("ordinary outbox transition was not applied")
            await uow.commit()
        return True

    async def run(self, *, once: bool = False, stop: asyncio.Event | None = None) -> None:
        """Poll until stopped; a process owns only its registered internal event types."""
        stopping = stop if stop is not None else asyncio.Event()
        while not stopping.is_set():
            handled = await self.process_one()
            if once:
                return None
            if not handled:
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=self._settings.poll_seconds)
                except TimeoutError:
                    pass
