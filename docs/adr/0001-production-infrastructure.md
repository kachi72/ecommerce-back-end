# ADR 0001: Production infrastructure

- **Status:** Proposed
- **Date:** 2026-08-30
- **Decision owners:** Product owner and production operations owner — names required before acceptance
- **Related issue:** S0-012

## Context

Ẹkúmidáyọ̀mí needs a container-first production platform for a FastAPI modular monolith,
PostgreSQL, Redis, private product-media objects, secrets, logs, metrics, and repeatable releases.
The initial customer and administrator audience is in Nigeria. The platform should minimize
operational burden for a small team while preserving private dependency networking, horizontal
application scaling, point-in-time database recovery, and controlled rollback.

PostgreSQL remains authoritative for customers, stock, orders, payments, reviews, audits, jobs,
and durable analytics rollups. Redis owns only disposable acceleration and ephemeral
coordination state. Product media belongs in object storage; PostgreSQL stores its references and
metadata.

This ADR records a preferred direction. It does not create an Azure account, buy a service,
approve a budget, provision resources, or authorize production credentials.

## Known constraints and unresolved inputs

| Input | Current position | Acceptance requirement |
|---|---|---|
| Primary audience | Nigeria | Measure latency from realistic Nigerian fixed and mobile networks. |
| Launch traffic and catalogue size | Not supplied | Record expected and peak requests, workers, products, media volume, database size, and Redis working set. |
| Monthly budget | Not supplied | Approve low, expected, and high monthly totals for staging and production. |
| Team cloud experience | Not supplied | Name the operator and confirm that the selected platform is supportable by that person. |
| Compliance and data residency | Not reviewed | Record applicable privacy, payment, retention, residency, and audit obligations after legal review. |
| Availability target | Proposed 99.9% monthly service objective | Product and operations owners must approve the target and exclusions. |
| Recovery targets | Proposed RPO 15 minutes and RTO 4 hours | Approve or replace the targets and prove them with a timed restore rehearsal. |

No row with an unresolved acceptance requirement may be treated as approved by merging this ADR.

## Decision drivers

- Low operational burden for a small team.
- Acceptable measured latency for Nigerian customers and administrators.
- Managed PostgreSQL backups and point-in-time recovery.
- Private dependency connectivity and managed workload identity where supported.
- Immutable container releases with health probes, staged verification, and application rollback.
- Central secret storage, privacy-safe logs, metrics, dashboards, and alerts.
- Separate staging and production failure and credential boundaries.
- A launch-sized configuration that can scale without changing the application architecture.
- Transparent monthly cost, recovery targets, and named operational ownership.

## Research snapshot

The service claims below were rechecked against official documentation on 2026-08-30.

- Azure lists South Africa North as an availability-zone region.
- Azure Database for PostgreSQL Flexible Server lists South Africa North with zone-redundant HA,
  same-zone HA, and geo-redundant backup support.
- Azure App Service Premium v4 lists South Africa North with availability-zone support.
- Azure Managed Redis is the current managed Redis product and supports private endpoints.
- Azure Cache for Redis Basic, Standard, and Premium tiers retire on 2028-09-30. A new deployment
  must not select that retiring product.
- AWS operates the `af-south-1` Africa (Cape Town) region across three availability zones. RDS for
  PostgreSQL and ElastiCache are available there.

Azure service and SKU availability can differ by subscription and can change. The complete
proposed Azure bill of materials must still be verified in the official region matrix and the
target subscription before acceptance, especially Azure Managed Redis, private endpoints, and
the chosen sizes.

## Considered options

### Option A — Microsoft Azure managed platform

- Azure App Service for Linux Containers for the FastAPI image.
- Azure Database for PostgreSQL Flexible Server.
- Azure Managed Redis, not Azure Cache for Redis.
- Azure Blob Storage for private product media.
- Azure Key Vault for application secrets.
- Azure Container Registry for immutable application images.
- Application Insights, Azure Monitor, and Log Analytics for telemetry and alerts.

Advantages include one provider, managed identity integration, private-networking options,
managed PostgreSQL recovery, and a direct custom-container hosting model. Disadvantages include
region- and SKU-dependent features, greater cost for private networking and redundant instances,
preview limitations in some Azure Managed Redis features, and less runtime control than a
general container orchestrator.

### Option B — AWS managed platform

- Amazon ECS on Fargate for the FastAPI image.
- Amazon RDS for PostgreSQL.
- Amazon ElastiCache.
- Amazon S3 for private product media.
- AWS Secrets Manager and IAM roles for application secrets.
- Amazon ECR for immutable application images.
- Amazon CloudWatch for logs, metrics, dashboards, and alerts.

