"""External identities retain local ownership and uniqueness constraints."""

from typing import cast

import sqlalchemy as sa

from ekumidayomi.auth.model import ExternalIdentity
from ekumidayomi.db.base import Base


def test_external_identity_schema_contract() -> None:
    table = cast(sa.Table, ExternalIdentity.__table__)

    assert table.metadata is Base.metadata
    assert table.primary_key.name == "pk_external_identities"
    foreign_keys = list(table.foreign_key_constraints)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].name == "fk_external_identities_user_id_users"
    assert foreign_keys[0].ondelete == "CASCADE"
    assert [element.target_fullname for element in foreign_keys[0].elements] == ["users.id"]
    assert {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {
        ("uq_external_identities_provider_subject", ("provider", "subject")),
        ("uq_external_identities_user_id_provider", ("user_id", "provider")),
    }
    assert isinstance(table.c.provider.type, sa.String)
    assert table.c.provider.type.length == 20
    assert isinstance(table.c.subject.type, sa.String)
    assert table.c.subject.type.length == 255
    assert table.c.last_login_at.nullable is False
