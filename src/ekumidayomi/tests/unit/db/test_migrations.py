"""Alembic migration-chain integrity tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from ekumidayomi.db.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[5]
ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def get_script_directory() -> ScriptDirectory:
    """Load the repository's Alembic revision directory."""
    return ScriptDirectory.from_config(Config(ALEMBIC_CONFIG))


def test_migration_chain_has_exactly_one_baseline_head() -> None:
    script = get_script_directory()

    assert script.get_heads() == ["0001_sprint0_baseline"]
    assert script.get_base() == "0001_sprint0_baseline"


def test_baseline_has_no_parent_or_domain_tables() -> None:
    baseline = get_script_directory().get_revision("0001_sprint0_baseline")

    assert baseline is not None
    assert baseline.down_revision is None
    assert Base.metadata.tables == {}
