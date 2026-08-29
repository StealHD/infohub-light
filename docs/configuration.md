---
layout: default
title: Configuration Guide
---

# Configuration Guide

Inteliscope has one current runtime: React served by FastAPI, a Worker, and optional Remote MCP on the FastAPI `/mcp` route. Configuration comes from environment variables, `data/config.json`, Service DB state, and the write-only SecretStore.

## Runtime topology

The only console entry points are:

```bash
uv run horizon-api
uv run horizon-worker
```

Docker Compose contains only `horizon-api` and `horizon-worker`. Feed and per-source schedules are evaluated by the Worker; there is no scheduler profile, CLI publisher, static-site writer, local stdio MCP, or UI-variant switch.

React is the only UI. When `src/ui/service_static/index.html` is absent, the API and `/mcp` still start and non-API pages return 404.

### Fast local development preview

For backend/frontend iteration without rebuilding Docker, stop both canonical containers before pointing host processes at the canonical `data/service.db`; two code revisions must not write the same SQLite database concurrently. Start the current Worktree API on an alternate loopback port with `HORIZON_REQUIRE_WORKER_FOR_READINESS=false` and do not start the Worker or scheduler. The Vite development server accepts `VITE_API_PROXY_TARGET` and defaults to the canonical `http://127.0.0.1:8080` when it is absent:

```bash
# API example: 127.0.0.1:18080, using the current Worktree source and root .env
python -m src.api.server --host 127.0.0.1 --port 18080 \
  --data-dir /absolute/runtime/data --log-dir /absolute/preview/logs

# React example: 127.0.0.1:15173 -> preview API
VITE_API_PROXY_TARGET=http://127.0.0.1:18080 npm run dev -- --port 15173
```

Use an SQLite backup copy instead when the canonical containers must remain available. A preview never starts the Worker, notifications, scheduled acquisition, maintenance Probe, or paid Actor operation. Rebuild the canonical `8080` API/Worker containers once, after source tests and preview API acceptance pass.

## Bootstrap authentication

A fresh database needs an initial Owner:

```bash
HORIZON_AUTH_USER=admin
HORIZON_AUTH_PASSWORD=replace-me
# or
HORIZON_AUTH_PASSWORD_HASH='pbkdf2_sha256$...'
```

Generate a hash without storing the password in shell history:

```bash
uv run python -m src.auth hash-password
```

Current session controls are:

```bash
HORIZON_AUTH_SECURE_COOKIE=true
HORIZON_AUTH_SESSION_TTL_SECONDS=604800
```

Service authentication is always enabled. Once an enabled database user exists, readiness no longer depends on bootstrap password variables.

## SecretStore

Real AI, Apify, Email, Webhook, and Telegram credentials are write-only and belong in ignored `data/secrets.env` through the administrative APIs. The file is atomically replaced with mode `0600`; SQLite stores only references, hashes, generations, and safe provider metadata.

Never put real keys, destination URLs, tokens, SMTP passwords, or chat IDs in `data/config.json`, source configs, logs, or Job payloads.

## `data/config.json`

Current global input includes:

- `ai`: provider/model selection, safe limits, and SecretStore references.
- `filtering`: acquisition and Feed windows plus thresholds still used by current production.
- `rsshub`: credential-free Base URL and controlled routing settings.
- `tags`: workspace taxonomy choices.
- `sources`: import input; after import, `source_catalog` and `user_subscriptions` are authoritative.

The config runtime is owned by `src/services/config_runtime.py`. `GET /api/config` never projects retired top-level blocks `email`, `webhook`, `premium_analysis`, or `article_graph`. If an existing operator file contains those blocks, they remain untouched on disk but are not executed, returned, or rewritten by current config actions.

## Source acquisition and limits

Service jobs are user-scoped. Optional shared acquisition may reuse neutral content for a public/workspace source within a freshness window; private sources, subscription projection, AI analysis, item state, and Feed snapshots are never shared.

```bash
HORIZON_SHARED_ACQUISITION_ENABLED=false
HORIZON_SHARED_ACQUISITION_MIN_TTL_MINUTES=5
HORIZON_SHARED_ACQUISITION_MAX_TTL_MINUTES=60
HORIZON_SHARED_ACQUISITION_FALLBACK_TTL_MINUTES=30
```

Daily guardrails use the `INFOHUB_*` limits documented in `.env.example`, including per-user fetch/subscription limits and workspace/provider AI/fetch attempt limits. Network retries consume attempts; cache hits do not.

