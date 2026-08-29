# Configuration

All backend configuration is loaded by `ekumidayomi.core.settings.Settings`. Environment variables use the `EKUMIDAYOMI_` prefix. Application modules must consume the validated settings object and must not call `os.getenv()` directly.

## Local setup

From the repository root, create the untracked `.env` file.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```shell
cp .env.example .env
```

The example contains development-only placeholders. Review the database and Redis locations before starting the API, and never commit `.env`.

## Value format

- Boolean values use `true` or `false`.
- Durations are expressed in seconds.
- `ALLOWED_HOSTS` and `CORS_ORIGINS` use JSON arrays, including the double quotes around each item.
- PostgreSQL URLs must use the async SQLAlchemy `postgresql+asyncpg://` scheme.
- Secret values must be injected as plain environment values by the runtime secret boundary; they must not be committed or printed.

Example list values:

```text
EKUMIDAYOMI_ALLOWED_HOSTS=["api.example.com"]
EKUMIDAYOMI_CORS_ORIGINS=["https://shop.example.com"]
```

## Environment behavior

### Development

- Uses `DATABASE_URL`.
- May use HTTP and insecure cookies on a developer machine.
- Allows the explicit local frontend origin from `.env.example`.
- Uses obvious development-only credentials that must never be promoted.

### Test

- Uses `TEST_DATABASE_URL` through `Settings.active_database_url`.
- Rejects configuration when `TEST_DATABASE_URL` equals `DATABASE_URL`.
- Must point to disposable test data rather than the development database.

### Production

- Uses `DATABASE_URL`.
- Rejects debug mode.
- Requires secure cookies.
- Rejects wildcard or empty allowed-host policies.
- Rejects wildcard CORS origins.
- Rejects known placeholder secret keys.
- Requires production values to come from the deployment environment and its approved secret-management boundary.

## Settings reference

| Environment variable | Classification | Required in production | Purpose and behavior |
|---|---|---:|---|
| `EKUMIDAYOMI_APP_ENV` | Public | Yes | Selects the `development`, `test`, or `production` safety profile. |
| `EKUMIDAYOMI_APP_NAME` | Public | No | Reader-facing OpenAPI and service name. Defaults to `Ẹkúmidáyọ̀mí API`. |
| `EKUMIDAYOMI_DEBUG` | Public | No | Enables framework diagnostics. It must be `false` in production. |
| `EKUMIDAYOMI_API_PREFIX` | Public | No | Versioned API prefix. Defaults to `/api/v1`. |
| `EKUMIDAYOMI_SECRET_KEY` | Secret | Yes | Security key for later signing and authentication behavior. Placeholder values are rejected in production. |
| `EKUMIDAYOMI_ALLOWED_HOSTS` | Public | Yes | JSON array of accepted HTTP hostnames. Wildcards and empty lists are rejected in production. |
| `EKUMIDAYOMI_CORS_ORIGINS` | Public | When a browser frontend calls the API | JSON array of exact browser origins, including scheme and port. Wildcards are rejected in production. |
| `EKUMIDAYOMI_SECURE_COOKIES` | Public | Yes | Controls the cookie `Secure` requirement. It must be `true` in production. |
| `EKUMIDAYOMI_DATABASE_URL` | Secret | Yes | Async PostgreSQL URL for development and production. The password makes the complete URL sensitive. |
| `EKUMIDAYOMI_TEST_DATABASE_URL` | Secret | CI and test | Dedicated async PostgreSQL test URL. It must differ from `DATABASE_URL`. |
| `EKUMIDAYOMI_DATABASE_POOL_SIZE` | Public | No | Persistent SQLAlchemy connections per application process; range 1–50. |
| `EKUMIDAYOMI_DATABASE_MAX_OVERFLOW` | Public | No | Temporary connections allowed above the pool size; range 0–50. |
| `EKUMIDAYOMI_DATABASE_CONNECT_TIMEOUT_SECONDS` | Public | No | Bounded PostgreSQL connection timeout; greater than 0 and no more than 30 seconds. |
| `EKUMIDAYOMI_REDIS_URL` | Secret when credentials are embedded | Yes | Redis connection URL. Redis is not authoritative for durable commerce state. |
| `EKUMIDAYOMI_REDIS_CONNECT_TIMEOUT_SECONDS` | Public | No | Bounded Redis connection timeout; greater than 0 and no more than 30 seconds. |
| `EKUMIDAYOMI_REDIS_OPERATION_TIMEOUT_SECONDS` | Public | No | Bounded Redis command timeout; greater than 0 and no more than 30 seconds. |
| `EKUMIDAYOMI_CHECK_DEPENDENCIES_ON_STARTUP` | Public | No | When true, startup will fail if a required dependency cannot be reached. |

## Container entrypoint setting

`RUN_MIGRATIONS_ON_STARTUP` is consumed by `docker-entrypoint.sh`, not by the typed application
settings object. It defaults to `false`. Local Compose sets it to `true` for the single
development application container so the database reaches `head` before Uvicorn starts.

Production and multi-replica environments must set it to `false` and execute `alembic upgrade
head` exactly once in a separate release step. Running migrations concurrently from every API
replica is unsupported.

## Host and container database names

The `.env.example` URLs use `localhost` because they are intended for an API or Alembic command running directly on the developer machine.

When the API or Alembic runs inside Docker Compose, use Compose service names and container ports instead:

```text
EKUMIDAYOMI_DATABASE_URL=postgresql+asyncpg://ekumidayomi:development-only@postgres:5432/ekumidayomi
EKUMIDAYOMI_TEST_DATABASE_URL=postgresql+asyncpg://ekumidayomi:test-only@postgres-test:5432/ekumidayomi_test
EKUMIDAYOMI_REDIS_URL=redis://redis:6379/0
```

Do not copy container hostnames into a host-run `.env`; names such as `postgres` and `redis`
resolve only on the Compose network. `compose.yml` owns these service-name overrides while
`.env.example` remains host-oriented.

## HTTP security implications

- `ALLOWED_HOSTS` controls which `Host` headers the API accepts; it is not a CORS setting.
- `CORS_ORIGINS` controls which browser origins may make credentialed cross-origin requests; list exact origins rather than `*`.
- `SECURE_COOKIES=false` is acceptable only for local HTTP development. Production HTTPS requires `true`.
- `DEBUG` controls diagnostic behavior and must not be used as the sole switch for enabling production documentation URLs. Documentation exposure belongs to the application-factory and deployment decisions in later Sprint 0 issues.

## Production secret boundary

The production provider is not selected until S0-012. Regardless of provider, secrets must be injected at runtime from its managed secret facility or an equivalently reviewed system. Secrets must not be stored in the repository, `.env` files, container images, Compose files used for production, command history, logs, errors, or screenshots.

If a secret is exposed, rotate it immediately and invalidate credentials or sessions derived from it.

## Deferred provider settings

SMTP, payment, shipping, object-storage, and external analytics settings are intentionally absent from S0-003. Their owning sprints will add typed fields after each provider contract is approved. Do not invent or rely on undocumented environment-variable names before then.
