"""Reusable SQLAlchemy value-type factories."""

from decimal import Decimal

import sqlalchemy as sa

from ekumidayomi.core.types import MONEY_PRECISION, MONEY_SCALE


def money_type() -> sa.Numeric[Decimal]:
    """Return the project-wide exact monetary column type."""
    return sa.Numeric(
        precision=MONEY_PRECISION,
        scale=MONEY_SCALE,
        asdecimal=True,
    )
