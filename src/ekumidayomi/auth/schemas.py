"""Authentication API request and response contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)


class ChallengeAccepted(BaseModel):
    message: str = "If eligible, verification instructions will be sent."
    challenge_id: UUID


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")
    password: SecretStr = Field(min_length=15, max_length=128)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=128)
