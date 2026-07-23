# Apify Key Pool Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one workspace-scoped Apify key pool the only Service credential source, drain every old-key Actor run before failover, and retry the logical fetch with the next key.

**Architecture:** Add additive schema-v8 pool/run state owned by a Service-layer coordinator. Keep raw values only in `SecretStore`, pin one secret to each remote run, and use a generation barrier so no replacement run starts until every old-generation run is terminal. Service API and React settings manage one ordered active/standby pool; legacy CLI config remains compatible behind a disabled rollout flag.

**Tech Stack:** Python 3.14, FastAPI, SQLite, httpx, React 19, TypeScript, TanStack Query, Vitest, pytest.

## Global Constraints

- Branch from local `main` in an ignored isolated worktree; never touch the existing dirty checkout.
- Do not call real Apify keys, paid Actors, AI, Worker loops, scheduler, or production.
- Trigger proactive failover when included monthly credits reach zero; generic 403/429 must not poison a key.
- Abort and confirm every known old-generation run before activating the next key.
- Keep tokens, account records, raw upstream errors, run IDs, and dataset IDs out of public API responses and logs.
- Keep `HORIZON_APIFY_KEY_POOL_ENABLED` disabled by default.

---

### Task 1: Add schema-v8 pool persistence and coordinator

**Files:**
- Create: `src/services/apify_key_pool.py`
- Modify: `src/storage/service_store.py`
- Test: `tests/test_apify_key_pool.py`

- [x] Add idempotent `apify_key_pool_state`, `apify_key_pool_members`, and `apify_actor_runs` schema plus v8 marker.
- [x] Seed existing Apify secret refs deterministically, preferring the most-referenced enabled source key.
- [x] Implement atomic ordered membership, generation reservation, draining, terminal run accounting, recovery-to-tail, and safe public projection.
- [x] Cover two-connection races, repeat initialization, exhaustion, recovery, and secret lifecycle guards.

### Task 2: Pin credentials and implement fail-closed Actor failover

**Files:**
- Modify: `src/scrapers/apify_client.py`
- Modify: `src/scrapers/apify_social.py`
- Modify: `src/orchestrator.py`
- Modify: `src/services/worker.py`
- Test: `tests/test_apify_social.py`, `tests/test_worker.py`

- [x] Pin start/poll/dataset/abort requests to one credential and preserve the remote run ID durably.
- [x] Classify only HTTP 402 and explicit quota errors as depleted; treat invalid-token, permission, rate-limit, and transport failures separately.
- [x] Drain every old-generation run through `/actor-runs/{runId}/abort`, confirm terminal status, and retry with each enabled key at most once.
- [x] Keep unknown POST outcomes blocked and reconcile registered nonterminal runs on later worker cycles.
- [x] Inject the pool into Service source tests, single-source fetches, and full Feed refreshes without changing legacy CLI behavior.

### Task 3: Keep schedules and shared acquisition consistent

**Files:**
- Modify: `src/services/source_acquisition.py`
- Modify: `src/services/source_schedule.py`
- Test: `tests/test_source_acquisition.py`, `tests/test_source_schedule.py`

- [x] Include pool generation in Apify acquisition fingerprints and reject stale-generation cache publication.
- [x] Skip blocked Apify source schedules until the earliest recovery time without suppressing non-Apify Feed work.

### Task 4: Add admin API and single-pool UI

**Files:**
- Modify: `src/api/server.py`
- Modify: `src/services/source_type_registry.py`
- Modify: `frontend/src/features/admin-heroui/HeroSettingsPage.tsx`
- Modify: `frontend/src/features/admin-heroui/HeroSubscriptionDialogs.tsx`
- Test: matching API and React tests.

- [x] Add admin-only pool GET, optimistic order PUT, and idempotent drain POST endpoints.
- [x] Auto-append new Apify secrets; guard active/draining rotation and deletion.
- [x] Reject new Apify source-level `secret_env` assignments while pool mode is enabled.
- [x] Render active/standby/draining/depleted/invalid state, accessible ordering controls, quota feedback, and pool-managed source copy without exposing internal identifiers.

### Task 5: Contracts and verification

**Files:**
- Modify: API/architecture/UI control contracts, decision/phase/default files, `tests/test_impact_map.json`, and `WORKLOG.md`.

- [x] Record schema, interface, rollout flag, safety barrier, and compatibility rules in their authoritative files.
- [x] Run focused backend/frontend tests, typecheck, lint, and build.
- [x] Run `python scripts/test_gate.py run --mode full`, control JSON validation, and `git diff --check`.
- [x] Confirm the diff contains no secret value and append one concise worklog entry.
