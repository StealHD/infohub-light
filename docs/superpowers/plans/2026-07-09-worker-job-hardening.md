# Worker Job Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加固 InfoHub Light 小团体任务系统：SQLite job lease、stale running 恢复、失败重试退避、任务取消、结果保留清理、任务 API/UI 状态展示，并保持现有订阅控制台和 Docker 本地环境可用。

**Architecture:** 继续使用现有 FastAPI + SQLite `service.db` + 单进程 Worker loop，不引入 Redis/Celery。`src/services/job_queue.py` 负责所有任务状态机和 SQL，`src/services/worker.py` 只负责任务执行编排，`src/api/server.py` 只做权限和 API envelope，静态订阅控制台通过 `/api/jobs/*` 展示和操作任务。

**Tech Stack:** Python 3.11+、FastAPI、SQLite、pytest、vanilla JavaScript、Docker Compose light profile。

## Global Constraints

- 不引入 Redis/Celery/Postgres，本阶段仍使用 SQLite job table。
- Web 请求只创建、取消、重试或查询 job，不执行长耗时抓取。
- 任务状态必须通过 `JobQueue` 管理，API 和 Worker 不得散落手写 SQL。
- `viewer` 只能查看 jobs，不得取消、重试或创建任务。
- 现有 job 类型继续保持：`source_test`、`source_fetch`、`user_feed_refresh`。
- 失败响应继续使用统一 envelope：`{"ok": false, "error": {"code", "message", "retryable", "action"}}`。
- Docker light 下 `horizon-api` 必须继续 healthy，`horizon-worker --once` 必须可运行。
- 不做分布式队列，不做多 workspace，不做自动 scheduler 默认开启。

---

### Task 0: Checkpoint Current Subscription Console State

**Files:**
- Read: `git status --short`
- Read: `WORKLOG.md`

**Interfaces:**
- Consumes: 已完成但尚未提交的 multi-user core、配置兼容层、订阅控制台改动。
- Produces: 开工前基线确认；不自动 commit，除非用户明确授权。

- [ ] **Step 1: Inspect current branch and worktree**

Run:

```bash
git branch --show-current
git status --short
```

Expected: branch is `feature/multi-user-mvp-core`; worktree contains previous multi-user and subscription-console changes.

