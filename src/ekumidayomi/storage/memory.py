import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import quote

from ekumidayomi.core.types import utc_now
from ekumidayomi.storage.ports import ObjectStorage
from ekumidayomi.storage.types import ObjectKey, SignedAccess, StoredObject, UploadMetadata


class MemoryObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, StoredObject]] = {}

    async def put(
        self, key: ObjectKey, chunks: AsyncIterator[bytes], metadata: UploadMetadata
    ) -> StoredObject:
        digest = hashlib.sha256()
        content = bytearray()
        async for chunk in chunks:
            content.extend(chunk)
            digest.update(chunk)
            if len(content) > metadata.size_bytes:
                raise ValueError("uploaded object exceeds declared size")
        if len(content) != metadata.size_bytes or digest.hexdigest() != metadata.sha256:
            raise ValueError("uploaded object does not match declared metadata")
        stored = StoredObject(key=key, metadata=metadata, stored_at=utc_now())
        self._objects[key.value] = (bytes(content), stored)
        return stored

    async def head(self, key: ObjectKey) -> StoredObject | None:
        found = self._objects.get(key.value)
        return found[1] if found else None

    async def sign_read(self, key: ObjectKey, expires_in: timedelta) -> SignedAccess:
        if key.value not in self._objects:
            raise FileNotFoundError(key.value)
        if not timedelta(seconds=1) <= expires_in <= timedelta(minutes=15):
            raise ValueError("signed access expiry must be between 1 second and 15 minutes")
        return SignedAccess(
            url=f"https://storage.test/{quote(key.value)}?signature=test-only",
            expires_at=utc_now() + expires_in,
        )

    async def delete(self, key: ObjectKey) -> None:
        self._objects.pop(key.value, None)
