from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ekumidayomi.auth.oidc.settings import ProviderName


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: UUID = Field(default_factory=uuid4)
    provider: ProviderName
    intent: Literal["login", "link", "reauthenticate"]
    browser_hash: str
    nonce: str
    verifier: str
    redirect_uri: str
    return_path: Literal["/", "/profile", "/shop"] = "/profile"
    actor_id: UUID | None = None
    session_id: UUID | None = None
    started_at: int

    @model_validator(mode="after")
    def validate_actor_binding(self) -> Self:
        """Bind sensitive intents to both the initiating user and local session."""

        has_actor = self.actor_id is not None
        has_session = self.session_id is not None
        if self.intent == "login" and (has_actor or has_session):
            raise ValueError("login attempts must not carry a local actor")
        if self.intent != "login" and not (has_actor and has_session):
            raise ValueError("link and reauthentication attempts require a local actor")
        return self


@dataclass(frozen=True, slots=True)
class Identity:
    provider: ProviderName
    subject: str
    email: str | None
    email_verified: bool
    auth_time: int | None = None


class Provider(ABC):
    @abstractmethod
    async def authorization_url(self, state: str, attempt: Attempt) -> str:
        """Return an authorization-code URL with nonce and S256."""
        raise NotImplementedError

    @abstractmethod
    async def exchange(self, code: str, attempt: Attempt) -> Identity:
        """Return only verified identity claims; discard provider tokens."""
        raise NotImplementedError