Advantages include a verified Cape Town region, broad managed-service depth, private VPC
networking, strong recovery features, and greater runtime control. Disadvantages include more
networking and deployment components, more infrastructure decisions for a small team, and a
steeper operational learning surface.

### Option C — Developer platform with external managed data

- Render or Fly.io for the application container.
- Provider or external managed PostgreSQL, Redis-compatible cache, and object storage.
- Platform secrets and observability supplemented by external services where required.

Advantages include the fastest initial setup and simplest developer experience. Disadvantages
include fragmented support and billing, service-specific regional gaps, inconsistent private
networking, weaker single-owner operational visibility, and a greater chance of a later platform
migration.

## Evaluation matrix

| Criterion | Azure managed platform | AWS managed platform | Developer platform plus managed data |
|---|---|---|---|
| Nigeria-focused region | Candidate South Africa North; complete SKU verification pending | Cape Town region and core data services verified | Varies by provider and service combination |
| Small-team operational effort | Medium-low | Medium-high | Low initially; medium when providers fragment |
| Private dependency networking | Strong, tier dependent | Strong through VPC services | Variable |
| Managed identity and secrets | Strong Azure-native integration | Strong IAM-native integration | Variable |
| PostgreSQL PITR and HA path | Strong | Strong | Provider dependent |
| Container release control | Moderate | Strong | Simple but platform dependent |
| Central observability | Strong | Strong | Often split across products |
| Cost predictability | Requires exact SKU calculator estimate | Requires exact service calculator estimate | Simpler entry pricing but fragmented growth cost |
| Vendor lock-in | Medium-high | Medium-high | Medium, plus cross-provider coupling |
| Migration risk at larger scale | Low-medium | Low | Medium-high |

## Proposed decision

Use Option A, the Azure managed platform, subject to every acceptance gate below.

The provisional primary region is **South Africa North** because it is the closest Azure region
candidate in this comparison and supports the core App Service and PostgreSQL capabilities.
Before acceptance, verify every exact service and SKU in the target subscription and record
latency measurements from Nigeria. If the complete stack, budget, or measured latency does not
pass, repeat the comparison with AWS `af-south-1` as the preferred fallback rather than silently
selecting a distant Azure region.

## Environment topology

- Create separate staging and production resource groups, application identities, App Services,
  PostgreSQL servers and databases, Redis instances, storage boundaries, secrets, telemetry
  workspaces, and configuration values.
- Do not copy production customer data into staging. Use generated or irreversibly sanitized
  fixtures.
- Use separate Azure subscriptions for production when approved governance and budget permit;
  otherwise enforce resource-group, identity, role, policy, and billing-alert boundaries.
- Share no database password, Redis credential, storage signing key, or application secret across
  environments.
- Staging validates the exact immutable image that is later promoted to production.

## Networking, ingress, and secrets

- Expose only the public HTTPS API through App Service ingress using the approved custom domain.
- Redirect or disable plain HTTP, require TLS 1.2 or later, configure exact trusted hosts, and
  configure exact browser CORS origins.
- Use App Service VNet integration for private outbound dependency access.
- Disable public network access for PostgreSQL and Azure Managed Redis after private endpoints,
  private DNS, migration-runner access, and emergency procedures are proven.
- Prefer private access for Blob Storage, Key Vault, and Container Registry where the selected
  tiers and deployment workflow support it.
- Inventory required outbound destinations for payment, email, shipping, and other adapters.
  Introduce egress filtering when those provider contracts are approved.
- Use managed identities for Container Registry pulls, Key Vault access, and supported service
  authentication. Grant narrowly scoped roles and avoid long-lived deployment credentials.
- Require named administrator identities, MFA, least privilege, and reviewed emergency access.
  Do not expose PostgreSQL or Redis as an administrative public endpoint.
- Store product media privately in Blob Storage. A future media adapter may issue short-lived,
  scoped access rather than making the storage account public.

## Runtime and scaling proposal

- Run one staging instance with autoscaling disabled.
- Run at least two production instances across zones when the chosen App Service plan, region,
  and approved budget support zone redundancy.
- Propose production autoscaling from two to four instances. Validate the range with load tests
  before launch.
- Record the selected App Service SKU's vCPU and memory per instance in this ADR before
  acceptance; do not deploy with an unpriced or implicit capacity assumption.
- Scale out after sustained CPU above 70%, memory pressure above 75%, or a breached agreed p95
  request-latency target. Scale-in must be conservative and must not occur during a deployment.
