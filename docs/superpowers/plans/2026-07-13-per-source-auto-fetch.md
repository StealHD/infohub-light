# Inteliscope Per-Source Auto Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reliable subscription-level automatic `source_fetch` scheduling and configure `X · @thsottiaux` to retain at most one item every 30 minutes while the full Feed remains on its six-hour schedule.

**Architecture:** Add an additive `user_source_schedules` table and a focused `SourceScheduleService`. The existing Worker evaluates both user Feed schedules and source schedules before claiming ordinary jobs; scheduled source jobs reuse the existing queue, catalog runner, Feed v2 finalizer, source health, quota, and claim guards. API/UI expose only the current user's subscription schedule, and a bootstrap-safe local configuration step applies `fetch_limit=1` plus the 30-minute X schedule.

**Tech Stack:** Python 3.11+, FastAPI/Pydantic, SQLite/WAL, vanilla browser JavaScript/CSS, pytest, Node DOM behavior tests, Docker Compose.

## Global Constraints

- X alone runs every 30 minutes with `fetch_limit=1`; Apple, OpenAI, and Claude remain on the existing 360-minute full Feed schedule.
- Scweet requires upstream `max_items >= 100`; request 100 and enforce the one-item limit locally after parsing.
- Allowed source intervals are exactly `30, 60, 180, 360, 720, 1440` minutes.
- Reuse the existing API + Worker containers; do not call legacy scheduler, `HorizonOrchestrator.run()`, `LegacyPublisher`, static Feed files, notifications, summaries, or Graph publishing.
- At most one queued/running `source_fetch` may exist for a subscription; stale claims cannot finalize Feed, health, or schedule state.
- Never expose Apify keys in SQLite, API responses, job results, logs, DOM, docs, or Git diff.
- Do not modify VPS state. Do not commit or push.

---

### Task 1: Add the subscription schedule schema and projection

**Files:**
- Modify: `src/storage/service_store.py`
- Test: `tests/test_source_schedule.py`

**Interfaces:**
- Produces: SQLite table `user_source_schedules` keyed by `subscription_id`.
- Produces: `ServiceStore.get_source_schedule(subscription_id: str) -> dict[str, Any] | None`.

- [ ] **Step 1: Write failing additive-schema and cascade tests**

Create `tests/test_source_schedule.py` with a helper that creates an owner, private source, and subscription. Assert `PRAGMA table_info(user_source_schedules)` contains the exact design columns; assert the interval CHECK rejects `29`; delete the subscription and assert the schedule row cascades.

```python
def test_source_schedule_schema_is_additive_and_cascades(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _subscribed_owner(tmp_path, monkeypatch)
    columns = {
        row["name"] for row in store.connect().execute(
            "PRAGMA table_info(user_source_schedules)"
        ).fetchall()
    }
    assert columns == {
        "subscription_id", "workspace_id", "user_id", "source_id", "enabled",
        "interval_minutes", "next_run_at", "last_evaluated_at",
        "last_enqueued_at", "last_job_id", "last_skip_reason",
        "created_at", "updated_at",
    }
    store.delete_subscription(subscription["id"], user_id=owner["id"])
    assert store.get_source_schedule(subscription["id"]) is None
```

- [ ] **Step 2: Run the test and verify RED**

Run: `./.venv/bin/pytest tests/test_source_schedule.py::test_source_schedule_schema_is_additive_and_cascades -q`

Expected: FAIL because `user_source_schedules` and `get_source_schedule` do not exist.

- [ ] **Step 3: Add the table, index, and store projection**

Add the table in `ServiceStore.initialize()` after `user_feed_schedules`:

```sql
CREATE TABLE IF NOT EXISTS user_source_schedules (
    subscription_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
    interval_minutes INTEGER NOT NULL DEFAULT 60
        CHECK(interval_minutes IN (30, 60, 180, 360, 720, 1440)),
    next_run_at TEXT,
    last_evaluated_at TEXT,
    last_enqueued_at TEXT,
    last_job_id TEXT,
    last_skip_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE,
    FOREIGN KEY(last_job_id) REFERENCES fetch_jobs(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_user_source_schedules_due
    ON user_source_schedules(enabled, next_run_at);
```

