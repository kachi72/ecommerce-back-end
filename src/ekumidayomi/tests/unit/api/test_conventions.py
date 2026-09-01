"""Tests for reusable API query and response conventions."""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, TypeAdapter, ValidationError

from ekumidayomi.api.errors import register_error_handlers
from ekumidayomi.api.query import SortField, pagination, parse_filters, parse_sort
from ekumidayomi.api.schemas import (
    APIEntityId,
    MoneyResponse,
    Page,
    PageMeta,
    UTCDateTime,
    serialize_page,
)
from ekumidayomi.core.types import Money, PageRequest
from ekumidayomi.core.types import Page as DomainPage


def test_pagination_is_bounded() -> None:
    assert pagination(page=2, page_size=50).offset == 50

    with pytest.raises(ValueError, match="page must be at least 1"):
        pagination(page=0, page_size=20)
    with pytest.raises(ValueError, match="page_size must be between"):
        pagination(page=1, page_size=101)


@pytest.mark.asyncio
async def test_pagination_query_validation_uses_the_stable_error_envelope() -> None:
    application = FastAPI()
    register_error_handlers(application)

    @application.get("/items")
    async def items(page_request: Annotated[PageRequest, Depends(pagination)]) -> dict[str, int]:
        return page_request.to_dict()

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        valid_response = await client.get("/items?page=2&page_size=50")
        invalid_response = await client.get(
            "/items?page=password-not-for-response&page_size=101",
            headers={"X-Request-ID": "pagination-validation"},
        )

    assert valid_response.json() == {"page": 2, "page_size": 50}
    assert invalid_response.status_code == 422
    assert invalid_response.json()["error"] == {
        "code": "request_validation_failed",
        "message": "Request validation failed",
        "details": {
            "fields": [
                {
                    "path": "query.page",
                    "code": "invalid_type",
                    "message": "Value has an invalid type",
                },
                {
                    "path": "query.page_size",
                    "code": "out_of_range",
                    "message": "Value is outside the allowed range",
                },
            ]
        },
        "request_id": "pagination-validation",
    }
    assert "password-not-for-response" not in invalid_response.text


def test_empty_page_uses_stable_metadata() -> None:
    page = Page[int](
        items=[],
        pagination=PageMeta(
            page=1,
            page_size=20,
            total_items=0,
            total_pages=0,
            has_previous=False,
            has_next=False,
        ),
    )

    assert page.model_dump() == {
        "items": [],
        "pagination": {
            "page": 1,
            "page_size": 20,
            "total_items": 0,
            "total_pages": 0,
            "has_previous": False,
            "has_next": False,
        },
    }


def test_page_rejects_inconsistent_metadata_and_item_counts() -> None:
    with pytest.raises(ValidationError, match="total_pages does not match"):
        PageMeta(
            page=1,
            page_size=20,
            total_items=21,
            total_pages=1,
            has_previous=False,
            has_next=False,
        )

    metadata = PageMeta(
        page=1,
        page_size=1,
        total_items=2,
        total_pages=2,
        has_previous=False,
        has_next=True,
    )
    with pytest.raises(ValidationError, match="items cannot exceed page_size"):
        Page[int](items=[1, 2], pagination=metadata)


def test_domain_page_serialization_preserves_metadata() -> None:
    domain_page = DomainPage(items=(1, 2), total_items=3, page=1, page_size=2)

    assert Page[int].from_domain(domain_page) == serialize_page(domain_page)
    assert serialize_page(domain_page, items=(10, 20)).items == [10, 20]
    assert serialize_page(domain_page).pagination.has_next is True


def test_money_response_uses_current_version_one_shape() -> None:
    assert MoneyResponse.from_domain(Money(amount_kobo=150_000)).model_dump() == {
        "amount_kobo": 150_000,
        "currency": "NGN",
    }

    with pytest.raises(ValidationError):
        MoneyResponse(amount_kobo=-1)
    with pytest.raises(ValidationError):
        MoneyResponse(amount_kobo=1, currency="USD")  # type: ignore[arg-type]


