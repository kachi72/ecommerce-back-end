"""Bounded, versioned JSON cache encoding."""

import json
from dataclasses import dataclass


class CacheDecodeError(ValueError):
    """A cached value is corrupt, oversized, or uses an unsupported schema."""


@dataclass(frozen=True, slots=True)
class JsonCacheCodec:
    """Encode JSON values inside a strict schema-version envelope."""

    schema_version: int = 1
    max_bytes: int = 262_144

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or not 1 <= self.schema_version <= 999
        ):
            raise ValueError("schema_version must be an integer between 1 and 999")
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not 1 <= self.max_bytes <= 1_048_576
        ):
            raise ValueError("max_bytes must be an integer between 1 and 1048576")

    def encode(self, value: object) -> bytes:
        """Encode one JSON-safe, non-null value within the byte limit."""

        if value is None:
            raise ValueError("cache value must not be null")
        try:
            encoded = json.dumps(
                {"schema_version": self.schema_version, "value": value},
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ValueError("cache value must be JSON-safe") from error
        if len(encoded) > self.max_bytes:
            raise ValueError("cache value exceeds the byte limit")
        return encoded

    def decode(self, encoded: str | bytes) -> object:
        """Decode a supported envelope or raise a corruption-safe error."""

        if isinstance(encoded, str):
            try:
                raw = encoded.encode("utf-8")
            except UnicodeEncodeError as error:
                raise CacheDecodeError("cache value is corrupt") from error
        elif isinstance(encoded, bytes):
            raw = encoded
        else:
            raise CacheDecodeError("cache value has an unsupported representation")
        if len(raw) > self.max_bytes:
            raise CacheDecodeError("cache value exceeds the byte limit")
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CacheDecodeError("cache value is corrupt") from error
        if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "value"}:
            raise CacheDecodeError("cache envelope is invalid")
        if envelope["schema_version"] != self.schema_version:
            raise CacheDecodeError("cache schema version is unsupported")
        if envelope["value"] is None:
            raise CacheDecodeError("cache value must not be null")
        return envelope["value"]
