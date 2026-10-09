"""Outbox only events."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from ekumidayomi.audit.events import BaseAuditEvent


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
