"""Tests for private media value objects and the in-memory storage adapter."""

import hashlib
from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from ekumidayomi.storage.memory import MemoryObjectStorage
from ekumidayomi.storage.ports import ObjectStorage
from ekumidayomi.storage.types import ObjectKey, SignedAccess, StoredObject, UploadMetadata

pytestmark = pytest.mark.unit


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    """Yield upload content in caller-defined chunks."""
    for part in parts:
        yield part


async def failing_chunks(content: bytes) -> AsyncIterator[bytes]:
    """Simulate an adapter input stream that fails after yielding data."""
    yield content
    raise OSError("upload stream failed")


def metadata_for(
    content: bytes,
    *,
    content_type: str = "image/jpeg",
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> UploadMetadata:
    """Build valid metadata unless a test supplies an explicit mismatch."""
    return UploadMetadata(
        content_type=content_type,
        size_bytes=len(content) if size_bytes is None else size_bytes,
        sha256=hashlib.sha256(content).hexdigest() if sha256 is None else sha256,
    )


def product_key(*, extension: str = "jpg") -> ObjectKey:
    """Build a generated product-media key."""
    return ObjectKey.product_image(uuid4(), uuid4(), extension)


def test_product_image_generates_a_namespaced_object_key() -> None:
    product_id = UUID("00000000-0000-0000-0000-000000000001")
    object_id = UUID("00000000-0000-0000-0000-000000000002")

    key = ObjectKey.product_image(product_id, object_id, "webp")

    assert key.value == f"products/{product_id}/{object_id}.webp"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/products/image.jpg",
        r"products\image.jpg",
        "products/../secret",
        "../secret",
        "products/image\x00.jpg",
        "x" * 256,
    ],
)
def test_object_key_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError, match="object key is unsafe"):
        ObjectKey(value)


@pytest.mark.parametrize("extension", ["", "gif", "jpeg", "JPG", "jpg.exe"])
def test_product_image_rejects_unsupported_extensions(extension: str) -> None:
    with pytest.raises(ValueError, match=r"file extension is (?:not )?supported"):
        product_key(extension=extension)


def test_object_key_is_immutable() -> None:
    key = product_key()
    field_name = "value"

    with pytest.raises(FrozenInstanceError):
        setattr(key, field_name, "products/replaced.jpg")


@pytest.mark.parametrize("content_type", ["text/html", "image/gif", "IMAGE/JPEG", "image/jpeg;x=1"])
def test_upload_metadata_rejects_unsupported_or_spoofed_content_types(
    content_type: str,
) -> None:
    with pytest.raises(ValueError, match="content type is unsupported"):
        metadata_for(b"image", content_type=content_type)


@pytest.mark.parametrize("size_bytes", [False, -1, 0, 10_485_761])
def test_upload_metadata_rejects_invalid_declared_sizes(size_bytes: int) -> None:
    with pytest.raises(ValueError, match="size_bytes must be between 1 and 10485760"):
        metadata_for(b"image", size_bytes=size_bytes)


@pytest.mark.parametrize(
    "sha256",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
    ],
)
def test_upload_metadata_rejects_invalid_checksums(sha256: str) -> None:
    with pytest.raises(ValueError, match="sha256 must be lowercase hexadecimal"):
        metadata_for(b"image", sha256=sha256)


def test_upload_metadata_accepts_each_allowlisted_image_type() -> None:
    for content_type in ("image/avif", "image/jpeg", "image/png", "image/webp"):
        metadata = metadata_for(b"image", content_type=content_type)

        assert metadata.content_type == content_type


def test_stored_object_normalizes_an_aware_timestamp_to_utc() -> None:
    local_time = datetime(2026, 9, 4, 13, 30, tzinfo=timezone(timedelta(hours=1)))

    stored = StoredObject(
        key=product_key(),
        metadata=metadata_for(b"image"),
        stored_at=local_time,
    )

    assert stored.stored_at == datetime(2026, 9, 4, 12, 30, tzinfo=UTC)
    assert stored.stored_at.tzinfo is UTC


def test_stored_object_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="datetime must be timezone-aware"):
        StoredObject(
            key=product_key(),
            metadata=metadata_for(b"image"),
            stored_at=datetime(2026, 9, 4, 12, 30),
        )


