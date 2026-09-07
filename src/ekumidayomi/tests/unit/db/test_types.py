"""Tests for shared SQLAlchemy value types."""

import sqlalchemy as sa

from ekumidayomi.core.types import MONEY_PRECISION, MONEY_SCALE
from ekumidayomi.db.types import money_type


def test_money_type_is_exact_postgresql_numeric() -> None:
    value_type = money_type()

    assert isinstance(value_type, sa.Numeric)
    assert value_type.precision == MONEY_PRECISION == 19
    assert value_type.scale == MONEY_SCALE == 4
    assert value_type.asdecimal is True
    dialect = sa.engine.make_url("postgresql://").get_dialect()()
    assert str(value_type.compile(dialect=dialect)) == "NUMERIC(19, 4)"
