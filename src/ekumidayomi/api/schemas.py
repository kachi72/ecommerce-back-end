"""Reusable schemas for stable HTTP API responses."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)

from ekumidayomi.core.types import Money, require_utc, serialize_utc
from ekumidayomi.core.types import Page as DomainPage

type APIEntityId = Annotated[
    UUID,
    Field(examples=["7b9c61d4-81d5-4bf4-8945-3354a481b109"]),
]
type UTCDateTime = Annotated[
    datetime,
    AfterValidator(require_utc),
    PlainSerializer(serialize_utc, return_type=str, when_used="json"),
    Field(examples=["2026-08-31T12:30:00Z"]),
]


class APIModel(BaseModel):
    """Base response model with strict, ORM-compatible input handling."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True, strict=True)


class PageMeta(APIModel):
    """Deterministic metadata for a one-based result page."""

    page: int = Field(ge=1, examples=[1])
    page_size: int = Field(ge=1, le=100, examples=[20])
    total_items: int = Field(ge=0, examples=[42])
    total_pages: int = Field(ge=0, examples=[3])
    has_previous: bool
    has_next: bool

    @model_validator(mode="after")
    def validate_derived_values(self) -> Self:
        """Reject pagination metadata that contradicts its source values."""

        expected_pages = (self.total_items + self.page_size - 1) // self.page_size
        if self.total_pages != expected_pages:
            raise ValueError("total_pages does not match total_items and page_size")
        if self.has_previous is not (self.page > 1):
            raise ValueError("has_previous does not match page")
        if self.has_next is not (self.page < expected_pages):
            raise ValueError("has_next does not match page and total_pages")
        return self


class Page[T](APIModel):
    """Items and stable metadata returned by every page-based endpoint."""

    items: list[T]
    pagination: PageMeta

    @model_validator(mode="after")
    def validate_item_count(self) -> Self:
        """Keep response contents within the declared page bounds."""

        if len(self.items) > self.pagination.page_size:
            raise ValueError("items cannot exceed page_size")
        if len(self.items) > self.pagination.total_items:
            raise ValueError("items cannot exceed total_items")
        return self

    @classmethod
    def from_domain(cls, page: DomainPage[T]) -> Self:
        """Build an API page from the framework-neutral domain contract."""

        return cls(
            items=list(page.items),
            pagination=PageMeta(
                page=page.page,
                page_size=page.page_size,
                total_items=page.total_items,
                total_pages=page.total_pages,
                has_previous=page.has_previous,
                has_next=page.has_next,
            ),
        )


class MoneyResponse(APIModel):
    """Current version-one NGN money response contract."""

    amount_kobo: int = Field(ge=0, examples=[150_000])
    currency: Literal["NGN"] = "NGN"

    @classmethod
    def from_domain(cls, value: Money) -> Self:
        """Build the HTTP representation of a domain money value."""

        return cls(amount_kobo=value.amount_kobo, currency=value.currency.value)


def serialize_page[T](page: DomainPage[T], *, items: Sequence[T] | None = None) -> Page[T]:
    """Serialize a domain page, optionally using already-adapted response items."""

    resolved_items = list(page.items if items is None else items)
    return Page[T](
        items=resolved_items,
        pagination=PageMeta(
            page=page.page,
            page_size=page.page_size,
            total_items=page.total_items,
            total_pages=page.total_pages,
            has_previous=page.has_previous,
            has_next=page.has_next,
        ),
    )
