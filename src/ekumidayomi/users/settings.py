"""Validated users-domain configuration."""

from pydantic import BaseModel, ConfigDict, Field


class ProfileRateLimitSettings(BaseModel):
    """Authenticated profile mutation limits."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    profile_update_limit: int = Field(default=20, ge=1, le=1_000)
    address_mutation_limit: int = Field(default=60, ge=1, le=2_000)
    window_seconds: int = Field(default=600, ge=60, le=3_600)
