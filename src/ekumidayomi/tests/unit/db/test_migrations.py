"""Alembic migration-chain integrity tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from ekumidayomi.db.base import Base
from ekumidayomi.outbox.model import OutboxMessage

PROJECT_ROOT = Path(__file__).resolve().parents[5]
ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def get_script_directory() -> ScriptDirectory:
    """Load the repository's Alembic revision directory."""
    return ScriptDirectory.from_config(Config(ALEMBIC_CONFIG))


def test_migration_chain_has_exactly_one_platform_head() -> None:
    script = get_script_directory()

    assert script.get_heads() == ["0002_platform_outbox"]
    assert script.get_base() == "0001_sprint0_baseline"


def test_baseline_has_no_parent_and_outbox_follows_it() -> None:
    baseline = get_script_directory().get_revision("0001_sprint0_baseline")
    outbox = get_script_directory().get_revision("0002_platform_outbox")

    assert baseline is not None
    assert baseline.down_revision is None
    assert outbox is not None
    assert outbox.down_revision == "0001_sprint0_baseline"


def test_outbox_is_the_only_registered_platform_table() -> None:
    script = get_script_directory()

    assert script.get_current_head() == "0002_platform_outbox"
    assert OutboxMessage.__tablename__ == "outbox_messages"
    assert set(Base.metadata.tables) == {"outbox_messages"}
