"""Alembic migration-chain integrity tests."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from ekumidayomi.audit.model import AuditRecord
from ekumidayomi.auth.challenge_model import EmailChallenge, PasswordCredential
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.db.base import Base
from ekumidayomi.jobs.models import Job
from ekumidayomi.outbox.model import OutboxMessage, WorkerControl
from ekumidayomi.users.model import User

PROJECT_ROOT = Path(__file__).resolve().parents[5]
ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def get_script_directory() -> ScriptDirectory:
    """Load the repository's Alembic revision directory."""
    return ScriptDirectory.from_config(Config(ALEMBIC_CONFIG))


def test_migration_chain_has_exactly_one_platform_head() -> None:
    script = get_script_directory()

    assert script.get_heads() == ["111bac782bb3"]
    assert script.get_base() == "0001_sprint0_baseline"


def test_platform_users_and_auth_sessions_form_one_linear_chain() -> None:
    baseline = get_script_directory().get_revision("0001_sprint0_baseline")
    outbox = get_script_directory().get_revision("1118b82ffb5c")
    jobs = get_script_directory().get_revision("734dfb7a6638")
    audit = get_script_directory().get_revision("46ad9a9488c3")
    users = get_script_directory().get_revision("4f2722ba18ca")
    sessions = get_script_directory().get_revision("111bac782bb3")

    assert baseline is not None
    assert baseline.down_revision is None
    assert outbox is not None
    assert outbox.down_revision == "0001_sprint0_baseline"
    assert jobs is not None
    assert jobs.down_revision == "1118b82ffb5c"
    assert audit is not None
    assert audit.down_revision == "734dfb7a6638"
    assert users is not None
    assert users.down_revision == "46ad9a9488c3"
    assert sessions is not None
    assert sessions.down_revision == "4f2722ba18ca"


def test_platform_models_are_registered_for_autogeneration() -> None:
    script = get_script_directory()

    assert script.get_current_head() == "111bac782bb3"
    assert Job.__tablename__ == "jobs"
    assert OutboxMessage.__tablename__ == "outbox_messages"
    assert AuditRecord.__tablename__ == "audit_records"
    assert User.__tablename__ == "users"
    assert AuthSession.__tablename__ == "auth_sessions"
    assert EmailChallenge.__tablename__ == "email_challenges"
    assert PasswordCredential.__tablename__ == "password_credentials"
    assert WorkerControl.__tablename__ == "outbox_worker_controls"
    assert set(Base.metadata.tables) == {
        "audit_records",
        "auth_sessions",
        "email_challenges",
        "jobs",
        "outbox_messages",
        "outbox_worker_controls",
        "password_credentials",
        "users",
    }
