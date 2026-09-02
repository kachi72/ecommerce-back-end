"""Alembic migration-chain integrity tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from ekumidayomi.audit.model import AuditRecord
from ekumidayomi.db.base import Base
from ekumidayomi.jobs.models import Job
from ekumidayomi.outbox.model import OutboxMessage

PROJECT_ROOT = Path(__file__).resolve().parents[5]
ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def get_script_directory() -> ScriptDirectory:
    """Load the repository's Alembic revision directory."""
    return ScriptDirectory.from_config(Config(ALEMBIC_CONFIG))


def test_migration_chain_has_exactly_one_platform_head() -> None:
    script = get_script_directory()

    assert script.get_heads() == ["46ad9a9488c3"]
    assert script.get_base() == "0001_sprint0_baseline"


def test_baseline_outbox_jobs_and_audit_form_one_linear_chain() -> None:
    baseline = get_script_directory().get_revision("0001_sprint0_baseline")
    outbox = get_script_directory().get_revision("1118b82ffb5c")
    jobs = get_script_directory().get_revision("734dfb7a6638")
    audit = get_script_directory().get_revision("46ad9a9488c3")

    assert baseline is not None
    assert baseline.down_revision is None
    assert outbox is not None
    assert outbox.down_revision == "0001_sprint0_baseline"
    assert jobs is not None
    assert jobs.down_revision == "1118b82ffb5c"
    assert audit is not None
    assert audit.down_revision == "734dfb7a6638"


def test_platform_models_are_registered_for_autogeneration() -> None:
    script = get_script_directory()

    assert script.get_current_head() == "46ad9a9488c3"
    assert Job.__tablename__ == "jobs"
    assert OutboxMessage.__tablename__ == "outbox_messages"
    assert AuditRecord.__tablename__ == "audit_records"
    assert set(Base.metadata.tables) == {"audit_records", "jobs", "outbox_messages"}
