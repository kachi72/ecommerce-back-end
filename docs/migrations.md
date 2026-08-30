# Database migrations

Alembic owns every PostgreSQL schema change. The migration environment uses `Settings.active_database_url` and the shared `Base.metadata`; tracked Alembic configuration contains no usable database credential.

## Commands

Run commands from the repository root:

```shell
just migration-heads
just migration-current
just migrate
just migration "short description"
just migration-check
just migration-integrity
just migration-downgrade base
```

- `migration-heads` must report exactly one head.
- `migration-current` displays the revision applied to the configured database.
- `migrate` upgrades the configured database to the latest revision.
- `migration` autogenerates a candidate revision from ORM metadata changes.
- `migration-check` fails when ORM metadata differs from the migration chain.
- `migration-integrity` requires one head, upgrades the active database, and checks for drift.
- `migration-downgrade` defaults to `base`; pass a specific revision when a narrower rollback is required.

## Host and container URLs

Alembic uses the same environment contract as the application.

- When Alembic runs on the host machine, PostgreSQL commonly uses `localhost` and the published host port.
- When Alembic runs inside Docker Compose, PostgreSQL uses the Compose service name and container port, such as `postgres:5432`.
- Test migrations must target the dedicated test database rather than development data.

Never change a tracked URL to contain a real credential. Select the environment through runtime configuration.

## Creating a revision

1. Add or update the ORM model in its owning sprint.
2. Import the new model module in `migrations/env.py` so its tables are registered on `Base.metadata`.
3. Confirm the intended database is disposable or backed up as appropriate.
4. Run `just migration "describe the schema change"`.
5. Review every generated upgrade and downgrade operation manually.
6. Add missing PostgreSQL constraints, indexes, server defaults, or data-migration steps explicitly.
7. Run the migration against a clean database and an upgraded copy of the previous schema.
8. Confirm `just migration-heads` still reports one head and `just migration-check` reports no drift.

Autogeneration is a draft, not an approval mechanism. It may miss renames, data transformations, partial indexes, constraint intent, and safe deployment sequencing.

## ORM conventions

- Domain models use `UUIDPrimaryKeyMixin` for PostgreSQL-native UUID4 primary keys.
- Mutable domain models use `TimestampMixin` for non-null, timezone-aware `created_at` and `updated_at` values generated from PostgreSQL time.
- Archiving and deactivation are explicit opt-in fields through `ArchivedAtMixin` and `DeactivatedAtMixin`; there is no universal `deleted_at` column or hidden global query filter.
- Every string column declares an intentional maximum length unless the owning domain documents why unbounded text is required.
- Required values declare `nullable=False`, and database-generated values declare reviewed server defaults.
- Unique behavior uses explicit constraints rather than application-only checks.
- Every foreign key declares its intended update/delete behavior; destructive cascades require domain ownership and tests.
- Indexes must support a named query, ordering, constraint, or concurrency requirement. Do not index every foreign key or low-selectivity state field automatically.
- Multi-column indexes and constraints follow query and selectivity order, and deterministic metadata names include every participating column.
- Check constraints are explicitly named so Alembic can produce stable `ck_<table>_<constraint>` identifiers.

The mixins register no tables on `Base.metadata`, so introducing or changing an abstract convention alone does not require an Alembic revision. Domain tables adopt these conventions and add migrations in their owning sprint.

## Applying and verifying migrations

For each revision:

1. Upgrade a clean PostgreSQL database from `base` to `head`.
2. Confirm `just migration-current` reports the expected head.
3. Exercise the application behavior that uses the changed schema.
4. Downgrade to the previous revision when the migration is designed to be reversible.
5. Upgrade to `head` again and rerun the relevant tests.

The Sprint 0 baseline is intentionally empty. It creates no customer, product, inventory, order, payment, review, analytics, or other ecommerce table.

## Multiple heads

Do not merge a change that introduces an unintended second head. Rebase the migration on the current head or create a reviewed merge revision when two already-deployed branches genuinely require one. CI must assert that the repository has exactly one head.

The `Migration integrity` workflow repeats this check against a clean PostgreSQL 17 service,
upgrades that database to `head`, confirms the current revision, and runs `alembic check`.

## Production safety

- Never edit a revision that has been deployed. Add a corrective revision.
- Never run a destructive reset against a shared or production database.
- Coordinate destructive or non-reversible operations with a backup, compatibility window, data-migration plan, and rollback decision.
- Prefer expand/migrate/contract sequencing for changes that must remain compatible with a previous application version.
- Run production migrations exactly once through the release workflow rather than from every application replica.
- Deploy expand-compatible schema changes before application code that depends on them. Complete
  backfills before a later release removes compatibility columns or constraints.
- Roll back application code independently when possible. A database downgrade is permitted only
  when the reviewed migration and recovery plan prove it is safe for already-written data.
- Keep credentials and complete connection URLs out of logs, pull requests, screenshots, and command output.
