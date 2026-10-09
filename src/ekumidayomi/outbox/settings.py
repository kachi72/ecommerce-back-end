"""Shared runner policy, composed into the root settings object."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutboxWorkerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    max_attempts: int = Field(default=5, ge=1, le=100)
    poll_seconds: float = Field(default=1, ge=0.1, le=60, allow_inf_nan=False)
    retry_base_seconds: int = Field(default=30, ge=1, le=300)
    retry_max_seconds: int = Field(default=300, ge=1, le=3600)
    prepare_seconds: int = Field(default=10, ge=1, le=30)
    send_seconds: int = Field(default=20, ge=1, le=60)
    lease_seconds: int = Field(default=120, ge=30, le=300)
    max_age_seconds: int = Field(default=3600, ge=60, le=82800)

    @model_validator(mode="after")
    def validate_retry_window(self) -> Self:
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("retry_max_seconds must be at least retry_base_seconds")
        if self.lease_seconds <= self.prepare_seconds + self.send_seconds + 30:
            raise ValueError("lease must cover bounded work and finalization margin")
        return self
