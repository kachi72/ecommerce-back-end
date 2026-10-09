"""Domain-independent delivery interface."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from ekumidayomi.email.schemas import OutgoingEmail
from ekumidayomi.outbox.outcomes import DeliveryOutcome


@dataclass(frozen=True, slots=True)
class EmailRequest:
    key: str
    body: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class EmailSubmission:
    requests: tuple[EmailRequest, ...] = field(repr=False)
    fingerprint: str = field(repr=False)


class EmailSender(Protocol):
    @abstractmethod
    def prepare(self, message: OutgoingEmail) -> EmailSubmission:
        """Freeze private transport content and stable per-recipient identities."""
        raise NotImplementedError

    @abstractmethod
    async def send(
        self, submission: EmailSubmission, completed: Mapping[str, str]
    ) -> DeliveryOutcome:
        """Submit only unresolved recipients; return safe provider receipts."""
        raise NotImplementedError