- Treat worker queue depth as an additional signal after the durable job system exists.
- Configure liveness at `/health/live` and readiness at `/health/ready`. Readiness removes an
  instance from traffic; a dependency outage alone must not cause a liveness restart loop.
- Allow at least 30 seconds for graceful shutdown and safe in-flight request completion.
- Fail a deployment when the new revision does not become ready within 10 minutes.
- Use warmed deployment slots or an equivalently controlled rollout so a healthy old revision
  remains available until the new revision passes readiness.
- Redis loss may reduce performance or invalidate ephemeral state according to later contracts,
  but must never lose orders, payments, stock, reviews, audits, or other durable records.

## Deployment and migrations

1. CI tests, scans, and builds one container image from a reviewed commit.
2. Push the image to Azure Container Registry with an immutable commit tag and record its digest.
3. Deploy that digest to staging without rebuilding it.
4. Run `alembic upgrade head` exactly once from a dedicated migration runner using the same image
   and private database access. Application containers set `RUN_MIGRATIONS_ON_STARTUP=false`.
5. Require staging readiness, migration integrity, and critical smoke tests.
6. Promote the already-tested digest to the production pre-production slot.
7. Run the approved production migration exactly once before traffic uses code that requires the
   new schema.
8. Require readiness and critical read-only verification, then perform the controlled traffic or
   slot switch.
9. Record the deployed digest, migration revision, actor, timestamps, and verification result.
10. On application failure, route traffic back to the previous healthy digest.
11. Use expand/migrate/contract sequencing for non-backward-compatible database changes. A
    migration downgrade is never the default rollback for data already written by a new version.

The S10 deployment pipeline must define the private migration-runner mechanism and ensure two
workflow retries cannot execute a non-idempotent migration concurrently.

## Observability and incident entry points

- Send structured application logs, App Service platform logs, request count, p50/p95/p99
  latency, 4xx/5xx rate, restart count, dependency latency, PostgreSQL capacity, Redis capacity,
  and deployment events to Azure Monitor and Log Analytics.
- Retain application and platform logs for a proposed 30 days initially. Security, audit, payment,
  and legal retention are separate decisions and may require longer protected storage.
- Provide one service-health dashboard and one commerce-reconciliation dashboard when the
  underlying business metrics exist.
- Alert on sustained 5xx rate above 2% for 5 minutes, readiness failure for 5 minutes, p95 API
  latency above the approved target for 10 minutes, PostgreSQL or Redis capacity above 80% for
  15 minutes, failed migration jobs, and repeated container restarts.
- Route alerts to a named primary operator and escalation contact. No alert is production-ready
  until a human owner and response path are recorded.
- Do not record passwords, cookies, tokens, full connection strings, raw payment details,
  sensitive request bodies, or unnecessary customer data.
- Start triage with the deployed digest, health endpoints, release/migration record, dependency
  metrics, and privacy-safe correlated logs.

## Data protection and recovery

- Enable encrypted PostgreSQL automated backups and point-in-time recovery.
- Configure at least 14 days of production PostgreSQL backup retention initially. The approved
  retention must remain within the selected service capability or add a reviewed long-term
  backup design.
- Propose an RPO of 15 minutes and an RTO of 4 hours. Azure documents a PostgreSQL Flexible
  Server PITR RPO below five minutes, while restore duration varies and can exceed four hours;
  therefore the RTO is a project target that must be demonstrated, not a provider guarantee.
- Perform and record a staging restore rehearsal before launch and at least quarterly after
  launch. Time the restore, validate migrations and critical queries, and record the resulting
  RPO and RTO.
- Test the exact private-network restore topology because PostgreSQL restore networking has
  public/private access constraints.
- Enable Blob Storage versioning or soft delete with a proposed 30-day recovery window, subject
  to the approved media-retention policy.
- Keep Redis rebuildable from durable sources where applicable. Redis receives no durable-data
  RPO and must not become a backup dependency.
- Name the person who reviews backup failures and the person authorized to initiate and validate
  a restore.

## Cost gate

Before acceptance, price the exact staging and production architecture with the official Azure
calculator in the selected region. Include App Service plans and instances, PostgreSQL compute,
storage, HA and backups, Azure Managed Redis, Blob Storage operations and egress, Key Vault,
Container Registry, private endpoints and networking, Application Insights and Log Analytics
ingestion/retention, bandwidth, support, tax, and growth headroom.

