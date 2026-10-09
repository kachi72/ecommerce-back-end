"""Resend HTTP settings, loaded through the central application settings."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class ResendSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True, hide_input_in_errors=True)

    api_key: SecretStr = Field(repr=False, min_length=1)
    sender: EmailStr = Field(repr=False)
    fingerprint_key: SecretStr = Field(repr=False, min_length=32)
    timeout_seconds: float = Field(default=10, gt=0, le=20, allow_inf_nan=False)
