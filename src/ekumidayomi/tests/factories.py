"""Deterministic values shared by tests."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DeterministicValues:
    """Stable identifiers and timestamps for repeatable assertions."""

    identifier: UUID
    now: datetime


def build_deterministic_values() -> DeterministicValues:
    """Build the canonical stable values used by test fixtures."""
    return DeterministicValues(
        identifier=UUID("00000000-0000-4000-8000-000000000001"),
        now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
