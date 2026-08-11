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
HORIZON_OPENCLAW_CHAT_ENABLED=false
HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789
```

`/mcp` is the only MCP server. It uses delegation tokens and the same ServiceStore boundaries as REST. The repository does not ship `horizon-mcp`, a local run store, or legacy fetch/AI/config tools.

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
