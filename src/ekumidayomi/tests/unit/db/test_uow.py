"""Tests for the explicit SQLAlchemy unit-of-work boundary."""

import asyncio
from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ekumidayomi.db.uow import PostCommit, SqlAlchemyUnitOfWork


def build_unit_of_work() -> tuple[SqlAlchemyUnitOfWork, AsyncMock, MagicMock]:
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction = MagicMock(return_value=False)
    factory = MagicMock(return_value=session)
    typed_factory = cast(async_sessionmaker[AsyncSession], factory)
    return SqlAlchemyUnitOfWork(typed_factory), session, factory


@pytest.mark.asyncio
async def test_context_owns_exactly_one_session_and_never_commits_implicitly() -> None:
    unit_of_work, session, factory = build_unit_of_work()

    with pytest.raises(RuntimeError, match="not active"):
        _ = unit_of_work.session

    async with unit_of_work as entered:
        assert entered is unit_of_work
        assert unit_of_work.session is session
        assert factory.call_count == 1

    factory.assert_called_once_with()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()
    with pytest.raises(RuntimeError, match="not active"):
        _ = unit_of_work.session


@pytest.mark.asyncio
async def test_explicit_commit_runs_callbacks_in_registration_order() -> None:
    unit_of_work, session, _ = build_unit_of_work()
    events: list[str] = []

    async def first() -> None:
        events.append("first")

    async def second() -> None:
        events.append("second")

    async with unit_of_work:
        unit_of_work.after_commit(first)
        unit_of_work.after_commit(second)
        await unit_of_work.commit()

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once_with()
    assert events == ["first", "second"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(lambda: RuntimeError("domain failure"), id="exception"),
        pytest.param(asyncio.CancelledError, id="cancellation"),
    ],
)
async def test_failure_rolls_back_and_closes(
    error_factory: Callable[[], BaseException],
) -> None:
    unit_of_work, session, _ = build_unit_of_work()
    error = error_factory()

    with pytest.raises(type(error)):
        async with unit_of_work:
            raise error

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_explicit_rollback_discards_callbacks_without_double_rollback() -> None:
    unit_of_work, session, _ = build_unit_of_work()
    callback = AsyncMock()

    async with unit_of_work:
        unit_of_work.after_commit(cast(PostCommit, callback))
        await unit_of_work.rollback()

    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()
    session.close.assert_awaited_once_with()
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_on_context_exit() -> None:
    unit_of_work, session, _ = build_unit_of_work()
    session.commit.side_effect = RuntimeError("database rejected commit")
    callback = AsyncMock()

    with pytest.raises(RuntimeError, match="database rejected commit"):
        async with unit_of_work:
            unit_of_work.after_commit(cast(PostCommit, callback))
            await unit_of_work.commit()

    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_failure_does_not_rollback_durable_commit() -> None:
    unit_of_work, session, _ = build_unit_of_work()
    first = AsyncMock(side_effect=RuntimeError("callback failed"))
    second = AsyncMock()

    with pytest.raises(RuntimeError, match="callback failed"):
        async with unit_of_work:
            unit_of_work.after_commit(cast(PostCommit, first))
            unit_of_work.after_commit(cast(PostCommit, second))
            await unit_of_work.commit()

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once_with()
    first.assert_awaited_once_with()
    second.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_transaction_after_commit_is_rolled_back_on_exit() -> None:
    unit_of_work, session, _ = build_unit_of_work()
    session.in_transaction.return_value = True

    async with unit_of_work:
        await unit_of_work.commit()

    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_close_runs_when_implicit_rollback_fails() -> None:
    unit_of_work, session, _ = build_unit_of_work()
    session.rollback.side_effect = RuntimeError("rollback failed")

    with pytest.raises(RuntimeError, match="rollback failed"):
        async with unit_of_work:
            pass

    session.close.assert_awaited_once_with()
    with pytest.raises(RuntimeError, match="not active"):
        _ = unit_of_work.session


@pytest.mark.asyncio
async def test_instance_cannot_be_reused() -> None:
    unit_of_work, session, factory = build_unit_of_work()

    async with unit_of_work:
        await unit_of_work.rollback()

    with pytest.raises(RuntimeError, match="cannot be reused"):
        async with unit_of_work:
            pass

    factory.assert_called_once_with()
    session.close.assert_awaited_once_with()


def test_callback_registration_requires_an_active_context() -> None:
    unit_of_work, _, _ = build_unit_of_work()

    with pytest.raises(RuntimeError, match="not active"):
        unit_of_work.after_commit(cast(PostCommit, AsyncMock()))


@pytest.mark.asyncio
async def test_callback_must_be_callable() -> None:
    unit_of_work, _, _ = build_unit_of_work()

    async with unit_of_work:
        with pytest.raises(TypeError, match="must be callable"):
            unit_of_work.after_commit(cast(PostCommit, None))
