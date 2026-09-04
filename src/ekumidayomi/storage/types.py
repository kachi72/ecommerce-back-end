from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ekumidayomi.core.types import require_utc

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MIME_TYPES = frozenset({"image/avif", "image/jpeg", "image/png", "image/webp"})


@dataclass(frozen=True, slots=True)
class ObjectKey:
    value: str

    def __post_init__(self) -> None:
        if (
            not self.value
            or len(self.value) > 255
            or self.value.startswith("/")
            or "\\" in self.value
            or ".." in self.value.split("/")
            or any(ord(char) < 32 for char in self.value)
        ):
            raise ValueError("object key is unsafe")

    @classmethod
    def product_image(cls, product_id: UUID, object_id: UUID, extension: str) -> ObjectKey:
        if extension not in {"avif", "jpg", "png", "webp"}:
            raise ValueError("file extension is not supported")
        return cls(f"products/{product_id}/{object_id}.{extension}")


@dataclass(frozen=True, slots=True)
class UploadMetadata:
    content_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.content_type not in _MIME_TYPES:
            raise ValueError("content type is unsupported")
        if isinstance(self.size_bytes, bool) or not 1 <= self.size_bytes <= 10_485_760:
            raise ValueError("size_bytes must be between 1 and 10485760")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: ObjectKey
    metadata: UploadMetadata
    stored_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "stored_at", require_utc(self.stored_at))


@dataclass(frozen=True, slots=True)
class SignedAccess:
    url: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise ValueError("signed access must use HTTPS")
        object.__setattr__(self, "expires_at", require_utc(self.expires_at))