Project booleans consistently with existing `_bool()` helpers.

- [ ] **Step 4: Run focused store tests**

Run: `./.venv/bin/pytest tests/test_source_schedule.py::test_source_schedule_schema_is_additive_and_cascades tests/test_service_store.py -q`

Expected: PASS.

### Task 2: Implement atomic source scheduling and job deduplication

**Files:**
- Create: `src/services/source_schedule.py`
- Modify: `src/services/job_queue.py`
- Test: `tests/test_source_schedule.py`
- Test: `tests/test_job_queue.py`

**Interfaces:**
- Produces: `SOURCE_ALLOWED_INTERVALS = (30, 60, 180, 360, 720, 1440)`.
- Produces: `SourceScheduleService.get_subscription_schedule(...)`.
- Produces: `SourceScheduleService.update_subscription_schedule(...)`.
- Produces: `SourceScheduleService.enqueue_due(now=None, limit=100)`.
- Produces: `JobQueue.create_source_fetch_if_absent(workspace_id, user_id, source_id, subscription_id, payload, priority, ...) -> tuple[dict, bool]`.

- [ ] **Step 1: Add failing lifecycle, validation, and concurrency tests**

Cover missing-row defaults, enable/change/disable time semantics, disabled subscription rejection, cancellation of queued scheduled jobs only, two SQLite connections competing for one due schedule, manual/automatic deduplication, and restart catch-up producing only one job.

```python
def test_two_connections_compete_for_one_due_source_schedule(tmp_path, monkeypatch):
    # Seed one due schedule, run SourceScheduleService from two independent
    # ServiceStore connections behind a Barrier, and assert one source_fetch.
    assert len(_active_source_jobs(final_store, subscription["id"])) == 1
```

- [ ] **Step 2: Run source schedule tests and verify RED**

Run: `./.venv/bin/pytest tests/test_source_schedule.py -q`

Expected: FAIL because the service and queue method are absent.

- [ ] **Step 3: Implement the minimal service and atomic queue path**

Follow `FeedScheduleService` transaction ownership and time normalization patterns. Build scheduled jobs with:

```python
payload = {
    "reason": "scheduled_source_fetch",
    "source_id": source_id,
    "subscription_id": subscription_id,
}
```

Use priority `-10`, the existing retry settings, and `QuotaService`. In one `BEGIN IMMEDIATE` transaction, re-read the subscription/source/user, reject viewer or disabled entities, detect a full refresh or same-subscription active source job, create at most one job, record quota, and move `next_run_at` exactly once.

- [ ] **Step 4: Run scheduling and queue tests**

Run: `./.venv/bin/pytest tests/test_source_schedule.py tests/test_job_queue.py tests/test_job_queue_reliability.py -q`

Expected: PASS with no duplicate active jobs.

### Task 3: Integrate source schedules into Worker execution and full refresh completion

**Files:**
- Modify: `src/services/worker.py`
- Modify: `src/services/feed_production.py`
- Modify: `src/services/source_schedule.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_source_schedule.py`
- Test: `tests/test_multi_user_feed_e2e.py`

**Interfaces:**
- Consumes: `SourceScheduleService.enqueue_due()` from Task 2.
- Produces: `SourceScheduleService.advance_after_full_refresh(user_id, source_outcomes, finished_at)`.

- [ ] **Step 1: Write failing Worker and refresh-reset tests**

Assert `run_worker_once(enqueue_schedules=True)` evaluates both schedule services before claim; an X-only scheduled job invokes only the selected catalog source; a full refresh outcome for X advances its plan by 30 minutes; and a full refresh without that subscription leaves the source schedule unchanged.

