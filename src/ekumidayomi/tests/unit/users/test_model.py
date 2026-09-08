"""Identity normalization, role and persistence-shape contracts."""

from typing import cast

import pytest
import sqlalchemy as sa

from ekumidayomi.db.base import Base
from ekumidayomi.users.errors import InvalidEmailError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import normalize_email


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Customer+shop@EXAMPLE.com ", "customer+shop@example.com"),
        ("first.last+shop@example.com", "first.last+shop@example.com"),
        ("  customer@EXAMPLE.COM  ", "customer@example.com"),
        ("ẸKÚ@EXAMPLE.com", "ẹkú@example.com"),
        ("Straße@example.com", "strasse@example.com"),
    ],
)
def test_email_policy(value: str, expected: str) -> None:
    normalized = normalize_email(value)
    assert normalized == expected
    assert normalize_email(normalized) == normalized


@pytest.mark.parametrize("value", ["", " ", "not-an-email", "a@", "a b@example.com"])
def test_invalid_email_uses_safe_domain_error(value: str) -> None:
    with pytest.raises(InvalidEmailError) as caught:
        normalize_email(value)
    assert caught.value.code == "invalid_email"
    assert caught.value.status_code == 422
    assert caught.value.details == {}
    assert caught.value.__suppress_context__ is True


def test_normalization_does_not_require_dns() -> None:
    # This syntactically valid domain need not exist; unit tests prohibit network I/O.
    assert normalize_email("customer@nonexistent-ekumidayomi-domain.com") == (
        "customer@nonexistent-ekumidayomi-domain.com"
    )


def test_roles_match_the_customer_and_admin_contract() -> None:
    assert {name: member.value for name, member in Role.__members__.items()} == {
        "CUSTOMER": "customer",
        "ADMIN": "admin",
    }


@pytest.mark.parametrize("value", ["owner", "administrator", "CUSTOMER", "", " customer "])
def test_unknown_roles_are_rejected_at_the_application_boundary(value: str) -> None:
    with pytest.raises(ValueError):
        Role(value)


def test_role_is_string_and_identity_contains_no_auth_secrets() -> None:
    table = cast(sa.Table, User.__table__)
    assert table.metadata is Base.metadata
    assert isinstance(table.c.role.type, sa.String)
    assert not isinstance(table.c.role.type, sa.Enum)
    assert table.c.role.type.length == 20
    assert table.c.role.nullable is False
    assert not any(isinstance(item, sa.CheckConstraint) for item in table.constraints)
    assert set(table.c.keys()) == {
        "id",
        "email",
        "display_name",
        "phone",
        "role",
        "is_active",
        "email_verified_at",
        "created_at",
        "updated_at",
    }


def test_identity_constraints_use_shared_metadata_names() -> None:
    table = cast(sa.Table, User.__table__)
    unique_constraints = [
        item for item in table.constraints if isinstance(item, sa.UniqueConstraint)
    ]
    assert [(item.name, list(item.columns.keys())) for item in unique_constraints] == [
        ("uq_users_email", ["email"]),
    ]
    assert [(item.name, list(item.columns.keys())) for item in table.indexes] == [
        ("ix_users_role_is_active", ["role", "is_active"]),
    ]
    assert table.primary_key.name == "pk_users"
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert table.c.email.nullable is False
    assert isinstance(table.c.email.type, sa.String)
    assert table.c.email.type.length == 320
    assert isinstance(table.c.id.type, sa.UUID)
    for name in ("email_verified_at", "created_at", "updated_at"):
        column_type = table.c[name].type
        assert isinstance(column_type, sa.DateTime)
        assert column_type.timezone is True
