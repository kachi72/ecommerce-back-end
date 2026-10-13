"""Public audit projections omit sensitive metadata."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ekumidayomi.api.schemas import UTCDateTime


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_kind: str
    actor_id: UUID | None
    action: str
    target_type: str
    target_id: UUID
    outcome: str
    occurred_at: UTCDateTime
    correlation_id: str
