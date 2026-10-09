from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Protocol
from uuid import UUID

from ekumidayomi.audit.model import AuditOutcome
from ekumidayomi.audit.service import AuditActor
from ekumidayomi.core.types import utc_now


@dataclass(frozen=True, slots=True)
class AuditData:
    actor: AuditActor
    action: str
    target_type: str
    target_id: UUID
    outcome: AuditOutcome
    metadata: Mapping[str, object]
    allowed_metadata_keys: frozenset[str]
    correlation_id: str
    occurred_at: datetime


class AuditEvent(Protocol):
    @abstractmethod
    def to_record(self) -> AuditData:
        """Return typed evidence; persistence still validates and sanitizes."""
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class BaseAuditEvent(ABC):
    actor: AuditActor
    target_id: UUID
    correlation_id: str
    action: ClassVar[str]
    target_type: ClassVar[str]
    outcome: ClassVar[AuditOutcome] = AuditOutcome.SUCCEEDED
    allowed_metadata_keys: ClassVar[frozenset[str]] = frozenset()

    @property
    @abstractmethod
    def metadata(self) -> Mapping[str, object]:
        """Expose only the concrete event's declared metadata."""
        raise NotImplementedError

    def to_record(self) -> AuditData:
        """Expose only the concrete event's declared metadata."""
        return AuditData(
            self.actor,
            self.action,
            self.target_type,
            self.target_id,
            self.outcome,
            self.metadata,
            self.allowed_metadata_keys,
            self.correlation_id,
            utc_now(),
        )
