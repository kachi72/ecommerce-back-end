"""Audit model and metadata convention tests."""

from typing import cast

import sqlalchemy as sa

from ekumidayomi.audit.model import ActorKind, AuditOutcome, AuditRecord


def test_audit_enums_are_application_strings() -> None:
    assert [kind.value for kind in ActorKind] == [
        "customer",
        "administrator",
        "system",
        "anonymous",
    ]
    assert [outcome.value for outcome in AuditOutcome] == [
        "succeeded",
        "denied",
        "failed",
    ]
    assert isinstance(AuditRecord.__table__.c.actor_kind.type, sa.String)
    assert isinstance(AuditRecord.__table__.c.outcome.type, sa.String)
    assert not isinstance(AuditRecord.__table__.c.actor_kind.type, sa.Enum)
    assert not isinstance(AuditRecord.__table__.c.outcome.type, sa.Enum)


def test_audit_constraints_and_indexes_use_shared_metadata_names() -> None:
    table = cast(sa.Table, AuditRecord.__table__)
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    index_names = {index.name for index in table.indexes}

    assert check_names == {"ck_audit_records_metadata_object"}
    assert index_names == {
        "ix_audit_records_action_occurred_at_id",
        "ix_audit_records_actor_id_occurred_at_id",
        "ix_audit_records_actor_kind_occurred_at_id",
        "ix_audit_records_correlation_id",
        "ix_audit_records_occurred_at_id",
        "ix_audit_records_outcome_occurred_at_id",
        "ix_audit_records_target_id_occurred_at_id",
        "ix_audit_records_target_type_target_id_occurred_at_id",
    }
