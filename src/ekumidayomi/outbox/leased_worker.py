"""Leased delivery processing for external I/O; no transaction crosses the provider call."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager

from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.outbox.leased_repository import Claim, LeasedOutboxRepository
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.ports import ExternalOutboxHandler
from ekumidayomi.outbox.retry import next_delay
from ekumidayomi.outbox.settings import OutboxWorkerSettings

logger = logging.getLogger(__name__)
type UnitOfWorkFactory = Callable[[], AbstractAsyncContextManager[UnitOfWork]]


class LeasedOutboxWorker:
    """Claim, prepare, submit and finalize an external delivery with a lease fence."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        handlers: Mapping[str, ExternalOutboxHandler],
        settings: OutboxWorkerSettings,
        worker_group: str = "auth_email",
    ) -> None:
        if not handlers:
            raise ValueError("register at least one external handler")
        self._factory = uow_factory
        self._handlers = dict(handlers)
        self._settings = settings.model_copy(deep=True)
        self._group = worker_group

    async def _finalize(self, claim: Claim, result: DeliveryOutcome) -> None:
        async with self._factory() as uow:
            changed = await LeasedOutboxRepository(uow.session, self._group).finish(
                claim, result, next_delay(claim.attempts, result, self._settings)
            )
            await uow.commit()
        logger.info(
            "external_delivery_result",
            extra={
                "message_id": str(claim.message_id),
                "result_code": result.code,
                "outcome": result.kind.value,
                "claim_applied": changed,
            },
        )

    async def process_one(self) -> bool:
        """Claim external work, release the connection, then call the provider."""
        async with self._factory() as uow:
            claim = await LeasedOutboxRepository(uow.session, self._group).claim(
                tuple(self._handlers), self._settings
            )
            await uow.commit()
        if claim is None:
            return False
        if claim.event is None:
            await self._finalize(claim, DeliveryOutcome(OutcomeKind.PERMANENT, "invalid_event"))
            return True

        handler = self._handlers[claim.event.event_type]
        try:
            async with asyncio.timeout(self._settings.prepare_seconds):
                async with self._factory() as uow:
                    prepared = await handler.prepare(uow, claim.event)
        except TimeoutError:
            await self._finalize(claim, DeliveryOutcome(OutcomeKind.RETRY, "preparation_timeout"))
            return True

        if isinstance(prepared, DeliveryOutcome):
            await self._finalize(claim, prepared)
            return True

        async with self._factory() as uow:
            allowed = await LeasedOutboxRepository(uow.session, self._group).bind(
                claim, prepared.fingerprint, prepared.expires_at
            )
            await uow.commit()
        if not allowed:
            return True
        if utc_now() >= min(prepared.expires_at, claim.deadline):
            await self._finalize(claim, DeliveryOutcome(OutcomeKind.SKIPPED, "no_longer_eligible"))
            return True

        try:
            async with asyncio.timeout(self._settings.send_seconds):
                result = await handler.deliver(prepared, claim.receipts)
        except TimeoutError:
            result = DeliveryOutcome(OutcomeKind.UNCERTAIN, "submission_timeout")
        except Exception:
            result = DeliveryOutcome(OutcomeKind.BLOCKED, "handler_failure")
        await self._finalize(claim, result)
        return True

    async def run(self, *, once: bool = False, stop: asyncio.Event | None = None) -> None:
        """Poll until stopped; in-flight external work finishes before shutdown."""
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
