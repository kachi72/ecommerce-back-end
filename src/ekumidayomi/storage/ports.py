from abc import abstractmethod
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Protocol

from ekumidayomi.storage.types import ObjectKey, SignedAccess, StoredObject, UploadMetadata


class ObjectStorage(Protocol):
    @abstractmethod
    async def put(
        self, key: ObjectKey, chunks: AsyncIterator[bytes], metadata: UploadMetadata
    ) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    async def head(self, key: ObjectKey) -> StoredObject | None:
        raise NotImplementedError

    @abstractmethod
    async def sign_read(self, key: ObjectKey, expires_in: timedelta) -> SignedAccess:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: ObjectKey) -> None:
        raise NotImplementedError
