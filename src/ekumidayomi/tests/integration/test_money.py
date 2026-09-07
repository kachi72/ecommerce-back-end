"""Exact monetary values round-trip through PostgreSQL without a domain table."""

from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.core.types import Money
from ekumidayomi.db.types import money_type


@pytest.mark.parametrize(
    "amount", ["0", "10.00005", "10.00015", "-1.23456", "999999999999999.9999"]
)
async def test_money_round_trips_as_decimal(database_session: AsyncSession, amount: str) -> None:
    value = Money.from_value(amount=amount)
    result = await database_session.scalar(
        sa.select(sa.cast(sa.literal(value.amount, type_=money_type()), money_type()))
    )

    assert isinstance(result, Decimal)
    assert result == value.amount
    assert result.as_tuple().exponent == -4
