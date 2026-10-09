"""Internal delivery results; never expose provider bodies or credentials."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class OutcomeKind(StrEnum):
    ACCEPTED = "accepted"
    RETRY = "retry"
    PERMANENT = "permanent"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    kind: OutcomeKind
    code: str
    retry_after: int = 0
    receipts: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", OutcomeKind(self.kind))
        object.__setattr__(self, "receipts", MappingProxyType(dict(self.receipts)))
        if re.fullmatch(r"[a-z][a-z0-9_]{0,99}", self.code) is None:
            raise ValueError("use a safe delivery result code")
        if isinstance(self.retry_after, bool) or not 0 <= self.retry_after <= 3600:
            raise ValueError("retry_after must be between 0 and 3600")