Source tests are always bounded and run through `src/services/source_probe.py`; they do not publish a Feed snapshot. Paid Actor tests require their dedicated confirmation and budget contracts.

## AI

AI settings refer to a SecretStore Key; they never contain the real value. `analysis_mode=personal_only` content enters history and personal Feed but skips AI, featured selection, and notification delivery.

The Service uses current source data only and applies bounded input/output limits. A model failure falls back to captured source summary/body/title according to the API contract; no old daily-summary publisher runs.

## Notifications

Current notifications are Service DB features, not the retired notifier chain:

- Workspace Email and Telegram transport credentials are managed by Owner/Admin.
- Notification services bind a single Email, Webhook, or Telegram destination.
- Users opt in globally, select visible services, and opt in per subscription.
- The Worker stages delivery only after a committed Feed result and sends outside the Feed transaction.

Legacy `data/config.json.email` and `.webhook` blocks are inert and are never used as fallback transport configuration.

## Worker schedules

The Worker evaluates both user Feed schedules and subscription source schedules:

```bash
HORIZON_SCHEDULE_POLL_SECONDS=30
```

Schedules create ordinary `user_feed_refresh` or `source_fetch` Jobs and reuse queue de-duplication, quota, Source Health, Feed finalization, and notification outbox rules. They never start another process or read legacy files.

## Feed storage and retention

`data/service.db` is the current data store. `FeedReadService` requires a `ServiceStore` and provides latest/history/search without a filesystem fallback. Snapshot readers retain compatibility with existing Service DB storage-v1/full payloads and storage-v2 compact payloads.

Compact writes require both the flag and the Feed storage v3 marker:

```bash
HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED=true
uv run python scripts/migrate_feed_storage_v3.py --dry-run --data-dir data
uv run python scripts/migrate_feed_storage_v3.py --apply --data-dir data --backup-dir data/backups
```

Explicit migrations require stopped API/Worker where their runbook says so, a `0600` SQLite backup, and integrity/foreign-key checks. Application startup does not perform destructive migrations.

Fresh databases do not create a feedback table. Existing feedback tables and rows are excluded from initialization, Feed v2 migration, and local reset operations.

## Current cold archives

Current cold storage is owned by `StorageGovernanceService` and lives under private `data/archives/**`. Owner/Admin operations use preview/apply plans and checksummed archives; Feed search can match retained cold metadata. This feature is unrelated to the retired `/api/archive/*` analytics routes.

## Remote MCP and OpenClaw

```bash
HORIZON_REMOTE_MCP_ENABLED=false
HORIZON_REMOTE_MCP_PUBLIC_URL=http://127.0.0.1:8080/mcp
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false
HORIZON_REMOTE_MCP_SYSTEM_SETTINGS_WRITES_ENABLED=false
HORIZON_OPENCLAW_CHAT_ENABLED=false
HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789
```

`/mcp` is the only MCP server. It uses delegation tokens and the same ServiceStore boundaries as REST. Subscription management and Owner/Admin system management use separate connections and separate default-off write flags.

## Workspace system settings

Global schema 32 adds typed workspace overrides for 21 safe capacity, Job,
retention, storage and shared-acquisition settings. Resolution is database
override, then the documented environment variable, then the compiled default.
Owner/Admin may use `/settings/system` or an explicitly created system-management
MCP connection; both require preview, the exact confirmation phrase and a
generation compare-and-swap. Secrets, endpoints, database paths, Actor cost or
activation, and arbitrary environment names are excluded.

Fresh databases create schema 32 automatically. For an existing database, first
apply the required ActorOps global 31 migration, then stop API and Worker,
preview, and explicitly apply with a private backup:

```bash
python scripts/migrate_system_settings_v32.py --data-dir data
python scripts/migrate_system_settings_v32.py --data-dir data --apply
```

## ActorOps stability and maintenance

Global schema 33 (`actorops_v2_stability`) is the current ActorOps online gate
and requires a valid global 32. Existing databases must stop API and Worker,
preview the migration, then explicitly apply it with a private backup:

```bash
python scripts/migrate_actorops_v2_stability.py --data-dir data
python scripts/migrate_actorops_v2_stability.py --data-dir data --backup-dir data/backups --apply
```

The apply step installs source-circuit state, maintenance authorization origin,
and the exact-Candidate presentation sidecar in one transaction. It validates
the marker, schema shape, integrity, and foreign keys; a partial schema or an
occupied version 33 fails closed, and a failed apply restores the `0600`
backup. It performs no network request, Actor/AI call, or cost mutation.

