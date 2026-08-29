# Operations

This page describes the operational behavior implemented by the Sprint 0 application and
container baseline. Provider-specific production procedures remain pending ADR approval.

## Health endpoints

- `GET /health/live` is a process-only liveness check. It performs no PostgreSQL, Redis, or
  third-party request.
- `GET /health/ready` checks PostgreSQL and Redis. It returns `200` only when both dependencies
  respond and returns `503` with a safe `service_not_ready` response otherwise.

A platform should remove an unready instance from traffic. Liveness restarts should be reserved
for a process that cannot serve requests; a dependency outage alone should not create a restart
loop.

## Startup and shutdown

Startup validates typed settings, creates bounded PostgreSQL and Redis clients, and checks both
dependencies when `CHECK_DEPENDENCIES_ON_STARTUP` is enabled. A failed dependency check aborts
startup without exposing the private exception through the API.

Shutdown closes the Redis client and disposes the SQLAlchemy engine, including when application
lifespan exits through an error. Container termination must allow enough grace time for this
cleanup to complete.

The local Compose entrypoint may run migrations before starting one development application
container. Multi-replica and production deployments must disable startup migrations and execute
them exactly once as a separate release step.

## Basic incident checks

1. Confirm the deployed image identifier, release time, and environment without dumping secrets.
2. Check liveness and readiness separately to distinguish a process failure from a dependency
   failure.
3. Inspect privacy-safe application and platform logs around the first failure. The baseline
   currently relies on Uvicorn and platform logs; a structured application logging contract has
   not yet been added.
4. Check PostgreSQL reachability, connection saturation, and the current Alembic revision.
5. Check Redis reachability and latency while remembering that durable state belongs in
   PostgreSQL.
6. Compare the active configuration with the documented contract using redacted values.
7. Roll back the application image when release verification fails. Do not reverse a database
   migration unless its reviewed recovery procedure declares that downgrade safe.

## Dependency outages

- During a PostgreSQL outage, readiness fails and durable commerce writes must stop safely.
- During a Redis outage, readiness currently fails because Redis is a required runtime
  dependency. Future cache-specific degradation behavior must be introduced and tested by the
  feature that owns it.
- Third-party provider behavior is not part of the Sprint 0 runtime and must not be inferred from
  these health checks.

## Deployment decision gate

[ADR 0001](adr/0001-production-infrastructure.md) is proposed. It conditionally prefers an Azure
managed platform in South Africa North and retains AWS Cape Town as the primary fallback.
Production provisioning remains blocked until provider, region, SKU, latency, cost, capacity,
recovery, security, privacy, and ownership gates are approved.

Azure Cache for Redis must not be selected for a new deployment because it is on a published
retirement path. The proposal uses Azure Managed Redis and requires its region, SKU, private
networking, clustering, and application-client compatibility to be verified before acceptance.