```python
def test_full_refresh_advances_participating_source_schedule(...):
    service.advance_after_full_refresh(
        user_id=owner["id"],
        source_outcomes=(successful_outcome,),
        finished_at=finished,
    )
    assert service.get_subscription_schedule(...)["next_run_at"] == (
        finished + timedelta(minutes=30)
    ).isoformat()
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `./.venv/bin/pytest tests/test_worker.py tests/test_source_schedule.py -q`

Expected: FAIL on missing source schedule evaluation/reset.

- [ ] **Step 3: Wire the services without creating a new runtime**

In `run_worker_once`, evaluate `FeedScheduleService(store).enqueue_due()` followed by `SourceScheduleService(store).enqueue_due()` before `claim_next_job`. After claim-guarded full refresh finalization, call the reset method inside the same transaction for each participating `subscription_id`. Preserve existing stale-token behavior and do not call the legacy publisher.

- [ ] **Step 4: Run Worker, production, and isolation tests**

Run: `./.venv/bin/pytest tests/test_worker.py tests/test_feed_production.py tests/test_source_schedule.py tests/test_multi_user_feed_e2e.py -q`

Expected: PASS; private-user item intersections remain zero.

### Task 4: Expose current-user source schedule APIs and runtime counts

**Files:**
- Modify: `src/api/server.py`
- Modify: `src/services/runtime_status.py`
- Test: `tests/test_api_service.py`
- Test: `tests/test_api_permissions_matrix.py`

**Interfaces:**
- Produces: `GET /api/me/subscriptions/{subscription_id}/schedule`.
- Produces: `PATCH /api/me/subscriptions/{subscription_id}/schedule`.
- Extends: `GET /api/ops/runtime` with `source_schedule_count`, `overdue_source_schedule_count`, and `next_source_scheduled_at`.

- [ ] **Step 1: Write failing API and permission tests**

Cover owner/admin/member self-only access, viewer read-only behavior, cross-user 404, invalid interval 400, disabled subscription 409, no secret/payload fields, and runtime aggregation without source names.

```python
response = client.patch(
    f"/api/me/subscriptions/{subscription_id}/schedule",
    json={"enabled": True, "interval_minutes": 30},
)
assert response.status_code == 200
assert response.json()["data"]["allowed_intervals"] == [30, 60, 180, 360, 720, 1440]
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `./.venv/bin/pytest tests/test_api_service.py tests/test_api_permissions_matrix.py -q`

Expected: FAIL only on the new routes/fields.

- [ ] **Step 3: Implement Pydantic request, response projection, and routes**

Add `SourceSchedulePatchRequest(enabled: bool | None, interval_minutes: int | None)`. Resolve the subscription first and return 404 unless `subscription.user_id == current_user.id`; apply `require_mutating_member` only to PATCH. Response includes schedule timestamps, safe last/active job summaries, Worker state, and allowed intervals.

- [ ] **Step 4: Run API and runtime tests**

Run: `./.venv/bin/pytest tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_feed_schedule.py tests/test_source_schedule.py -q`

Expected: PASS.

### Task 5: Add subscription-level controls to the existing editor

**Files:**
- Modify: `src/ui/static/subscriptions.js`
- Modify: `src/ui/static/subscriptions.css`
- Modify: `src/ui/static/state.js`
- Test: `tests/subscription_job_ui_behavior.test.cjs`
- Test: `tests/test_static_reading_ui.py`

**Interfaces:**
- Consumes: Task 4 schedule GET/PATCH routes.
- Produces: editor controls named `source_schedule_enabled` and `source_schedule_interval_minutes`.

- [ ] **Step 1: Add failing DOM behavior tests**

Assert opening a subscription editor loads its schedule, renders 30-minute and other allowed options, saves through the subscription-specific route, prevents viewer writes, and ignores stale responses after switching users/editors using the existing `user_id + action_generation` guards.

- [ ] **Step 2: Run Node tests and verify RED**

Run: `node --test tests/subscription_job_ui_behavior.test.cjs`

Expected: FAIL because per-source controls and requests are absent.

- [ ] **Step 3: Implement the controls using existing editor state**

Render a compact “自动抓取此来源” section. Keep the form read-only for viewer. Save ordinary subscription fields first, then PATCH schedule only when schedule fields changed; surface an error without losing saved subscription fields if schedule validation fails. Never render `secret_env`, Key values, or source payload.

- [ ] **Step 4: Run Node and static UI tests**

Run: `node --test tests/*.test.cjs && ./.venv/bin/pytest tests/test_static_reading_ui.py tests/test_subscription_job_ui_behavior.py -q`

