from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class ProviderName(StrEnum):
    """Options for external identity provider."""

    GOOGLE = "google"
    YAHOO = "yahoo"


ISSUERS: dict[ProviderName, str] = {
    ProviderName.GOOGLE: "https://accounts.google.com",
    ProviderName.YAHOO: "https://api.login.yahoo.com",
}


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    enabled: bool = False
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    redirect_uri: str = ""
    pkce_verified: bool = False

    @model_validator(mode="after")
    def validate_enabled(self) -> Self:
        if self.enabled:
            uri = urlsplit(self.redirect_uri)
            if (
                not self.client_id
                or not self.client_secret.get_secret_value()
                or uri.scheme != "https"
                or not uri.hostname
                or uri.query
                or uri.fragment
                or uri.username
                or uri.password
            ):
                raise ValueError("enabled providers require credentials and exact HTTPS callback")
        return self


class OidcSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    google: ProviderConfig = Field(default_factory=ProviderConfig)
    yahoo: ProviderConfig = Field(default_factory=ProviderConfig)
    attempt_seconds: int = Field(default=600, ge=120, le=900)
    http_timeout_seconds: float = Field(default=5.0, gt=0, le=15)

    @model_validator(mode="after")
    def yahoo_gate(self) -> Self:
        if self.yahoo.enabled and not self.yahoo.pkce_verified:
            raise ValueError("verify Yahoo S256 enforcement in the sandbox before enabling it")
        return self
