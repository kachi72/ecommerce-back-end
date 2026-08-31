"""Declarative metadata tests."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ekumidayomi.db.base import (
    NAMING_CONVENTION,
    ArchivedAtMixin,
    Base,
    DeactivatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class DefaultWithArg(Protocol):
    arg: object


class ConventionBase(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class Parent(UUIDPrimaryKeyMixin, ConventionBase):
    __tablename__ = "convention_parents"

    name: Mapped[str] = mapped_column(sa.String(50), nullable=False)


class ConventionExample(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    ArchivedAtMixin,
    DeactivatedAtMixin,
    ConventionBase,
):
    __tablename__ = "convention_examples"
    __table_args__ = (
        sa.UniqueConstraint("parent_id", "code"),
        sa.CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        sa.Index(None, "parent_id", "code"),
    )

    parent_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("convention_parents.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)


def test_base_uses_deterministic_constraint_names() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert NAMING_CONVENTION == {
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


def test_constraint_and_index_names_include_tables_and_all_columns() -> None:
    table = cast(sa.Table, ConventionExample.__table__)

    assert table.primary_key.name == "pk_convention_examples"
    assert next(iter(table.indexes)).name == "ix_convention_examples_parent_id_code"
    assert (
        next(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        )
        == "uq_convention_examples_parent_id_code"
    )
    assert (
        next(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        )
        == "ck_convention_examples_quantity_non_negative"
    )
    assert (
        next(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, sa.ForeignKeyConstraint)
        )
        == "fk_convention_examples_parent_id_convention_parents"
    )


def test_uuid_primary_key_uses_postgresql_uuid4() -> None:
    table = cast(sa.Table, ConventionExample.__table__)
    column = table.c.id

    assert isinstance(column.type, sa.UUID)
    assert column.type.as_uuid is True
    assert column.primary_key is True
    assert column.nullable is False
    assert column.default is not None
    default = cast(DefaultWithArg, column.default).arg
    assert callable(default)
    generated = cast(Callable[[object | None], UUID], default)(None)
    assert generated.version == 4


def test_timestamps_are_timezone_aware_and_server_generated() -> None:
    table = cast(sa.Table, ConventionExample.__table__)
    created_at = table.c.created_at
    updated_at = table.c.updated_at

    assert isinstance(created_at.type, sa.DateTime)
    assert isinstance(updated_at.type, sa.DateTime)
    assert created_at.type.timezone is True
    assert updated_at.type.timezone is True
    assert created_at.nullable is False
    assert updated_at.nullable is False
    assert created_at.server_default is not None
    assert updated_at.server_default is not None
    assert str(cast(DefaultWithArg, created_at.server_default).arg) == "now()"
    assert str(cast(DefaultWithArg, updated_at.server_default).arg) == "now()"
    assert updated_at.onupdate is not None
    assert str(cast(DefaultWithArg, updated_at.onupdate).arg) == "now()"


def test_soft_state_is_opt_in_without_global_deleted_at() -> None:
    table = cast(sa.Table, ConventionExample.__table__)
    columns = table.c

    assert isinstance(columns.archived_at.type, sa.DateTime)
    assert isinstance(columns.deactivated_at.type, sa.DateTime)
    assert columns.archived_at.type.timezone is True
    assert columns.archived_at.nullable is True
    assert columns.deactivated_at.type.timezone is True
    assert columns.deactivated_at.nullable is True
    assert "deleted_at" not in columns
    assert not hasattr(Base, "deleted_at")


def test_mixins_construct_a_typed_mapper() -> None:
    mapper = ConventionExample.__mapper__

    assert mapper.primary_key == (ConventionExample.__table__.c.id,)
    assert ConventionExample.__annotations__["code"] == Mapped[str]
    assert UUIDPrimaryKeyMixin.__annotations__["id"] == Mapped[UUID]
    assert TimestampMixin.__annotations__["created_at"] == Mapped[datetime]


def test_postgresql_ddl_uses_native_uuid_and_timestamptz() -> None:
    table = cast(sa.Table, ConventionExample.__table__)
    ddl = str(
        sa.schema.CreateTable(table).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
        )
    )

    assert "id UUID NOT NULL" in ddl
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl
    assert "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl
    assert "CONSTRAINT pk_convention_examples PRIMARY KEY (id)" in ddl
    assert "ON DELETE CASCADE" in ddl
