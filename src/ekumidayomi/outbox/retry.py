"""One retry owner with capped full jotter and bounded provider delay."""

import random

from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.settings import OutboxWorkerSettings


def next_delay(attempt: int, result: DeliveryOutcome, settings: OutboxWorkerSettings) -> float:
    if attempt < 1:
        raise ValueError("attempt starts at one")
    ceiling = min(
        settings.retry_max_seconds, settings.retry_base_seconds * 2 ** min(attempt - 1, 20)
    )
    return max(1.0, random.SystemRandom().uniform(0, ceiling), float(result.retry_after))


def next_status(result: DeliveryOutcome, *, attempt: int, max_attempts: int) -> str:
    if result.kind is OutcomeKind.ACCEPTED:
        return "published"
    if result.kind is OutcomeKind.SKIPPED:
        return "skipped"
    if result.kind is OutcomeKind.BLOCKED:
        return "blocked"
    if result.kind is OutcomeKind.PERMANENT:
        return "dead"
    if attempt >= max_attempts:
        return "uncertain" if result.kind is OutcomeKind.UNCERTAIN else "dead"
    return "failed"