Record monthly **low**, **expected**, and **high** estimates, the currency and exchange-rate date,
assumed traffic/storage/log volumes, and the approved monthly ceiling. Reprice the AWS fallback
with equivalent availability and retention so the comparison is coherent. Do not provision
production resources without written budget approval.

## Consequences

The project gains one preferred managed operational surface, concrete security and release
boundaries, a nearby candidate region, and a coherent path to private dependencies and recovery.
It also accepts potential Azure-specific coupling and recurring costs for redundant application
instances, managed Redis, private endpoints, telemetry, backup retention, and managed data.

The proposal deliberately leaves infrastructure-as-code, cloud-account creation, deployment
automation, provider adapters, and production provisioning to separately estimated work after
acceptance. If the acceptance gates reject Azure, the documented AWS option must be evaluated
with the same capacity, recovery, security, and cost assumptions.

## Risks

- The complete Azure service/SKU set may not be available in South Africa North for the target
  subscription.
- Azure Managed Redis is clustered by default and some capabilities remain preview or
  SKU-dependent; key design and redis-py behavior must be compatibility-tested.
- Nigerian latency may not meet the product target even when the platform is hosted in South
  Africa.
- Two production instances, private endpoints, managed Redis, HA PostgreSQL, and telemetry may
  exceed the owner's budget.
- A nominal four-hour RTO may be missed without a measured restore procedure and trained owner.
- Unnamed alert, deployment, migration, backup, and incident owners create an operational gap
  even if the technology is available.
- Provider-specific configuration can increase migration cost if service boundaries leak into
  application code.

## Acceptance gates

- [ ] Product owner approves Azure as the provider and records the decision owner by name.
- [ ] Product owner approves low, expected, high, and maximum monthly budgets.
- [ ] Exact primary region and every required service, feature, and SKU are verified in the target
  subscription.
- [ ] Nigerian latency is measured from realistic fixed and mobile client locations and the
  target is approved.
- [ ] Launch traffic, database, Redis, media, and telemetry capacity assumptions are recorded.
- [ ] Availability target, RPO, RTO, backup retention, media retention, and restore cadence are
  approved.
- [ ] A staging restore rehearsal demonstrates the approved recovery targets.
- [ ] Production operations owner and escalation contact are named.
- [ ] Security/network owner approves ingress, private endpoints, DNS, egress, identity roles,
  and emergency access.
- [ ] Deployment, migration, rollback, alert, backup-review, restore, secret-rotation, cost-review,
  and incident-coordination owners are named.
- [ ] Legal/privacy owner records applicable Nigerian and customer-market obligations.
- [ ] Azure Managed Redis clustering and required command patterns are validated with the
  application client.

Change the ADR status to `Accepted` only after every box is complete and the named product and
operations owners approve the final text. Until then, this document is a proposal and production
provisioning remains blocked.

## Follow-up work after acceptance

- Define infrastructure as code for the approved staging and production topology.
- Implement the S10 immutable-image deployment and exactly-once migration pipeline.
- Add structured application logging, correlation, metrics, dashboards, and alert routing.
- Add automated dependency and container vulnerability scanning.
- Implement restore, Redis rebuild, migration failure, and application rollback runbooks.
- Create provider adapters for media, payment, email, shipping, and analytics only in their owning
  sprints.
- Review budget, capacity, regional availability, and recovery evidence before each release gate.

## References

- [Azure Cache for Redis retirement FAQ](https://learn.microsoft.com/azure/azure-cache-for-redis/retirement-faq)
- [Azure Managed Redis overview](https://learn.microsoft.com/azure/redis/overview)
- [Azure Managed Redis private endpoints](https://learn.microsoft.com/azure/redis/private-link)
- [Azure product availability by region](https://azure.microsoft.com/explore/global-infrastructure/products-by-region/)
- [Azure regions and availability zones](https://learn.microsoft.com/azure/reliability/regions-list)
- [Azure App Service custom containers](https://learn.microsoft.com/azure/app-service/configure-custom-container)
- [Azure App Service Premium v4 regions](https://learn.microsoft.com/azure/app-service/app-service-configure-premium-v4-tier)
- [Azure Database for PostgreSQL Flexible Server](https://learn.microsoft.com/azure/postgresql/flexible-server/overview)
- [Azure PostgreSQL backup and restore](https://learn.microsoft.com/azure/postgresql/backup-restore/concepts-backup-restore)
- [AWS regions](https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html)
- [Amazon RDS regional availability](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.RegionsAndAvailabilityZones.html)
- [Amazon ElastiCache guide](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/redis-ug.html)
