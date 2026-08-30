"""Explicit SQLAlchemy unit-of-work transaction boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type PostCommit = Callable[[], Awaitable[None]]


class UnitOfWork(Protocol):
    """Application-facing atomic operation contract."""

    @property
    def session(self) -> AsyncSession: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    def after_commit(self, callback: PostCommit) -> None: ...


class SqlAlchemyUnitOfWork:
    """Own one async session and require application services to commit."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self._session: AsyncSession | None = None
        self._callbacks: list[PostCommit] = []
        self._used = False
        self._needs_rollback = False

    @property
    def session(self) -> AsyncSession:
        """Return the owned session while the context is active."""

        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session

    async def __aenter__(self) -> Self:
        if self._used:
            raise RuntimeError("unit of work instances cannot be reused")
        self._used = True
        self._session = self._factory()
        self._needs_rollback = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        session = self.session
        try:
            if self._needs_rollback or session.in_transaction():
                await session.rollback()
        finally:
            self._callbacks.clear()
            try:
                await session.close()
            finally:
                self._session = None
                self._needs_rollback = False

    async def commit(self) -> None:
        """Durably commit, then invoke queued callbacks in registration order."""

        session = self.session
        await session.commit()
        self._needs_rollback = False
        callbacks = tuple(self._callbacks)
        self._callbacks.clear()
        for callback in callbacks:
            await callback()

    async def rollback(self) -> None:
        """Explicitly roll back and discard all pending post-commit work."""

        session = self.session
        try:
            await session.rollback()
        finally:
            self._callbacks.clear()
        self._needs_rollback = False

    def after_commit(self, callback: PostCommit) -> None:
        """Queue an async side effect for the next successful commit."""

        if self._session is None:
            raise RuntimeError("unit of work is not active")
        if not callable(callback):
            raise TypeError("post-commit callback must be callable")
        self._callbacks.append(callback)
