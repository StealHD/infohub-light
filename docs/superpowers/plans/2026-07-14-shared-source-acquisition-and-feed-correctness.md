# Shared Source Acquisition and Feed Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make public/workspace sources perform at most one upstream acquisition per freshness window while preserving user-isolated projection, AI analysis, state, and Feed output, and fix the adjacent lifecycle, quota, snapshot, deduplication, and cache-key correctness gaps.

**Architecture:** Keep the existing API and user job types, add a shared acquisition coordinator/content pool beneath them, and split acquisition from user projection behind the existing orchestrator facade. Deliver three independently testable and reversible phases: P0 correctness/cost boundaries, P1 shared acquisition, and P2 Feed/AI consistency.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, React 19, TypeScript, Vitest.

## Global Constraints

- Keep the default deployment as one API process plus one Worker; do not add a dispatcher, cache service, or synchronous upstream call in an HTTP request.
- Share only normalized content from public/workspace sources. Keep private sources, user projections, item state, and AI cache isolated by workspace/user.
- Preserve existing `source_test`, `source_fetch`, and `user_feed_refresh` public job types.
- Preserve URL query parameters as part of canonical content identity.
- Use additive schema changes, dual-read compatibility, explicit backup-backed migrations, and feature flags for shared acquisition and compact snapshot writing.
- Write a failing test and verify the expected failure before each behavior change.

---

### Task 1: P0 lifecycle invalidation and Feed reconciliation

**Primary areas:** ServiceStore lifecycle transactions, job queue/Worker eligibility, Feed finalizer, lifecycle/API tests.

- [x] Add failing tests proving that disabling/deleting a subscription, disabling a source, disabling a user, or changing a user to viewer cancels every related queued manual and scheduled job.
- [x] Add failing race tests proving a running job invalidated before the network call performs no call, and a job invalidated during a call cannot update Feed or Source Health.
- [x] Implement a shared eligibility decision used at enqueue, immediately before a network attempt, and before claim-guarded finalization.
- [x] Make lifecycle mutations, schedule shutdown, and queued-job invalidation one SQLite transaction. Internally finalize invalidated running claims as `cancelled` with `error_code=job_invalidated`.
- [x] Reconcile the affected users' latest Feed without a network call: remove inactive provenance, preserve items with remaining active provenance, and create exactly one empty version when the last subscription disappears.
- [x] Run lifecycle, queue, Worker, schedule, Feed production, API, SQLite integrity, and foreign-key tests.

### Task 2: P0 disabled-source management and cost enforcement

**Primary areas:** Catalog API authorization, subscription UI/API client, quota/usage service, retry classification.

- [x] Add failing API/UI tests for manager access to disabled sources, re-enabling a disabled source, and member unsubscribe by subscription ID even when the source is disabled.
- [x] Add `GET /api/catalog/sources?include_disabled=true` for owner/admin only; make PATCH/DELETE authorization independent of enabled visibility; switch the UI to `DELETE /api/me/subscriptions/{id}`.
- [x] Add failing tests for the 100-enabled-subscription limit, the 1,000-AI-item daily limit, retry attempt charging, deterministic non-retryable errors, and concurrent workspace/provider quota admission.
- [x] Enforce existing source/AI limits. Meter each scraper/provider/AI network attempt atomically, including automatic and manual retries; cached AI results consume no attempt.
- [x] Default unknown exceptions to non-retryable. Retry only explicit retryable source issues, connection/timeouts, 429, and 5xx failures.
- [x] Add workspace/provider defaults of 100 fetch attempts/day and 1,000 workspace AI attempts/day, then run focused backend and frontend regression tests.

### Task 3: P1 shared acquisition schema and coordinator

**Primary areas:** Service schema/repository, new acquisition service, acquisition tests.

- [x] Add failing tests for one upstream call across two users, fresh cache reuse, TTL expiry, successful empty caching, configuration/secret invalidation, private isolation, waiting-job behavior, and stale lease recovery.
- [x] Add `source_acquisition_states`, `source_content_snapshots`, and `source_content_items` using additive initialization/migration logic.
- [x] Build acquisition keys from workspace, isolation scope, source ID/type, normalized network config, adapter-contract version, and secret-ref identity/version. Exclude projection/display fields.
- [x] Use workspace isolation for public/workspace sources and user isolation for private sources.
- [x] Derive freshness from the shortest active source/feed schedule, clamped to 5–60 minutes with a 30-minute fallback.
- [x] Implement claim-token guarded leases aligned to the 900-second Worker lease. Requeue waiters for five seconds without charging an attempt; apply existing exponential failure backoff capped at five minutes.
- [x] Store successful normalized items, including zero-item results, in the shared content tables and retain safe acquisition diagnostics only.

