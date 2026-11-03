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


@dataclass(frozen=True, kw_only=True)
class ExternalIdentityLinkedEvent(BaseAuditEvent):
    provider: str
    action = "identity.provider_linked"
    target_type = "user"
    allowed_metadata_keys = frozenset({"provider"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"provider": self.provider}


@dataclass(frozen=True, kw_only=True)
class ExternalIdentityUnlinkedEvent(BaseAuditEvent):
    provider: str
    action = "identity.provider_unlinked"
    target_type = "user"
    allowed_metadata_keys = frozenset({"provider"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"provider": self.provider}


@dataclass(frozen=True, kw_only=True)
class ExternalLoginSucceededEvent(BaseAuditEvent):
    provider: str
    action = "identity.login_succeeded"
    target_type = "user"
    allowed_metadata_keys = frozenset({"method", "provider"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"method": "oidc", "provider": self.provider}


@dataclass(frozen=True, kw_only=True)
class ExternalReauthenticationSucceededEvent(BaseAuditEvent):
    provider: str
    action = "identity.reauthentication_succeeded"
    target_type = "user"
    allowed_metadata_keys = frozenset({"method", "provider"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"method": "oidc", "provider": self.provider}


@dataclass(frozen=True, kw_only=True)
class ExternalLoginFailedEvent(BaseAuditEvent):
    provider: str
    intent: str
    action = "identity.external_login_failed"
    target_type = "external_login_attempt"
    outcome = AuditOutcome.DENIED
    allowed_metadata_keys = frozenset({"provider", "intent"})

    @property
    def metadata(self) -> Mapping[str, object]:
        return {"provider": self.provider, "intent": self.intent}