- [ ] **Step 2: Run baseline verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_service_store.py tests/test_job_queue.py tests/test_worker.py tests/test_static_reading_ui.py -q
node --check src/ui/static/*.js
git diff --check
```

Expected: all pass before Worker hardening edits.

### Task 1: Extend Fetch Job Schema for Lease and Retention

**Files:**
- Modify: `src/storage/service_store.py`
- Modify: `tests/test_service_store.py`

**Interfaces:**
- Consumes: existing `fetch_jobs` table.
- Produces new fetch job columns readable through `ServiceStore._job(row)`:
  - `max_attempts: int`
  - `next_run_at: str | None`
  - `locked_until: str | None`
  - `cancelled_at: str | None`
  - `expires_at: str | None`
- Produces updated `JOB_STATUSES = {"queued", "running", "succeeded", "failed", "partial", "cancelled"}`.

- [ ] **Step 1: Write failing schema migration test**

Add to `tests/test_service_store.py`:

```python
def test_service_store_migrates_fetch_jobs_for_worker_hardening(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()

    columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(fetch_jobs)").fetchall()
    }

    assert "max_attempts" in columns
    assert "next_run_at" in columns
    assert "locked_until" in columns
    assert "cancelled_at" in columns
    assert "expires_at" in columns
```

Run:

```bash
.venv/bin/python -m pytest tests/test_service_store.py::test_service_store_migrates_fetch_jobs_for_worker_hardening -q
```

Expected: FAIL because columns do not exist.

- [ ] **Step 2: Implement schema columns**

In `src/storage/service_store.py`, update `JOB_STATUSES`:

```python
JOB_STATUSES = {"queued", "running", "succeeded", "failed", "partial", "cancelled"}
```

In the `CREATE TABLE IF NOT EXISTS fetch_jobs` block, add:

```sql
max_attempts INTEGER NOT NULL DEFAULT 3,
next_run_at TEXT,
locked_until TEXT,
cancelled_at TEXT,
expires_at TEXT,
```

Add helper:

```python
def _ensure_column(self, table: str, column: str, definition: str) -> None:
    existing = {
        row["name"]
        for row in self.connect().execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        self.connect().execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
```

After `conn.executescript(...)` in `initialize()`, call:

```python
self._ensure_column("fetch_jobs", "max_attempts", "INTEGER NOT NULL DEFAULT 3")
self._ensure_column("fetch_jobs", "next_run_at", "TEXT")
self._ensure_column("fetch_jobs", "locked_until", "TEXT")
self._ensure_column("fetch_jobs", "cancelled_at", "TEXT")
self._ensure_column("fetch_jobs", "expires_at", "TEXT")
```

- [ ] **Step 3: Run schema tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_service_store.py -q
```

Expected: pass.

### Task 2: Implement Durable JobQueue State Machine

**Files:**
- Modify: `src/services/job_queue.py`
- Modify: `tests/test_job_queue.py`

**Interfaces:**
- Consumes:
  - `ServiceStore.connect()`
  - `ServiceStore._job(row)`
- Produces:
  - `JobQueue.create_job(..., max_attempts: int = 3, delay_seconds: float = 0, retention_days: int | None = None)`
  - `JobQueue.claim_next_job(worker_id: str, lease_seconds: float = 900)`
  - `JobQueue.fail_or_retry_job(job_id: str, error_code: str, error_message: str, retryable: bool = True, retry_base_seconds: float = 30)`
  - `JobQueue.requeue_stale_running_jobs(now: datetime | None = None) -> int`
  - `JobQueue.cancel_job(job_id: str, user_id: str | None = None) -> dict[str, Any]`
  - `JobQueue.retry_job(job_id: str, user_id: str | None = None) -> dict[str, Any]`
  - `JobQueue.prune_terminal_jobs(now: datetime | None = None) -> int`

- [ ] **Step 1: Write failing retry and lease tests**

Add to `tests/test_job_queue.py`:

```python
from datetime import datetime, timedelta, timezone


def test_job_queue_retries_failed_job_until_max_attempts(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=2,
    )
    claimed = queue.claim_next_job(worker_id="worker-1", lease_seconds=60)

    retried = queue.fail_or_retry_job(
        claimed["id"],
        error_code="RuntimeError",
        error_message="temporary failure",
        retryable=True,
        retry_base_seconds=0,
    )
    second_claim = queue.claim_next_job(worker_id="worker-1", lease_seconds=60)
    failed = queue.fail_or_retry_job(
        second_claim["id"],
        error_code="RuntimeError",
        error_message="final failure",
        retryable=True,
        retry_base_seconds=0,
    )

    assert retried["id"] == job["id"]
    assert retried["status"] == "queued"
    assert retried["attempts"] == 1
    assert second_claim["attempts"] == 2
    assert failed["status"] == "failed"
    assert failed["error_message"] == "final failure"


def test_job_queue_requeues_stale_running_jobs(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
    )
    claimed = queue.claim_next_job(worker_id="worker-1", lease_seconds=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    store.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        (past.isoformat(), claimed["id"]),
    )
    store.connect().commit()

    count = queue.requeue_stale_running_jobs()
    loaded = queue.get_job(job["id"])

    assert count == 1
    assert loaded["status"] == "queued"
    assert loaded["worker_id"] is None
    assert loaded["locked_until"] is None
```

Run:

```bash
.venv/bin/python -m pytest tests/test_job_queue.py::test_job_queue_retries_failed_job_until_max_attempts tests/test_job_queue.py::test_job_queue_requeues_stale_running_jobs -q
```

Expected: FAIL because methods/signatures do not exist.

- [ ] **Step 2: Implement create/claim lease fields**

In `src/services/job_queue.py`, import:

```python
from datetime import datetime, timedelta, timezone
```

Add:

```python
def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
```

Update `create_job()` signature:

```python
def create_job(
    self,
    *,
    workspace_id: str,
    user_id: str,
    job_type: str,
    payload: dict[str, Any] | None = None,
    source_id: str | None = None,
    subscription_id: str | None = None,
    priority: int = 0,
    max_attempts: int = 3,
    delay_seconds: float = 0,
    retention_days: int | None = None,
) -> dict[str, Any]:
```

Compute:

```python
now_dt = datetime.now(timezone.utc)
now = now_dt.isoformat()
next_run_at = (now_dt + timedelta(seconds=max(delay_seconds, 0))).isoformat()
expires_at = (now_dt + timedelta(days=retention_days)).isoformat() if retention_days else None
```

Insert `max_attempts`, `next_run_at`, `expires_at`.

Update `claim_next_job()` signature:

```python
def claim_next_job(self, *, worker_id: str, lease_seconds: float = 900) -> dict[str, Any] | None:
```

Select only available queued jobs:

```sql
WHERE status = 'queued'
  AND (next_run_at IS NULL OR next_run_at <= ?)
ORDER BY priority DESC, created_at
LIMIT 1
```

Set:

```sql
status = 'running',
attempts = attempts + 1,
worker_id = ?,
started_at = COALESCE(started_at, ?),
locked_until = ?,
updated_at = ?
```

- [ ] **Step 3: Implement retry/stale/cancel/prune methods**

Add:

```python
def fail_or_retry_job(
    self,
    job_id: str,
    *,
    error_code: str,
    error_message: str,
    retryable: bool = True,
    retry_base_seconds: float = 30,
) -> dict[str, Any]:
    current = self.get_job(job_id)
    if current is None:
        raise LookupError("job not found")
    now_dt = datetime.now(timezone.utc)
    should_retry = retryable and int(current["attempts"] or 0) < int(current.get("max_attempts") or 1)
    if should_retry:
        delay = max(float(retry_base_seconds), 0) * (2 ** max(int(current["attempts"] or 1) - 1, 0))
        next_run_at = (now_dt + timedelta(seconds=delay)).isoformat()
        self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET status = 'queued',
                worker_id = NULL,
                locked_until = NULL,
                next_run_at = ?,
                error_code = ?,
                error_message = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (next_run_at, error_code, error_message, now_dt.isoformat(), job_id),
        )
    else:
        self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET status = 'failed',
                worker_id = NULL,
                locked_until = NULL,
                error_code = ?,
                error_message = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (error_code, error_message, now_dt.isoformat(), now_dt.isoformat(), job_id),
        )
    self.store.connect().commit()
    updated = self.get_job(job_id)
    if updated is None:
        raise LookupError("job not found after update")
    return updated
```

Add:

```python
def requeue_stale_running_jobs(self, now: datetime | None = None) -> int:
    now_dt = now or datetime.now(timezone.utc)
    cur = self.store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'queued',
            worker_id = NULL,
            locked_until = NULL,
            error_code = 'lease_expired',
            error_message = 'Worker lease expired before completion',
            updated_at = ?
        WHERE status = 'running'
          AND locked_until IS NOT NULL
          AND locked_until < ?
        """,
        (now_dt.isoformat(), now_dt.isoformat()),
    )
    self.store.connect().commit()
    return cur.rowcount
```

Add:

```python
def cancel_job(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
    current = self.get_job(job_id)
    if current is None:
        raise LookupError("job not found")
    if user_id is not None and current["user_id"] != user_id:
        raise PermissionError("cannot cancel another user's job")
    if current["status"] != "queued":
        raise ValueError("only queued jobs can be cancelled")
    now = _now_iso()
    self.store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'cancelled',
            cancelled_at = ?,
            finished_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (now, now, now, job_id),
    )
    self.store.connect().commit()
    updated = self.get_job(job_id)
    if updated is None:
        raise LookupError("job not found after cancellation")
    return updated
```

Add:

```python
def retry_job(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
    current = self.get_job(job_id)
    if current is None:
        raise LookupError("job not found")
    if user_id is not None and current["user_id"] != user_id:
        raise PermissionError("cannot retry another user's job")
    if current["status"] not in {"failed", "partial", "cancelled"}:
        raise ValueError("only failed, partial, or cancelled jobs can be retried")
    now = _now_iso()
    self.store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'queued',
            attempts = 0,
            worker_id = NULL,
            locked_until = NULL,
            next_run_at = ?,
            cancelled_at = NULL,
            finished_at = NULL,
            error_code = NULL,
            error_message = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (now, now, job_id),
    )
    self.store.connect().commit()
    updated = self.get_job(job_id)
    if updated is None:
        raise LookupError("job not found after retry")
    return updated
```

Add:

```python
def prune_terminal_jobs(self, now: datetime | None = None) -> int:
    now_dt = now or datetime.now(timezone.utc)
    cur = self.store.connect().execute(
        """
        DELETE FROM fetch_jobs
        WHERE status IN ('succeeded', 'failed', 'partial', 'cancelled')
          AND expires_at IS NOT NULL
          AND expires_at < ?
        """,
        (now_dt.isoformat(),),
    )
    self.store.connect().commit()
    return cur.rowcount
```

- [ ] **Step 4: Run queue tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_queue.py tests/test_service_store.py -q
```

Expected: pass.

### Task 3: Use Retry and Lease Semantics in Worker

**Files:**
- Modify: `src/services/worker.py`
- Modify: `tests/test_worker.py`

**Interfaces:**
- Consumes:
  - `JobQueue.requeue_stale_running_jobs()`
  - `JobQueue.prune_terminal_jobs()`
  - `JobQueue.claim_next_job(worker_id, lease_seconds)`
  - `JobQueue.fail_or_retry_job(...)`
  - `JobQueue.complete_job(...)`
- Produces:
  - `run_worker_once(data_dir: str = "data", worker_id: str = "horizon-worker", lease_seconds: float | None = None, retry_base_seconds: float | None = None, retention_days: int | None = None)`

- [ ] **Step 1: Write failing worker retry test**

Add to `tests/test_worker.py`:

```python
def test_worker_retries_failed_job_before_final_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=2,
    )

    def failing_run_source_test(_payload):
        raise RuntimeError("temporary source failure")

    monkeypatch.setattr("src.services.worker.run_source_test", failing_run_source_test)

    first = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1", retry_base_seconds=0)
    second = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1", retry_base_seconds=0)

    assert first["id"] == job["id"]
    assert first["status"] == "queued"
    assert first["attempts"] == 1
    assert second["status"] == "failed"
    assert second["attempts"] == 2
    assert second["error_code"] == "RuntimeError"
```

Run:

```bash
.venv/bin/python -m pytest tests/test_worker.py::test_worker_retries_failed_job_before_final_failure -q
```

Expected: FAIL because `run_worker_once` does not accept retry options and currently fails immediately.

- [ ] **Step 2: Implement Worker options**

Update `run_worker_once` signature:

```python
def run_worker_once(
    *,
    data_dir: str = "data",
    worker_id: str = "horizon-worker",
    lease_seconds: float | None = None,
    retry_base_seconds: float | None = None,
    retention_days: int | None = None,
) -> dict[str, Any] | None:
```

Inside:

```python
lease = float(lease_seconds if lease_seconds is not None else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900"))
retry_base = float(
    retry_base_seconds if retry_base_seconds is not None else os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")
)
queue.requeue_stale_running_jobs()
queue.prune_terminal_jobs()
job = queue.claim_next_job(worker_id=worker_id, lease_seconds=lease)
```

Replace exception completion:

```python
except Exception as exc:
    return queue.fail_or_retry_job(
        job["id"],
        error_code=type(exc).__name__,
        error_message=str(exc),
        retryable=True,
        retry_base_seconds=retry_base,
    )
```

Leave success path:

```python
return queue.complete_job(job["id"], status="succeeded", result=result)
```

- [ ] **Step 3: Wire CLI env options**

In `main()`, add args:

```python
parser.add_argument("--lease-seconds", type=float, default=float(os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900")))
parser.add_argument("--retry-base-seconds", type=float, default=float(os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")))
```

Pass them to `run_worker_once(...)` in both `--once` and loop mode.

- [ ] **Step 4: Run worker tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker.py tests/test_job_queue.py -q
```

Expected: pass.

### Task 4: Add Job Cancel and Retry API

**Files:**
- Modify: `src/api/server.py`
- Modify: `tests/test_api_service.py`
- Modify: `API_CONTRACT.md`

**Interfaces:**
- Consumes:
  - `queue.cancel_job(job_id, user_id=...)`
  - `queue.retry_job(job_id, user_id=...)`
- Produces:
  - `POST /api/jobs/{id}/cancel`
  - `POST /api/jobs/{id}/retry`
  - `GET /api/jobs` accepts `limit`
  - `GET /api/dashboard/summary` includes `failed_job_count` and `running_job_count`.

- [ ] **Step 1: Write failing API tests**

Add to `tests/test_api_service.py`:

```python
def test_job_cancel_and_retry_api_respects_owner_permissions(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]

    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "queued"
    assert retried.json()["data"]["attempts"] == 0


def test_viewer_cannot_cancel_or_retry_jobs(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    )
    job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]
    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")

    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 403
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 403
```

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py::test_job_cancel_and_retry_api_respects_owner_permissions tests/test_api_service.py::test_viewer_cannot_cancel_or_retry_jobs -q
```

Expected: FAIL because endpoints do not exist.

- [ ] **Step 2: Implement API endpoints**

In `src/api/server.py`, add helper:

```python
def job_or_404(job_id: str, user: dict[str, Any]) -> dict[str, Any]:
    job = queue.get_job(job_id)
    if not job or job["workspace_id"] != user["workspace_id"]:
        raise ApiError("not_found", "job not found", status_code=404)
    if job["user_id"] != user["id"] and not _is_admin(user):
        raise ApiError("forbidden", "cannot access another user's job", status_code=403)
    return job
```

Refactor existing `GET /api/jobs/{job_id}` to use `job_or_404`.

Add:

```python
@app.post("/api/jobs/{job_id}/cancel")
async def jobs_cancel(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_mutating_member(user)
    job_or_404(job_id, user)
    try:
        return ok(queue.cancel_job(job_id, user_id=None if _is_admin(user) else user["id"]))
    except ValueError as exc:
        raise ApiError("job_not_cancelable", str(exc), status_code=409) from exc


@app.post("/api/jobs/{job_id}/retry")
async def jobs_retry(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_mutating_member(user)
    job_or_404(job_id, user)
    try:
        return ok(queue.retry_job(job_id, user_id=None if _is_admin(user) else user["id"]))
    except ValueError as exc:
        raise ApiError("job_not_retryable", str(exc), status_code=409) from exc
```

Update `jobs_list` signature:

```python
async def jobs_list(
    status: str | None = None,
    limit: int = 50,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
```

Pass `limit=max(1, min(limit, 200))`.

- [ ] **Step 3: Update API contract**

In `API_CONTRACT.md`, add:

```md
`POST /api/jobs/{id}/cancel` only cancels queued jobs. Running jobs are not force-killed in SQLite MVP and return `job_not_cancelable`.
`POST /api/jobs/{id}/retry` moves failed, partial, or cancelled jobs back to queued and resets attempts.
```

- [ ] **Step 4: Run API tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_job_queue.py -q
```

Expected: pass.

### Task 5: Improve Subscription Console Job UI

**Files:**
- Modify: `src/ui/static/subscriptions.js`
- Modify: `src/ui/static/subscriptions.css`
- Modify: `tests/test_static_reading_ui.py`

**Interfaces:**
- Consumes:
  - `GET /api/jobs?limit=20`
  - `POST /api/jobs/{id}/cancel`
  - `POST /api/jobs/{id}/retry`
- Produces:
  - job row displays `status`, `attempts/max_attempts`, `updated_at`, `error_message`
  - queued jobs show cancel button
  - failed/partial/cancelled jobs show retry button
  - viewer sees disabled mutation buttons.

- [ ] **Step 1: Write failing static contract test**

Add to `tests/test_static_reading_ui.py`:

```python
def test_subscription_console_job_controls_contract():
    subscriptions_js = STATIC_DIR.joinpath("subscriptions.js").read_text(encoding="utf-8")
    subscriptions_css = STATIC_DIR.joinpath("subscriptions.css").read_text(encoding="utf-8")

    assert "/api/jobs?limit=20" in subscriptions_js
    assert "/api/jobs/" in subscriptions_js
    assert "/cancel" in subscriptions_js
    assert "/retry" in subscriptions_js
    assert "cancelJob" in subscriptions_js
    assert "retryJob" in subscriptions_js
    assert "attempts" in subscriptions_js
    assert "max_attempts" in subscriptions_js
    assert "error_message" in subscriptions_js
    assert ".subscription-job-actions" in subscriptions_css
```

Run:

```bash
.venv/bin/python -m pytest tests/test_static_reading_ui.py::test_subscription_console_job_controls_contract -q
```

Expected: FAIL because UI does not include cancel/retry controls.

- [ ] **Step 2: Implement job action functions**

In `src/ui/static/subscriptions.js`, add:

```javascript
async function cancelJob(jobId) {
  if (!jobId) return;
  setSubscriptionMessage('正在取消任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '/cancel', { method: 'POST' });
    setSubscriptionMessage('任务已取消：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('取消任务失败：' + err.message, 'error');
  }
}

async function retryJob(jobId) {
  if (!jobId) return;
  setSubscriptionMessage('正在重试任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '/retry', { method: 'POST' });
    setSubscriptionMessage('任务已重新排队：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('重试任务失败：' + err.message, 'error');
  }
}
```

Update `loadJobsPreview()` to call:

```javascript
fetchSubscriptionApi('/api/jobs?limit=20&ts=' + Date.now())
```

- [ ] **Step 3: Render job attempts and actions**

Update `renderJobs(jobs)` row body:

```javascript
var canCancel = job.status === 'queued' && !subscriptionUserIsViewer();
var canRetry = ['failed', 'partial', 'cancelled'].indexOf(job.status) >= 0 && !subscriptionUserIsViewer();
```

Render:

```javascript
'  <span>' + escapeHtml(String(job.attempts || 0)) + ' / ' + escapeHtml(String(job.max_attempts || 1)) + '</span>',
'  <span>' + escapeHtml(formatDate(job.updated_at || job.created_at)) + '</span>',
job.error_message ? '  <span class="subscription-job-error">' + escapeHtml(job.error_message) + '</span>' : '',
'  <div class="subscription-job-actions">',
canCancel ? '    <button type="button" data-cancel-job="' + escapeHtml(job.id) + '">取消</button>' : '',
canRetry ? '    <button type="button" data-retry-job="' + escapeHtml(job.id) + '">重试</button>' : '',
'  </div>',
```

In `bindSubscriptionEvents()`, add click handlers for `[data-cancel-job]` and `[data-retry-job]`.

- [ ] **Step 4: Add CSS**

In `subscriptions.css`, add:

```css
.subscription-job-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.subscription-job-actions button {
  min-height: 28px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}

.subscription-job-error {
  grid-column: 1 / -1;
  color: var(--red);
  overflow-wrap: anywhere;
}
```

- [ ] **Step 5: Run frontend checks**

Run:

```bash
node --check src/ui/static/*.js
.venv/bin/python -m pytest tests/test_static_reading_ui.py -q
```

Expected: pass.

### Task 6: Docker and Worker Runbook Updates

**Files:**
- Modify: `docker-compose.light.yml`
- Modify: `project-defaults.yaml`
- Modify: `API_CONTRACT.md`
- Modify: `ARCHITECTURE_CONTRACT.md`
- Modify: `PLAN.md`
- Modify: `WORKLOG.md`
- Modify: `tests/test_light_runtime_scripts.py`

**Interfaces:**
- Consumes: existing `horizon-worker` script.
- Produces documented env defaults:
  - `HORIZON_WORKER_LEASE_SECONDS=900`
  - `HORIZON_WORKER_RETRY_BASE_SECONDS=30`
  - `HORIZON_WORKER_POLL_SECONDS=5`
  - `HORIZON_JOB_RETENTION_DAYS=14`

- [ ] **Step 1: Write failing compose/script contract test**

Add to `tests/test_light_runtime_scripts.py`:

```python
def test_light_compose_documents_worker_hardening_defaults():
    compose = Path("docker-compose.light.yml").read_text(encoding="utf-8")
    defaults = Path("project-defaults.yaml").read_text(encoding="utf-8")

    assert "HORIZON_WORKER_LEASE_SECONDS" in compose
    assert "HORIZON_WORKER_RETRY_BASE_SECONDS" in compose
    assert "HORIZON_JOB_RETENTION_DAYS" in compose
    assert "worker_lease_seconds" in defaults
    assert "worker_retry_base_seconds" in defaults
    assert "job_retention_days" in defaults
```

Run:

```bash
.venv/bin/python -m pytest tests/test_light_runtime_scripts.py::test_light_compose_documents_worker_hardening_defaults -q
```

Expected: FAIL because defaults are not documented.

- [ ] **Step 2: Add compose env defaults**

In `docker-compose.light.yml`, under `horizon-worker.environment`, add:

```yaml
HORIZON_WORKER_LEASE_SECONDS: ${HORIZON_WORKER_LEASE_SECONDS:-900}
HORIZON_WORKER_RETRY_BASE_SECONDS: ${HORIZON_WORKER_RETRY_BASE_SECONDS:-30}
HORIZON_JOB_RETENTION_DAYS: ${HORIZON_JOB_RETENTION_DAYS:-14}
```

If `horizon-worker.environment` does not exist, add it under the worker service only.

- [ ] **Step 3: Add project defaults**

In `project-defaults.yaml`, add:

```yaml
worker_lease_seconds: 900
worker_retry_base_seconds: 30
job_retention_days: 14
```

- [ ] **Step 4: Update control docs**

In `API_CONTRACT.md`, update job rules with lease/retry/cancel/prune semantics.

In `ARCHITECTURE_CONTRACT.md`, update Job Boundary with:

```md
Worker claims use SQLite lease (`locked_until`). Expired running jobs are returned to queued before the next claim. Failed jobs retry until `max_attempts`, then become failed.
```

In `PLAN.md`, move Worker hardening into completed once implemented.

- [ ] **Step 5: Run control validation**

Run:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/init-pro/scripts/validate_project_controls.py" \
  --project-root . \
  --primary-config project-defaults.yaml \
  --output INIT_PRO_VALIDATION.md
```

Expected: `overall_status=PASS`.

### Task 7: End-to-End Verification

**Files:**
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: local `.env`, Docker light compose, current static UI.
- Produces: verified local run state on `http://127.0.0.1:8080/`.

- [ ] **Step 1: Run focused regression**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_service_store.py tests/test_job_queue.py tests/test_worker.py tests/test_static_reading_ui.py tests/test_light_runtime_scripts.py -q
node --check src/ui/static/*.js
git diff --check
```

Expected: all pass.

- [ ] **Step 2: Run worker once**

Run:

```bash
.venv/bin/python -m src.services.worker --once
```

Expected: exits cleanly when no runnable job exists, or processes one queued job and records terminal/queued retry state.

- [ ] **Step 3: Rebuild Docker API**

Run:

```bash
docker compose -f docker-compose.light.yml up -d --build horizon-api
docker compose -f docker-compose.light.yml ps horizon-api
```

Expected: `horizon-light-api` is healthy.

- [ ] **Step 4: Smoke API**

Run:

```bash
curl -i http://127.0.0.1:8080/api/auth/status
curl -i http://127.0.0.1:8080/api/dashboard/summary
```

Expected:
- `/api/auth/status` returns `{"ok":true,"data":{"authenticated":false,"user":null}}`.
- `/api/dashboard/summary` returns 401 unauthorized envelope when unauthenticated.

- [ ] **Step 5: Browser smoke**

In the in-app browser:

1. Open `http://127.0.0.1:8080/`.
2. Confirm login gate appears.
3. Login with local credentials.
4. Open `订阅`.
5. Click `刷新我的信息流`.
6. Confirm job row displays status, attempts, updated time, and action buttons.
7. Cancel a queued job and confirm status becomes `cancelled`.
8. Retry the cancelled job and confirm status becomes `queued`.

- [ ] **Step 6: Update worklog**

Append:

```md
### 2026-07-09 HH:MM Codex
- 任务：加固 Worker 和任务队列
- 读取文件：`src/services/job_queue.py`、`src/services/worker.py`、`src/api/server.py`、`src/ui/static/subscriptions.js`、相关测试、控制面文档
- 修改文件：列出实际修改文件
- 执行验证：列出 pytest、node、worker、docker、curl、browser smoke 结果
- 结果：job 支持 lease、stale running 恢复、失败重试退避、取消、重试和保留清理；订阅控制台可查看并操作任务
- 未解决问题：不做分布式队列；running job 不强杀，只依赖 lease 到期恢复
- 控制面变更：更新 API/架构/计划/defaults，记录 Worker job 状态机
```

## Out of Scope

- 不引入 Redis/Celery/Postgres。
- 不做多 Worker 分布式锁的强一致语义，只做 SQLite lease 级别恢复。
- 不强制终止已经运行中的 Python 抓取函数。
- 不做 scheduler 默认开启。
- 不做高级 source 类型表单迁移。
- 不做商业计费或多 workspace。

## Validation Bundle

Run before marking complete:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_service_store.py tests/test_job_queue.py tests/test_worker.py tests/test_static_reading_ui.py tests/test_light_runtime_scripts.py -q
node --check src/ui/static/*.js
git diff --check
.venv/bin/python -m src.services.worker --once
python3 "${CODEX_HOME:-$HOME/.codex}/skills/init-pro/scripts/validate_project_controls.py" \
  --project-root . \
  --primary-config project-defaults.yaml \
  --output INIT_PRO_VALIDATION.md
docker compose -f docker-compose.light.yml up -d --build horizon-api
curl -i http://127.0.0.1:8080/api/auth/status
curl -i http://127.0.0.1:8080/api/dashboard/summary
```

## Self-Review

- Spec coverage: covers Worker lease, stale running recovery, retry backoff, cancel, retry, retention, API/UI controls, Docker/defaults/docs/tests.
- Placeholder scan: no task uses TBD/TODO/fill later; all behavior has named files, commands, expected outcomes, and concrete snippets.
- Type consistency: status string is consistently `cancelled`; new job fields are `max_attempts`, `next_run_at`, `locked_until`, `cancelled_at`, `expires_at`; API endpoints use `/api/jobs/{id}/cancel` and `/api/jobs/{id}/retry`.
