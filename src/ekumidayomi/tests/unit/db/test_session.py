"""Database session-boundary tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.core.settings import Settings
from ekumidayomi.db import session as session_module
from ekumidayomi.db.session import Database


def test_database_uses_active_url_and_bounded_pool_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock()
    session_factory = MagicMock()
    create_engine = MagicMock(return_value=engine)
    create_session_factory = MagicMock(return_value=session_factory)
    monkeypatch.setattr(session_module, "create_async_engine", create_engine)
    monkeypatch.setattr(session_module, "async_sessionmaker", create_session_factory)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@database/app",
        database_pool_size=7,
        database_max_overflow=3,
        database_connect_timeout_seconds=4,
    )

    database = Database(settings)

    assert database.engine is engine
    assert database.session_factory is session_factory
    create_engine.assert_called_once_with(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=7,
        max_overflow=3,
        connect_args={"timeout": 4.0},
    )
    create_session_factory.assert_called_once_with(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def build_database_with_session(
    session: AsyncMock,
) -> tuple[Database, AsyncMock]:
    context = AsyncMock()
    context.__aenter__.return_value = session
    context.__aexit__.return_value = None
    database = object.__new__(Database)
    database.session_factory = MagicMock(return_value=context)
    return database, context


@pytest.mark.asyncio
async def test_session_closes_without_implicit_commit() -> None:
    session = AsyncMock()
    database, context = build_database_with_session(session)

    async with database.session() as yielded_session:
        assert yielded_session is session

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_rolls_back_when_caller_raises() -> None:
    session = AsyncMock()
    database, context = build_database_with_session(session)

    with pytest.raises(RuntimeError, match="failed"):
        async with database.session():
            raise RuntimeError("failed")

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_connection_executes_minimal_query() -> None:
    connection = AsyncMock()
    connection_context = AsyncMock()
    connection_context.__aenter__.return_value = connection
    connection_context.__aexit__.return_value = None
    engine = MagicMock()
    engine.connect.return_value = connection_context
    database = object.__new__(Database)
    database.engine = engine

    await database.check_connection()

    statement = connection.execute.await_args.args[0]
    assert str(statement) == "SELECT 1"


@pytest.mark.asyncio
async def test_dispose_closes_the_engine() -> None:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    database = object.__new__(Database)
    database.engine = engine

    await database.dispose()

    engine.dispose.assert_awaited_once_with()
