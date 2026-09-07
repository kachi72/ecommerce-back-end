"""Boundary tests spanning the shared Sprint 1 platform contracts."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from ekumidayomi.cache.codec import JsonCacheCodec
from ekumidayomi.cache.keys import CacheKey
from ekumidayomi.core.types import (
    DecimalInput,
    Money,
    PageRequest,
    quantize_money,
    require_utc,
    serialize_entity_id,
)
from ekumidayomi.storage.types import ObjectKey, UploadMetadata

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", [True, 1, 1.5])
def test_money_rejects_boolean_integer_and_float_inputs(value: object) -> None:
    with pytest.raises(TypeError):
        quantize_money(cast("DecimalInput", value))


def test_money_accepts_strings_and_uses_four_place_half_even_rounding() -> None:
    assert Money.from_value(amount="1.23455").amount == Decimal("1.2346")
    assert Money.from_value(amount="-1").amount == Decimal("-1.0000")


@pytest.mark.parametrize("page,page_size", [(0, 20), (1, 0), (1, 101)])
def test_page_request_rejects_out_of_bounds_values(page: int, page_size: int) -> None:
    with pytest.raises(ValueError):
        PageRequest(page, page_size)


def test_utc_and_uuid_serialization_are_stable() -> None:
    assert require_utc(datetime(2026, 1, 1, tzinfo=UTC)).tzinfo is UTC
    identifier = uuid4()

    assert serialize_entity_id(identifier) == str(identifier)


def test_cache_codec_and_key_reject_unbounded_inputs() -> None:
    with pytest.raises(ValueError, match="unsafe cache key segment"):
        CacheKey("test", "owner", 1, "scope", "x" * 65)
    with pytest.raises(ValueError, match="byte limit"):
        JsonCacheCodec(max_bytes=8).encode({"value": "too-large"})


def test_media_contract_rejects_traversal_and_oversized_metadata() -> None:
    checksum = hashlib.sha256(b"image").hexdigest()

    with pytest.raises(ValueError, match="object key is unsafe"):
        ObjectKey("products/../private")
    with pytest.raises(ValueError, match="size_bytes must be between"):
        UploadMetadata(
            content_type="image/jpeg",
            size_bytes=10_485_761,
            sha256=checksum,
        )
