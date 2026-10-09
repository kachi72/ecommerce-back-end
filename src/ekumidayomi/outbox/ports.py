"""Separate contracts for internal event handling and external delivery."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.outcomes import DeliveryOutcome


@dataclass(frozen=True, slots=True)
class PreparedDelivery:
    payload: object = field(repr=False)
    fingerprint: str = field(repr=False)
    expires_at: datetime


class InternalOutboxHandler(Protocol):
    """Handle a database-only event inside the worker's unit of work."""

    @abstractmethod
    async def handle(self, uow: UnitOfWork, event: DomainEvent) -> None:
        """Apply internal state changes without external I/O."""
        raise NotImplementedError


class ExternalOutboxHandler(Protocol):
    @abstractmethod
    async def prepare(
        self, uow: UnitOfWork, event: DomainEvent
    ) -> PreparedDelivery | DeliveryOutcome:
        """Read eligibility and materialize detached work; no commits or external IO."""
        raise NotImplementedError

    @abstractmethod
    async def deliver(
        self, prepared: PreparedDelivery, completed: Mapping[str, str]
    ) -> DeliveryOutcome:
        """Perform bounded external IO with no ORM objects or database session."""
        raise NotImplementedError
