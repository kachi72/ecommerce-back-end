"""Auth eligibility, message content, and external delivery delegation."""

from collections.abc import Mapping
from uuid import UUID

from ekumidayomi.auth.challenge_model import ChallengePurpose, EmailChallenge
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.email.ports import EmailSender, EmailSubmission
from ekumidayomi.email.schemas import OutgoingEmail
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.leased_repository import LeasedOutboxRepository
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.ports import PreparedDelivery

CHALLENGE_EMAIL_EVENT = "email_challenge_requested"


PreparedOutcome = PreparedDelivery | DeliveryOutcome


class AuthChallengeEmailHandler:
    """External handler registered only with LeasedOutboxWorker."""

    def __init__(self, sender: EmailSender, settings: AuthSettings) -> None:
        self.sender = sender
        self.settings = settings

    def _build_email(self, challenge: EmailChallenge, *, delivery_id: UUID) -> OutgoingEmail:
        """Build auth-owned content; the sender performs the actual provider submission."""
        purpose = ChallengePurpose(challenge.purpose)
        subjects = {
            ChallengePurpose.REGISTRATION: "Ẹkúmidáyọ̀mí verification code",
            ChallengePurpose.PASSWORD_RESET: "Ẹkúmidáyọ̀mí password reset code",
        }
        code = derive_code(challenge, self.settings)
        return OutgoingEmail(
            delivery_id=delivery_id,
            recipients=[challenge.email],
            subject=subjects[purpose],
            text_body=f"Your {purpose.value.replace('_', ' ')} code is {code}.\n"
            "It expires shortly. If you did not request it, ignore this message.",
        )

    async def prepare(self, uow: UnitOfWork, event: DomainEvent) -> PreparedOutcome:
        try:
            raw_id = event.payload["challenge_id"]
            if not isinstance(raw_id, str):
                raise ValueError("invalid challenge")
            challenge_id = UUID(raw_id)
            if (
                event.event_type != CHALLENGE_EMAIL_EVENT
                or event.aggregate_type != "email_challenge"
                or event.aggregate_id != challenge_id
            ):
                raise ValueError("invalid event")
        except (KeyError, TypeError, ValueError):
            return DeliveryOutcome(OutcomeKind.PERMANENT, "invalid_challenge_event")

        row = await uow.session.get(EmailChallenge, challenge_id)
        now = await LeasedOutboxRepository(uow.session).now()
        if row is None or row.consumed_at is not None or row.expires_at <= now:
            return DeliveryOutcome(OutcomeKind.SKIPPED, "challenge_unavailable")
        try:
            ChallengePurpose(row.purpose)
        except ValueError:
            return DeliveryOutcome(OutcomeKind.PERMANENT, "invalid_challenge_purpose")
        if row.key_version not in self.settings.challenge_keys:
            return DeliveryOutcome(OutcomeKind.BLOCKED, "challenge_key_missing")

        outgoing = self._build_email(row, delivery_id=event.event_id)
        submission = self.sender.prepare(outgoing)
        return PreparedDelivery(submission, submission.fingerprint, row.expires_at)

    async def deliver(
        self, prepared: PreparedDelivery, completed: Mapping[str, str]
    ) -> DeliveryOutcome:
        if not isinstance(prepared.payload, EmailSubmission):
            return DeliveryOutcome(OutcomeKind.PERMANENT, "invalid_prepared_delivery")
        return await self.sender.send(prepared.payload, completed)