Expected: PASS.

### Task 6: Apply and verify the local X configuration

**Files:**
- Modify: `scripts/bootstrap_local_sources.py`
- Modify: `tests/test_bootstrap_local_sources.py`
- Modify: `docs/dev/local-ai-secret-subscriptions-v1-implementation-report.md`

**Interfaces:**
- Consumes: `SourceScheduleService.update_subscription_schedule(...)`.
- Produces: idempotent local state with X `fetch_limit=1`, source schedule 30 minutes, and user Feed schedule 360 minutes.

- [ ] **Step 1: Change bootstrap expectations first**

Update the test to require:

```python
assert x_source["config"]["fetch_limit"] == 1
assert source_schedule["enabled"] is True
assert source_schedule["interval_minutes"] == 30
assert feed_schedule["interval_minutes"] == 360
```

- [ ] **Step 2: Run bootstrap test and verify RED**

Run: `./.venv/bin/pytest tests/test_bootstrap_local_sources.py -q`

Expected: FAIL on the old X limit and missing source schedule.

- [ ] **Step 3: Make bootstrap idempotently apply the new values**

Change only the X definition to `fetch_limit: 1`. Capture the returned X subscription ID and call the source schedule service with `enabled=True, interval_minutes=30`; preserve the existing 360-minute Feed schedule. Keep all secret values out of results and logs.

- [ ] **Step 4: Rebuild containers before mutating live local data**

Run: `docker compose -f docker-compose.light.yml up -d --build horizon-api horizon-worker`

Expected: API and Worker healthy; scheduler absent.

- [ ] **Step 5: Update live X config through safe local APIs/scripts**

Use the existing authenticated API or an idempotent script path that reads keys from `data/secrets.env` without printing them. Set `fetch_limit=1`, then run `source_test`, wait for terminal success, run one `source_fetch`, verify at most one X item merged, and only then enable the 30-minute schedule.

Expected: Apify console receives a Run; local Source Health becomes healthy or returns a new explicit non-permission error.

### Task 7: Full verification and implementation report

**Files:**
- Modify: `API_CONTRACT.md`
- Modify: `ARCHITECTURE_CONTRACT.md`
- Modify: `PLAN.md`
- Modify: `DECISION_LOG.md`
- Modify: `README.md`
- Modify: `README_zh.md`
- Create: `docs/dev/per-source-auto-fetch-v1-implementation-report.md`

**Interfaces:**
- Documents the final API, queue semantics, operational status, real Apify outcome, and remaining risks.

- [ ] **Step 1: Run syntax and focused checks**

Run:

```bash
./.venv/bin/python -m compileall -q src scripts tests
find src/ui/static -name '*.js' -print0 | xargs -0 -n1 node --check
node --test tests/*.test.cjs
./.venv/bin/pytest tests/test_source_schedule.py tests/test_worker.py tests/test_api_service.py tests/test_bootstrap_local_sources.py -q
```

Expected: all pass.

- [ ] **Step 2: Run the complete regression suite**

Run: `./.venv/bin/pytest -q`

Expected: all tests pass; total is not lower than the current 658-test baseline.

- [ ] **Step 3: Validate Compose and working-tree hygiene**

Run:

```bash
docker compose -f docker-compose.light.yml config >/dev/null
docker compose -f docker-compose.yml config >/dev/null
git diff --check
git diff | rg 'AIza|apify_api_' && exit 1 || true
```

Expected: Compose/diff checks pass and no real Key pattern appears.

- [ ] **Step 4: Perform local runtime acceptance**

Verify live/ready 200, Worker heartbeat under 35 seconds, no scheduler container, no stale running jobs, X schedule enabled at 30 minutes, full Feed schedule enabled at 360 minutes, and no duplicate active X job. Inspect the latest X job and Feed snapshot without printing source payload or secrets.

- [ ] **Step 5: Update documentation and report evidence**

Record exact test counts, container health, schedule timestamps, X source-test/fetch status, Source Health, item count, database `integrity_check`, foreign-key results, and any external Apify limitation. Do not commit or push.
