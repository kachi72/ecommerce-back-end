"""Outbox contracts import without eagerly loading database infrastructure."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ekumidayomi.outbox.model import OutboxMessage, OutboxStatus
    from ekumidayomi.outbox.repository import OutboxRepository

__all__ = ["OutboxMessage", "OutboxRepository", "OutboxStatus"]


def __getattr__(name: str) -> object:
    """Load database-backed exports only when a caller requests one."""

    if name in {"OutboxMessage", "OutboxStatus"}:
        from ekumidayomi.outbox import model

        return getattr(model, name)
    if name == "OutboxRepository":
        from ekumidayomi.outbox.repository import OutboxRepository

        return OutboxRepository
    raise AttributeError(name)
