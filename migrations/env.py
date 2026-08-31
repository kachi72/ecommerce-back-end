"""Async Alembic environment."""

from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from ekumidayomi.core.settings import get_settings
from ekumidayomi.db.base import Base
from ekumidayomi.outbox.model import OutboxMessage

_REGISTERED_MODELS = (OutboxMessage,)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import domain model modules above this assignment when their owning sprint adds
# them. Importing FastAPI or constructing the application here is forbidden.
target_metadata = Base.metadata


def configure_context(connection: Connection) -> None:
    """Configure and run migrations on a synchronous connection adapter."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Generate migration SQL without opening a database connection."""
    context.configure(
        url=get_settings().active_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations through SQLAlchemy's async engine adapter."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_settings().active_database_url
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(configure_context)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())
