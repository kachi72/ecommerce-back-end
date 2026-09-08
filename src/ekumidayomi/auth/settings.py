"""Authentication configuration validated as part of the root settings object."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class AuthSettings(BaseModel):
    """Group auth policy without reading the environment or owning a settings cache."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    session_seconds: int = Field(default=604800, ge=300, le=2592000)
    cache_seconds: int = Field(default=60, ge=1, le=300)
    challenge_seconds: int = Field(default=600, ge=120, le=900)
    challenge_attempts: int = Field(default=5, ge=1, le=10)
    resend_seconds: int = Field(default=60, ge=30, le=300)
    recent_auth_seconds: int = Field(default=300, ge=60, le=900)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    challenge_keys: dict[str, SecretStr] = Field(default_factory=dict)
    active_challenge_key: str = "v1"

    @model_validator(mode="after")
    def validate_keys(self) -> Self:
        """Validate configured challenge keys and the existing exact-origin policy."""
        if self.challenge_keys:
            if self.active_challenge_key not in self.challenge_keys:
                raise ValueError("active challenge key is missing")
            if any(len(key.get_secret_value()) < 32 for key in self.challenge_keys.values()):
                raise ValueError("challenge keys require at least 32 random characters")
        if any(origin.endswith("/") or "*" in origin for origin in self.allowed_origins):
            raise ValueError("use exact origins without wildcards or trailing slashes")
        return self
