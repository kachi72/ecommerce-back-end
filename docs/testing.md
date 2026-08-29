# Testing

The test harness separates fast unit behavior from PostgreSQL-backed integration behavior. SQLite is not an approved substitute for PostgreSQL-specific constraints, transactions, schemas, or concurrency.

## Commands

- Run `just test-unit` for infrastructure-free unit tests.
- Start PostgreSQL and Redis with `just containers-up-deps` before integration tests.
- Run `just test-integration` for PostgreSQL-backed and Redis-compatible integration tests.
- Run `just test` for the complete suite and terminal plus HTML coverage reports.
- Pass additional pytest arguments after a command, such as `just test-unit "-q -x"`.

Integration tests use `EKUMIDAYOMI_TEST_DATABASE_URL`, never the development database URL. Each test receives a generated PostgreSQL schema, applies current SQLAlchemy metadata inside it, and drops the schema during teardown. A missing test database fails explicitly rather than skipping coverage.

## Coverage map

| Test layer | Current responsibility | Required infrastructure | Deferred responsibility |
|---|---|---|---|
| Unit | Domain-free settings, lifecycle helpers, dependency boundaries, safe failures, and deterministic utilities | None | Future domain rules and edge cases |
| API wiring | In-process FastAPI routing, dependency overrides, validation, status codes, and safe response shapes | None for unit fakes; PostgreSQL for integrated readiness | Authenticated customer/admin journeys |
| PostgreSQL integration | Real asyncpg behavior, isolated schemas, commits, metadata creation, readiness, and teardown | Dedicated test PostgreSQL only | Domain constraints, locking, retries, and concurrency |
| Redis-compatible fake | Deterministic decoded command behavior used by current services | None | Lua scripts, eviction behavior, failover, and real-Redis protocol details |
| Provider contract | Adapter request/response contracts and provider failure mapping | Provider sandbox or recorded contract boundary | Payment, email, shipping, analytics, and object-storage providers |
| Critical flow | Complete customer and administrator journeys across domains | Full isolated stack | Introduced with domain features and enforced before release |

## Test policy

- Default unit tests must not require PostgreSQL, Redis, SMTP, provider credentials, or internet access.
- Integration tests must use the dedicated test database and must never target development or production data.
- Fakes prove application behavior only for the commands they exercise; they do not prove real Redis deployment behavior.
- Tests that verify real Redis scripts, PostgreSQL locks, provider sandboxes, or full customer journeys must use explicit markers and dedicated infrastructure.
- Dependency overrides must be scoped and restored after each test.
- Test source files are excluded from application coverage calculations.
