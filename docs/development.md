# Development

## Prerequisites

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/)
- [`just`](https://just.systems/)
- Docker Desktop or Docker Engine with Compose

## Clean checkout

Run these steps from the repository root.

1. Copy `.env.example` to the untracked `.env` file.
2. Review the development-only database, Redis, host, and browser-origin values.
3. Run `uv sync --frozen --group dev` to install the locked development environment.
4. Run `just containers-up-deps` and wait for both PostgreSQL services and Redis to become
   healthy.
5. Run `just migrate` to upgrade the development database.
6. Run `just run` to start the API.
7. Open `http://localhost:8000/docs` and confirm `http://localhost:8000/health/ready` returns
   `200`.

On Windows PowerShell, create the local environment file with:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux, use:

```shell
cp .env.example .env
```

## Common commands

| Command | Purpose |
|---|---|
| `just run` | Start the API with reload enabled. |
| `just lint` | Run Ruff lint checks. |
| `just format` | Format Python source and migrations. |
| `just format-check` | Check formatting without modifying files. |
| `just typecheck` | Run strict mypy validation. |
| `just test-unit` | Run tests that require no external infrastructure. |
| `just test-integration` | Run PostgreSQL-backed integration tests. |
| `just test` | Run the full suite with terminal and HTML coverage reports. |
| `just qa` | Run lint, format, type, and complete test gates. |
| `just docs` | Build the HTML documentation site. |
| `just docs-check` | Build documentation and check links with warnings as errors. |
| `just containers-status` | Show local container health and status. |
| `just containers-down` | Stop local services without deleting named volumes. |

Integration tests require the isolated test PostgreSQL service published on port `5433`.
SQLite is not an approved substitute for PostgreSQL behavior.

## Troubleshooting

- If dependency startup fails, run `just containers-status` and inspect the relevant service
  with `just containers-logs <service>`.
- If the host API cannot resolve `postgres` or `redis`, restore the `localhost` URLs from
  `.env.example`; Compose service names resolve only inside the Compose network.
- If migrations target the wrong database, stop before retrying and verify `APP_ENV`,
  `DATABASE_URL`, and `TEST_DATABASE_URL` without printing their complete values.
- If locked installation fails after an intentional dependency change, update `uv.lock` in the
  dependency-owning change rather than removing `--frozen` from CI.
- If generated documentation is stale, remove `docs/_build` and rerun `just docs-check`.

Never paste complete connection URLs, secret keys, provider credentials, or environment dumps
into issues, pull requests, screenshots, or logs.

