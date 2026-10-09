from typing import Any

import pytest
from pydantic import ValidationError

from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.retry import next_delay, next_status
from ekumidayomi.outbox.settings import OutboxWorkerSettings


@pytest.mark.parametrize(
    "kind,status",
    [
        (OutcomeKind.ACCEPTED, "published"),
        (OutcomeKind.SKIPPED, "skipped"),
        (OutcomeKind.PERMANENT, "dead"),
        (OutcomeKind.BLOCKED, "blocked"),
        (OutcomeKind.RETRY, "failed"),
        (OutcomeKind.UNCERTAIN, "failed"),
    ],
)
def test_classification(kind: Any, status: Any) -> None:
    assert next_status(DeliveryOutcome(kind, "test"), attempt=1, max_attempts=5) == status


def test_exhaustion_preserves_uncertainty() -> None:
    assert (
        next_status(DeliveryOutcome(OutcomeKind.UNCERTAIN, "test"), attempt=5, max_attempts=5)
        == "uncertain"
    )
    assert (
        next_status(DeliveryOutcome(OutcomeKind.RETRY, "test"), attempt=5, max_attempts=5) == "dead"
    )


def test_backoff_honors_provider_delay_and_cap() -> None:
    settings = OutboxWorkerSettings()
    for _ in range(30):
        assert 1 <= next_delay(5, DeliveryOutcome(OutcomeKind.RETRY, "busy"), settings) <= 300
        assert next_delay(1, DeliveryOutcome(OutcomeKind.RETRY, "busy", 120), settings) == 120


@pytest.mark.parametrize(
    "values",
    [
        {"lease_seconds": 30},
        {"max_age_seconds": 86400},
        {"retry_base_seconds": 100, "retry_max_seconds": 50},
    ],
)
def test_invalid_windows(values: Any) -> None:
    with pytest.raises(ValidationError):
        OutboxWorkerSettings(**values)
