from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, min_length=5, max_length=32)


class ProfileView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    phone: str


class AddressInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["shipping", "billing"]
    recipient: str = Field(min_length=1, max_length=150)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    is_default: bool = False


class AddressView(AddressInput):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
