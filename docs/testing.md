# Testing

The test harness separates fast unit behavior from PostgreSQL-backed integration behavior. SQLite is not an approved substitute for PostgreSQL-specific constraints, transactions, schemas, or concurrency.

## Commands

- Run `just test-unit` for infrastructure-free unit tests.
- Start PostgreSQL and Redis with `just containers-up-deps` before integration tests.
- Run `just test-integration` for PostgreSQL-backed and Redis-compatible integration tests.
- Run `just test` for the complete suite and terminal plus HTML coverage reports.
- Pass additional pytest arguments after a command, such as `just test-unit "-q -x"`.

Integration tests use `EKUMIDAYOMI_TEST_DATABASE_URL`, never the development database URL. Each test receives a generated PostgreSQL schema, applies current SQLAlchemy metadata inside it, and drops the schema during teardown. A missing test database fails explicitly rather than skipping coverage.

## Sprint 1 platform traceability

| Contract | Unit evidence | Infrastructure evidence |
|---|---|---|
| Shared types | `tests/unit/core/test_types.py`, `tests/unit/platform/test_boundaries.py` | Not required |
| Error envelope | `tests/unit/api/test_errors.py`, `tests/unit/api/test_platform_contracts.py` | Not required |
| Unit of work | `tests/unit/db/test_uow.py` | `tests/integration/test_uow.py` |
| ORM and migrations | `tests/unit/db/test_base.py`, `tests/unit/db/test_migrations.py` | `tests/integration/test_orm_conventions.py` |
| Transactional outbox | `tests/unit/outbox/` | `tests/integration/test_outbox.py` |
| Durable jobs | `tests/unit/jobs/` | `tests/integration/test_jobs.py`, `tests/integration/test_platform_concurrency.py` |
| Redis cache | `tests/unit/cache/` | `tests/integration/test_cache.py` |
| API conventions | `tests/unit/api/test_conventions.py` | Not required |
| Audit trail | `tests/unit/audit/` | `tests/integration/test_audit.py` |
| Observability | `tests/unit/api/test_observability.py` | Not required |
| Media storage | `tests/unit/storage/test_storage.py` | Provider contract deferred |

Unit tests must not open infrastructure connections. Integration tests use isolated PostgreSQL schemas and Redis key namespaces. Concurrency behavior is tested only against PostgreSQL and Redis, never SQLite or a mock lock implementation.

## Coverage map

| Test layer | Current responsibility | Required infrastructure | Deferred responsibility |
|---|---|---|---|
| Unit | Domain-free settings, lifecycle helpers, dependency boundaries, safe failures, and deterministic utilities | None | Future domain rules and edge cases |
| API wiring | In-process FastAPI routing, dependency overrides, validation, status codes, and safe response shapes | None for unit fakes; PostgreSQL for integrated readiness | Authenticated customer/admin journeys |
| PostgreSQL integration | Real asyncpg behavior, isolated schemas, commits, metadata creation, readiness, and teardown | Dedicated test PostgreSQL only | Domain constraints, locking, retries, and concurrency |
| Redis-compatible fake | Deterministic decoded command behavior used by current services | None | Lua scripts, eviction behavior, failover, and real-Redis protocol details |
| Provider contract | Adapter request/response contracts and provider failure mapping | Provider sandbox or recorded contract boundary | Payment, email, shipping, analytics, and object-storage providers |
| Critical flow | Complete customer and administrator journeys across domains | Full isolated stack | Introduced with domain features and enforced before release |

Cloud-provider compatibility remains unclaimed until a provider adapter passes a sandbox or recorded contract suite. The in-memory media adapter proves the application-facing storage contract only.

## Test policy

- Default unit tests must not require PostgreSQL, Redis, SMTP, provider credentials, or internet access.
- Integration tests must use the dedicated test database and must never target development or production data.
- Fakes prove application behavior only for the commands they exercise; they do not prove real Redis deployment behavior.
- Tests that verify real Redis scripts, PostgreSQL locks, provider sandboxes, or full customer journeys must use explicit markers and dedicated infrastructure.
- Dependency overrides must be scoped and restored after each test.
- Test source files are excluded from application coverage calculations.
