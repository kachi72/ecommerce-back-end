"""Provider-neutral email submission, with one recipient per delivery."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class OutgoingEmail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    delivery_id: UUID
    recipients: list[EmailStr] = Field(min_length=1, max_length=100, repr=False)
    subject: str = Field(min_length=1, max_length=200, repr=False)
    text_body: str = Field(min_length=1, max_length=131072, repr=False)
    html_body: str | None = Field(default=None, max_length=262144, repr=False)

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, values: list[EmailStr]) -> list[EmailStr]:
        normalized = [str(value).casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("recipients must be unique")
        return values

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if not value.strip() or any(character in value for character in "\r\n\x00"):
            raise ValueError("subject must be a non-empty single line")
        return value


class EmailSendResult(BaseModel):
    """Private submission outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    accepted_recipients: tuple[EmailStr, ...] = Field(repr=False)
    refused_recipients: tuple[EmailStr, ...] = Field(repr=False)