class SerializationProbe(BaseModel):
    identifier: APIEntityId
    occurred_at: UTCDateTime


def test_identifiers_and_timestamps_serialize_canonically() -> None:
    identifier = UUID("7b9c61d4-81d5-4bf4-8945-3354a481b109")
    value = SerializationProbe(
        identifier=identifier,
        occurred_at=datetime(2026, 8, 31, 13, 30, tzinfo=timezone(timedelta(hours=1))),
    )

    assert value.model_dump(mode="json") == {
        "identifier": str(identifier),
        "occurred_at": "2026-08-31T12:30:00Z",
    }
    with pytest.raises(ValidationError, match="datetime must be timezone-aware"):
        SerializationProbe(identifier=identifier, occurred_at=datetime(2026, 8, 31, 12, 30))


def test_serialization_types_publish_safe_openapi_examples() -> None:
    schema = SerializationProbe.model_json_schema()
    money_schema = TypeAdapter(MoneyResponse).json_schema()

    assert schema["$defs"]["APIEntityId"]["examples"] == ["7b9c61d4-81d5-4bf4-8945-3354a481b109"]
    assert schema["$defs"]["UTCDateTime"]["examples"] == ["2026-08-31T12:30:00Z"]
    assert money_schema["properties"]["amount_kobo"]["examples"] == [150_000]


def test_sorting_is_allowlisted_unique_and_stable() -> None:
    allowed = frozenset({"created_at", "name", "id"})

    assert parse_sort("-created_at,name", allowed=allowed) == (
        SortField("created_at", "desc"),
        SortField("name", "asc"),
        SortField("id", "asc"),
    )
    assert parse_sort("-id", allowed=allowed) == (SortField("id", "desc"),)
    assert parse_sort(None, allowed=allowed) == (SortField("id", "asc"),)

    with pytest.raises(ValueError, match="not allowed"):
        parse_sort("email", allowed=allowed)
    with pytest.raises(ValueError, match="unique"):
        parse_sort("name,-name", allowed=allowed)


@pytest.mark.parametrize(
    "value,allowed,message",
    [
        ("", frozenset({"name"}), "must include id"),
        (",name", frozenset({"name", "id"}), "not allowed"),
        ("name,", frozenset({"name", "id"}), "not allowed"),
        ("-", frozenset({"id"}), "not allowed"),
        ("a" * 501, frozenset({"id"}), "too long"),
        (",".join(f"field_{index}" for index in range(11)), frozenset({"id"}), "at most 10"),
    ],
)
def test_sorting_rejects_malformed_or_unbounded_values(
    value: str,
    allowed: frozenset[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_sort(value, allowed=allowed)


def test_filters_are_allowlisted_and_preserve_colons_in_values() -> None:
    allowed = frozenset({"status", "created_at"})

    assert parse_filters(
        ["status:active", "created_at:2026-08-31T12:30:00Z"],
        allowed=allowed,
    ) == {
        "status": "active",
        "created_at": "2026-08-31T12:30:00Z",
    }


@pytest.mark.parametrize(
    "values,allowed,message",
    [
        (["status:active", "status:inactive"], frozenset({"status"}), "unique"),
        (["email:value"], frozenset({"status"}), "unique allowed"),
        (["status"], frozenset({"status"}), "unique allowed"),
        (["status:"], frozenset({"status"}), "unique allowed"),
        (["status: active"], frozenset({"status"}), "unique allowed"),
        (["status:" + "a" * 501], frozenset({"status"}), "too long"),
        ([f"field_{index}:value" for index in range(21)], frozenset({"status"}), "at most 20"),
        (None, frozenset(), "safe field names"),
    ],
)
def test_filters_reject_unknown_duplicate_malformed_or_unbounded_values(
    values: list[str] | None,
    allowed: frozenset[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_filters(values, allowed=allowed)
