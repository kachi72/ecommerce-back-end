# Architecture

Ẹkúmidáyọ̀mí is a FastAPI modular monolith under `src/ekumidayomi`. The current Sprint 0
baseline supplies process lifecycle, configuration, PostgreSQL, Redis, health checks,
migrations, tests, containers, and delivery gates. Ecommerce domain behavior is introduced
only by its owning sprint.

## Package boundaries

- `api` owns HTTP routing and request/response translation. Business rules must remain outside
  route handlers.
- `api.v1` is the versioned application API boundary mounted at the configured `/api/v1`
  prefix. Operational health endpoints remain unversioned at `/health`.
- `core` owns validated settings, application construction, process lifecycle, and shared
  infrastructure helpers.
- `db` owns the shared SQLAlchemy metadata, async engine, sessions, and request dependencies.
- `auth` and `users` reserve identity boundaries for their owning sprint; they contain no
  implemented domain behavior yet.
- Future ecommerce packages own their models, services, repositories, policies, and tests.

Dependencies point inward: HTTP and infrastructure adapters may call application or domain
services, while domain code must not import FastAPI, Redis clients, or provider SDKs.

## Application lifecycle

`ekumidayomi.main:app` is constructed by `create_app`. Constructing the application validates
settings but does not open network connections. The FastAPI lifespan creates the PostgreSQL
engine and Redis client, optionally checks both dependencies, and closes both resources during
shutdown.

The factory accepts an explicit `Settings` instance so tests can build the real application
without reading a developer environment or contacting production systems.

## Data and cache responsibilities

PostgreSQL is authoritative for durable business data. Request-scoped SQLAlchemy sessions do
not commit automatically; the service that owns a transaction must decide when to commit.
Alembic is the only supported path for schema changes.

Redis stores only cache entries and ephemeral coordination state. A Redis outage may reduce
availability or performance, but Redis must never become the only copy of orders, inventory,
payments, reviews, or other durable commerce state.

## Health contract

- `GET /health/live` confirms that the process can serve a request and does not query external
  dependencies.
- `GET /health/ready` checks PostgreSQL and Redis and returns `503` with safe component states
  when either dependency is unavailable.

## External providers

Payment, email, shipping, analytics, and object-storage integrations are deferred to their
owning sprints. They must enter through explicit adapter boundaries so provider SDKs and
transport concerns do not leak into domain services.

See [ADR 0001](adr/0001-production-infrastructure.md) for the status of the production
infrastructure decision.

