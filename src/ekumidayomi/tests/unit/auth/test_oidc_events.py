"""OIDC audit events expose provider labels without subjects or tokens."""

from uuid import uuid4

import pytest

from ekumidayomi.audit.model import ActorKind
from ekumidayomi.audit.service import AuditActor
from ekumidayomi.auth.events import (
    ExternalIdentityLinkedEvent,
    ExternalIdentityUnlinkedEvent,
    ExternalLoginFailedEvent,
    ExternalLoginSucceededEvent,
    ExternalReauthenticationSucceededEvent,
)


@pytest.mark.parametrize(
    ("event_type", "action", "metadata"),
    [
        (ExternalIdentityLinkedEvent, "identity.provider_linked", {"provider": "google"}),
        (ExternalIdentityUnlinkedEvent, "identity.provider_unlinked", {"provider": "google"}),
        (
            ExternalLoginSucceededEvent,
            "identity.login_succeeded",
            {"method": "oidc", "provider": "google"},
        ),
        (
            ExternalReauthenticationSucceededEvent,
            "identity.reauthentication_succeeded",
            {"method": "oidc", "provider": "google"},
        ),
    ],
)
def test_oidc_event_contracts_are_safe(
    event_type: type[
        ExternalIdentityLinkedEvent
        | ExternalIdentityUnlinkedEvent
        | ExternalLoginSucceededEvent
        | ExternalReauthenticationSucceededEvent
    ],
    action: str,
    metadata: dict[str, str],
) -> None:
    user_id = uuid4()
    event = event_type(
        actor=AuditActor(ActorKind.CUSTOMER, user_id),
        target_id=user_id,
        correlation_id="oidc-event",
        provider="google",
    )

    record = event.to_record()
    assert record.action == action
    assert record.target_id == user_id
    assert record.metadata == metadata
    assert "subject" not in record.metadata
    assert "token" not in record.metadata


def test_failed_handshake_event_contains_only_bounded_context() -> None:
    attempt_id = uuid4()
    event = ExternalLoginFailedEvent(
        actor=AuditActor(ActorKind.ANONYMOUS),
        target_id=attempt_id,
        correlation_id="oidc-denial",
        provider="google",
        intent="login",
    )

    record = event.to_record()
    assert record.action == "identity.external_login_failed"
    assert record.target_type == "external_login_attempt"
    assert record.target_id == attempt_id
    assert record.metadata == {"provider": "google", "intent": "login"}