### Task 4: P1 acquisition/projection integration and rollout controls

**Primary areas:** Orchestrator/catalog runner/Worker integration, runtime metrics/configuration, multi-user tests.

- [x] Add failing integration tests showing `source_fetch` and `user_feed_refresh` reuse shared content while producing separate user snapshots and user-isolated analysis.
- [x] Extract acquisition and user projection components behind the existing orchestrator facade; keep all HTTP endpoints asynchronous.
- [x] Make normal production fetches respect freshness. Make `source_test` bypass successful production cache and avoid publishing to the content pool, while still using cost admission and same-source concurrency protection.
- [x] Add safe result/runtime counts for acquisition hits, misses, upstream attempts, invalidated jobs, and quota rejects.
- [x] Add `HORIZON_SHARED_ACQUISITION_ENABLED=false` plus min/max/fallback TTL configuration. Verify legacy behavior when disabled and shared behavior when enabled.
- [x] Run multi-user concurrency tests and controlled source smoke tests; do not run a paid real provider without explicit operator enablement and an item limit of one.

Automated fixture-backed source smoke and concurrency coverage passed. Real non-paid natural-cycle canaries remain Release Gate 2; no paid provider was invoked.

### Task 5: P2 canonical merge and no-op/compact Feed versions

**Primary areas:** Cross-source merger, Feed production/store/archive, Feed tests.

- [x] Add failing tests proving full and incremental updates merge the same normalized URL, preserve full provenance, keep distinct query URLs separate, and preserve a stable existing article ID.
- [x] Route full and incremental combined content through one canonical merger. Prefer the latest Feed article ID, then stable priority/source/native-ID ordering.
- [x] Add failing tests proving unchanged output reuses the latest snapshot, changed output creates a version, and last-unsubscribe reconciliation creates one empty version.
- [x] Add `content_hash` and `storage_version`; hash ordered public Feed content while excluding timestamps, job diagnostics, and live user state.
- [x] Return `snapshot_created=false` and the existing snapshot ID on a no-op result.
- [x] Store complete new items only in `user_feed_items`; keep metadata and featured/daily/personal ID sets in snapshot JSON. Dual-read legacy complete payloads and new compact payloads.

### Task 6: P2 retention, exact AI fingerprint, migration, and final verification

**Primary areas:** Worker maintenance service, AI prompt/cache, migration tool, contracts/defaults.

- [x] Add failing tests for hourly pruning, latest-record preservation, legacy/compact snapshot reads, exact rendered-prompt cache invalidation, user isolation, and retry-attempt diagnostics.
- [x] Retain Feed snapshots for 90 days and at most 100/user, source content for 7 days, AI cache for 30 days, usage for 90 days, jobs for 14 days, and delete expired sessions. Always preserve the latest required Feed/source record.
- [x] Hash the rendered system prompt, rendered bounded user prompt, model, analysis mode, runtime limits, and cache version; never persist prompt text.
- [x] Add `analysis_usage.provider_attempts`, while preserving existing usage fields.
- [x] Provide a `--dry-run/--apply` UTC-backup migration that adds/backfills snapshot hashes, applies retention, and runs SQLite integrity/foreign-key checks without rewriting legacy payload bodies.
- [x] Update API/Architecture contracts, project defaults, environment/configuration docs, PLAN, decision log, and WORKLOG.
- [x] Run focused pytest, frontend Vitest/typecheck/build, full pytest, migration dry-run on a database copy, `git diff --check`, integrity checks, and secret-leak scanning.

## Public Interface Decisions

- `include_disabled=true` is owner/admin-only; member/viewer receives `403 forbidden`.
- Invalidated jobs use terminal `cancelled`, `error_code=job_invalidated`, and a bounded `invalidation_reason`.
- Feed/source job results add `snapshot_created`, acquisition cache hit/miss counts, and upstream attempt counts; `analysis_usage` adds `provider_attempts`.
- Public/runtime output exposes aggregate counts only and never source config, prompt, user/source IDs, or secrets.
- Normal manual production fetches honor the shared freshness window; `source_test` remains the explicit upstream verification path.

## Release Gates

1. Release P0 independently after focused and full regression pass.
2. Deploy P1 additive schema with shared acquisition disabled, then enable non-paid public sources for two natural cycles before paid sources.
3. Validate paid sources only with explicit operator enablement and `maxItems=1`.
4. Deploy P2 dual-read/new-write behavior, run migration dry-run, take a UTC backup, then apply retention.
5. Roll back by disabling shared acquisition or compact writing; legacy user jobs/readers remain available and additive tables may remain idle.
