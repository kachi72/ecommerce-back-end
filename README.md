# Ẹkúmidáyọ̀mí Backend

FastAPI backend for the Ẹkúmidáyọ̀mí ecommerce platform.

## Prerequisites

- Python 3.13 managed through `uv`
- `uv` for dependency and virtual-environment management
- `just` as the project command runner
- PostgreSQL and Redis instances matching the configured local URLs

## Local configuration

Create an untracked `.env` file from the safe development template.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```shell
cp .env.example .env
```

Review the development-only values before use. The development and test database URLs must remain separate. Never commit `.env`, production credentials, or complete connection URLs containing real passwords.

See [the configuration reference](docs/configuration.md) for every setting, environment-specific safety rule, JSON-list format, host-versus-container hostname guidance, and the production secret boundary.

## Install and run

From the repository root:

```shell
uv sync --frozen
just run
```

The remaining database, migration, and operations commands are introduced by their later Sprint 0 issues.

## Containers

Build and start the API, development PostgreSQL, isolated test PostgreSQL, and Redis:

```shell
just containers-up
```

Open `http://localhost:8000/docs` for the API documentation. The container is ready when `http://localhost:8000/health/ready` returns `200`.

The local services publish these ports:

- API: `8000`
- Development PostgreSQL: `5432`
- Test PostgreSQL: `5433`
- Redis: `6379`

Useful commands:

```shell
just containers-status
just containers-logs
just container-migrate
just container-smoke
just containers-down
```

`containers-down` stops the stack without deleting its named volumes. Development and test PostgreSQL use different databases and different volumes.

The local Compose app enables `RUN_MIGRATIONS_ON_STARTUP` for one development replica. Do not enable startup migrations in a multi-replica or production deployment. Production migrations must run exactly once as a separate release step defined by the later deployment workflow.
