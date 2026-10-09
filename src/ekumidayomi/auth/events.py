"""Authentication-owned audit classes"""

from collections.abc import Mapping
from dataclasses import dataclass

from ekumidayomi.audit.events import BaseAuditEvent
from ekumidayomi.audit.model import AuditOutcome
from ekumidayomi.auth.challenge_model import ChallengePurpose


@dataclass(frozen=True, kw_only=True)
class RegistrationInitiatedEvent(BaseAuditEvent):
    action = "auth.registration_requested"
    target_type = "registration_attempt"

    @property
    def metadata(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, kw_only=True)
class EmailChallengeIssuedEvent(BaseAuditEvent):
    purpose: ChallengePurpose
    is_resend: bool = False
    action = "auth.challenge_issued"
    target_type = "email_challenge"
    allowed_metadata_keys = frozenset({"purpose", "is_resend"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"purpose": ChallengePurpose(self.purpose).value, "is_resend": self.is_resend}


@dataclass(frozen=True, kw_only=True)
class EmailChallengeVerificationFailedEvent(BaseAuditEvent):
    purpose: ChallengePurpose
    action = "auth.challenge_verification_failed"
    target_type = "email_challenge"
    outcome = AuditOutcome.DENIED
    allowed_metadata_keys = frozenset({"purpose"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"purpose": ChallengePurpose(self.purpose).value}


@dataclass(frozen=True, kw_only=True)
class RegistrationCompletedEvent(BaseAuditEvent):
    action = "auth.registration_completed"
    target_type = "user"

    @property
    def metadata(self) -> Mapping[str, object]:
        return {}