Fresh policies and existing untouched `generation=1` workspace/Route policies
are enabled with `authorization_origin=system_default`. A policy previously
changed by an operator keeps its explicit enabled/disabled state. Effective
maintenance still requires both policies, an enabled Owner/Admin principal,
the existing daily/monthly limits, one unsettled Probe limit, and finalized
cost evidence. Maintenance Probes use the `validation` credential and Run-ledger
purpose, preferring a dedicated validation key and retaining the existing safe
Key Pool fallback when one is not configured. Route `auto_replace_non_last` is disabled; maintenance may add a
safe Standby or set a source preference, but Primary/Standby replacement stays
an explicit, confirmed administrator action. Authorization, cost settlement,
and Discovery completion wake blocked Repair records without erasing their
attempt or cost facts.

An Owner/Admin may explicitly queue a Recovery Probe for an assigned
`confirmed_failure` probationary or certified Candidate through
`POST /api/admin/apify-routes/{route_id}/v2-candidates/{candidate_id}/recovery-probe`.
The request uses the fixed confirmation `确认实测恢复 Actor`, a safe idempotency
key, and frozen Route/Candidate/Binding generations plus `last_failure_at`.
The Probe keeps the same `$0.05`, one-start, one-item, daily/monthly, and
single-unsettled-Probe limits. Only a later settled `valid_nonempty` observation
atomically restores Candidate and source-circuit health; it never changes the
assignment or publishes Feed content.

Avatar presentation mapping is optional and keyed by exact Candidate, Build,
and output-Schema hash. The sidecar stores only a validated JSON pointer,
evidence kind, status, generation, and timestamps. It never stores or projects
the observed URL or raw Actor output. Manifest and Schema pointers are
revalidated against successful target-bound rows and may be atomically degraded
or replaced. Traversal is bounded to mapping objects that pass the core identity
and content contract, and prioritizes the selected identity scope so metadata,
third-party objects, and large scalar-heavy rows cannot pollute discovery.
Instagram coauthor rows may be normalized only when the bounded coauthor list
exactly identifies the requested profile; the in-memory copy removes all
normalized avatar aliases from third-party `user`/`owner` containers. A direct
target avatar wins, while an exact matched coauthor avatar is the only allowed
collaboration-only fallback. The raw Dataset is never rewritten. A normal
acquisition may retain its proof-bound URL only inside the private snapshot
diagnostics for that freshness window, allowing a cache hit to retry a failed
media download; item JSON, Feed, public Job diagnostics, Admin APIs, and logs do
not receive it. Missing presentation data cannot turn a valid paid content
result into a failure.

## Container build identity and local migration flow

Run `./scripts/up-latest.sh` from the Worktree being verified. It resolves
`.env`, `data`, and `logs` from the primary checkout through Git's common
directory, then hashes HEAD, tracked changes, and untracked files. Dirty local
revisions include that digest, the image carries the same source-digest label,
and the script rejects source changes during the build. Readiness requires the
expected API revision/version, API and Worker container health, both image
source digests, and a served React asset.

When the target revision reports migration-required, `up-latest.sh` confirms
the response belongs to that revision, stops API and Worker, prints the exact
offline migration command, and exits. It never applies a migration implicitly.
After preview/apply, rerun the same Worktree command. Do not substitute a
temporary Compose override, runtime symlink, or image built from a different
checkout.

Formal VPS releases require a clean `main` equal to `origin/main`, build the
pinned-base `linux/amd64` image locally, verify revision and source digest, and
transfer an archive for `docker load`; the VPS never builds this repository.
Remote packaging blocks when disk usage is above 85% or free space is below
8 GiB and prints a read-only cleanup inventory without deleting operator data.

## Retired-data boundary

The current runtime does not read, migrate, rewrite, or delete:

- `data/site/**`
- `data/horizon.db`
- old summaries
- old local MCP runs
- existing legacy feedback rows

These are operator-owned inert artifacts. Removing them from disk is a separate, explicitly authorized data-retention task. `.gitignore` and `.dockerignore` may continue protecting those paths.

## Verification

After configuration or runtime changes:

```bash
python scripts/test_gate.py run --mode full
python scripts/test_gate.py run --mode release
```

The gates do not run real sources, AI, paid Actors, notification sends, or a scheduler.