def test_signed_access_requires_https_and_normalizes_expiry_to_utc() -> None:
    local_expiry = datetime(2026, 9, 4, 13, 30, tzinfo=timezone(timedelta(hours=1)))

    access = SignedAccess(url="https://storage.example/object", expires_at=local_expiry)

    assert access.expires_at == datetime(2026, 9, 4, 12, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="signed access must use HTTPS"):
        SignedAccess(url="http://storage.example/object", expires_at=local_expiry)


def test_signed_access_rejects_a_naive_expiry() -> None:
    with pytest.raises(ValueError, match="datetime must be timezone-aware"):
        SignedAccess(
            url="https://storage.example/object",
            expires_at=datetime(2026, 9, 4, 12, 30),
        )


def test_memory_adapter_satisfies_the_storage_port() -> None:
    storage: ObjectStorage = MemoryObjectStorage()

    assert storage is not None


async def test_memory_storage_verifies_and_retrieves_a_multichunk_upload() -> None:
    content = b"private-image-content"
    key = product_key()
    metadata = metadata_for(content)
    storage = MemoryObjectStorage()

    stored = await storage.put(key, chunks(content[:7], content[7:]), metadata)

    assert stored.key == key
    assert stored.metadata == metadata
    assert stored.stored_at.tzinfo is UTC
    assert await storage.head(key) == stored


async def test_memory_storage_returns_none_for_a_missing_object() -> None:
    storage = MemoryObjectStorage()

    assert await storage.head(product_key()) is None


async def test_memory_storage_rejects_content_larger_than_the_declared_size() -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()

    with pytest.raises(ValueError, match="uploaded object exceeds declared size"):
        await storage.put(key, chunks(content), metadata_for(content, size_bytes=len(content) - 1))

    assert await storage.head(key) is None


async def test_memory_storage_rejects_content_smaller_than_the_declared_size() -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()

    with pytest.raises(ValueError, match="uploaded object does not match declared metadata"):
        await storage.put(key, chunks(content), metadata_for(content, size_bytes=len(content) + 1))

    assert await storage.head(key) is None


async def test_memory_storage_rejects_a_checksum_mismatch() -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()

    with pytest.raises(ValueError, match="uploaded object does not match declared metadata"):
        await storage.put(key, chunks(content), metadata_for(b"different"))

    assert await storage.head(key) is None


async def test_memory_storage_propagates_stream_failures_without_storing_partial_data() -> None:
    content = b"partial"
    key = product_key()
    storage = MemoryObjectStorage()

    with pytest.raises(OSError, match="upload stream failed"):
        await storage.put(key, failing_chunks(content), metadata_for(content))

    assert await storage.head(key) is None


async def test_memory_storage_signs_existing_objects_with_bounded_private_access() -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()
    await storage.put(key, chunks(content), metadata_for(content))

    before = datetime.now(UTC)
    access = await storage.sign_read(key, timedelta(minutes=5))
    after = datetime.now(UTC)

    assert access.url == f"https://storage.test/{key.value}?signature=test-only"
    assert before + timedelta(minutes=5) <= access.expires_at <= after + timedelta(minutes=5)


@pytest.mark.parametrize(
    "expires_in",
    [timedelta(0), timedelta(microseconds=999_999), timedelta(minutes=15, microseconds=1)],
)
async def test_memory_storage_rejects_expiry_outside_the_allowed_range(
    expires_in: timedelta,
) -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()
    await storage.put(key, chunks(content), metadata_for(content))

    with pytest.raises(
        ValueError,
        match="signed access expiry must be between 1 second and 15 minutes",
    ):
        await storage.sign_read(key, expires_in)


@pytest.mark.parametrize("expires_in", [timedelta(seconds=1), timedelta(minutes=15)])
async def test_memory_storage_accepts_expiry_boundaries(expires_in: timedelta) -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()
    await storage.put(key, chunks(content), metadata_for(content))

    access = await storage.sign_read(key, expires_in)

    assert access.expires_at > datetime.now(UTC)


async def test_memory_storage_rejects_signed_access_for_a_missing_object() -> None:
    key = product_key()
    storage = MemoryObjectStorage()

    with pytest.raises(FileNotFoundError, match=key.value):
        await storage.sign_read(key, timedelta(minutes=5))


async def test_memory_storage_delete_is_idempotent() -> None:
    content = b"image"
    key = product_key()
    storage = MemoryObjectStorage()
    await storage.put(key, chunks(content), metadata_for(content))

    await storage.delete(key)
    await storage.delete(key)

    assert await storage.head(key) is None
    with pytest.raises(FileNotFoundError):
        await storage.sign_read(key, timedelta(minutes=5))
