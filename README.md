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

The remaining database, migration, container, and operations commands are introduced by their later Sprint 0 issues.
