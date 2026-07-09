# Subscription Console MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 InfoHub Light 小团体订阅控制台 MVP：登录后提供公共源市场、我的订阅、私有源创建、任务状态与手动刷新入口，替换配置页的源管理主路径，并保留旧配置表单作为高级兼容入口。

**Architecture:** 继续使用现有 FastAPI + SQLite service DB + 静态 JS 架构，不迁移 React/Vite/Next。后端先补齐订阅控制台需要的 API 便利层和角色边界，前端新增一个轻量静态控制台视图，通过 `/api/*` 读取和写入 source catalog、user subscriptions、jobs。

**Tech Stack:** Python 3.11+、FastAPI、SQLite、pytest、vanilla JavaScript、Docker Compose light profile。

## Global Constraints

- 保持当前 `horizon-api` Docker 服务可启动，现有阅读页和配置页不能被破坏。
- 静态前端只能通过 `/api/*` 访问数据，不能直接依赖 `data/site/*.json` 或 `data/config.json`。
- 数据库只保存 `secret_env`/`secret_ref`，API 不允许返回真实密钥值。
- 第一版仍然是单 workspace，小团体管理员创建用户，不做自助注册。
- `owner/admin` 可以管理公共和 workspace 源；`member` 可以订阅公共源并创建 private 源；`viewer` 只能查看，不允许创建源、改订阅或创建抓取任务。
- Web 请求只创建 job，不直接执行长耗时抓取。
- 每个任务完成后运行对应测试，并在 `WORKLOG.md` 追加记录。

---

### Task 0: Checkpoint Current Multi-User Core

**Files:**
- Read: `WORKLOG.md`
- Read: `git status --short`

**Interfaces:**
- Consumes: 当前未提交的 multi-user core、config service API、login gate 改动。
- Produces: 一个清晰的 checkpoint，避免下一阶段订阅控制台改动和已完成服务内核混在一起。

- [ ] **Step 1: Inspect current status**

Run:

```bash
git status --short
```

Expected: 只确认工作区状态，不回滚任何用户或既有改动。

- [ ] **Step 2: Run current focused verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_static_reading_ui.py tests/test_auth.py -q
node --check src/ui/static/*.js
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Create a local checkpoint commit if the user approves committing**

Run only after explicit approval:

```bash
git add .
git commit -m "feat: add multi-user service core and auth gate"
```

Expected: commit succeeds; if the user does not want a commit, continue without this step.

### Task 1: Harden Subscription API Surface

**Files:**
- Modify: `src/api/server.py`
- Modify: `tests/test_api_service.py`
- Modify: `API_CONTRACT.md`

**Interfaces:**
- Consumes: `current_user`, `current_admin`, `visible_source_or_404`, `store.create_subscription`, `store.delete_subscription`, `queue.create_job`, `quota.ensure_job_allowed`.
- Produces:
  - `POST /api/catalog/sources/{source_id}/subscribe`
  - `DELETE /api/catalog/sources/{source_id}/subscription`
  - `DELETE /api/catalog/sources/{source_id}`
  - `POST /api/jobs/user-feed-refresh`
  - role rule: viewer is read-only for catalog/subscription/job mutations.

- [ ] **Step 1: Write failing API tests**

Add tests to `tests/test_api_service.py`:

```python
def test_member_can_subscribe_public_source(client, logged_in_member):
    source_id = create_public_source(client)
    response = client.post(f"/api/catalog/sources/{source_id}/subscribe")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["subscription"]["source_id"] == source_id


def test_viewer_cannot_mutate_subscriptions_or_jobs(client, logged_in_viewer):
    source_id = create_public_source_as_admin(client)
    assert client.post(f"/api/catalog/sources/{source_id}/subscribe").status_code == 403
    assert client.post("/api/jobs/user-feed-refresh", json={}).status_code == 403


def test_admin_soft_deletes_catalog_source(client, logged_in_admin):
    source_id = create_public_source(client)
    response = client.delete(f"/api/catalog/sources/{source_id}")
    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False
```

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py -q
```

Expected: tests fail because endpoints or role checks do not exist yet.

- [ ] **Step 2: Implement route helpers and endpoints**

In `src/api/server.py`, add:

```python
def require_mutating_member(user: dict[str, Any]) -> None:
    if user.get("role") == "viewer":
        raise ApiError("forbidden", "viewer users cannot change subscriptions, sources, or jobs", status_code=403)
```

Use it in catalog create/patch, subscription create/patch/delete, source test/update, and job create paths.

Add endpoint behavior:

```python
@app.post("/api/catalog/sources/{source_id}/subscribe")
async def catalog_subscribe(source_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_mutating_member(user)
    visible_source_or_404(source_id, user)
    subscription = store.create_subscription(user_id=user["id"], source_id=source_id)
    return ok({"subscription": subscription})


@app.delete("/api/catalog/sources/{source_id}/subscription")
async def catalog_unsubscribe(source_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_mutating_member(user)
    subscription = store.get_user_subscription_for_source(user["id"], source_id)
    if not subscription:
        raise ApiError("not_found", "subscription not found", status_code=404)
    deleted = store.delete_subscription(subscription["id"], user_id=user["id"])
    return ok({"deleted": deleted})


@app.post("/api/jobs/user-feed-refresh")
async def jobs_user_feed_refresh(payload: JobCreateRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    require_mutating_member(user)
    return ok(create_job(payload, "user_feed_refresh", user))
```

If `get_user_subscription_for_source` does not exist yet, implement it in Task 2 before this endpoint passes.

- [ ] **Step 3: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_job_queue.py -q
```

Expected: pass.

### Task 2: Add ServiceStore Subscription Lookup

**Files:**
- Modify: `src/storage/service_store.py`
- Modify: `tests/test_service_store.py`

**Interfaces:**
- Consumes: existing `user_subscriptions` table.
- Produces: `ServiceStore.get_user_subscription_for_source(user_id: str, source_id: str) -> dict[str, Any] | None`.

- [ ] **Step 1: Write failing store test**

Add:

```python
def test_get_user_subscription_for_source_returns_current_row(service_store):
    user = service_store.bootstrap_admin("admin", "pw")
    source_id = service_store.create_source(
        workspace_id=user["workspace_id"],
        scope="public",
        owner_user_id=user["id"],
        source_type="rss",
        display_name="OpenAI",
        enabled=True,
    )
    created = service_store.create_subscription(user_id=user["id"], source_id=source_id)
    found = service_store.get_user_subscription_for_source(user["id"], source_id)
    assert found["id"] == created["id"]
```

Run:

```bash
.venv/bin/python -m pytest tests/test_service_store.py -q
```

Expected: fail with missing method.

- [ ] **Step 2: Implement lookup**

Add method in `ServiceStore`:

```python
def get_user_subscription_for_source(self, user_id: str, source_id: str) -> dict[str, Any] | None:
    row = self._conn.execute(
        "SELECT * FROM user_subscriptions WHERE user_id = ? AND source_id = ?",
        (user_id, source_id),
    ).fetchone()
    return self._row_to_subscription(row) if row else None
```

Adjust helper names to match the existing row conversion methods in `service_store.py`.

- [ ] **Step 3: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_service_store.py tests/test_api_service.py -q
```

Expected: pass.

### Task 3: Add Dashboard Summary API

**Files:**
- Modify: `src/api/server.py`
- Modify: `src/services/feed_archive.py`
- Modify: `tests/test_api_service.py`
- Modify: `API_CONTRACT.md`

**Interfaces:**
- Consumes: visible catalog sources, current user subscriptions, job queue list, latest feed facade.
- Produces: `GET /api/dashboard/summary`.

- [ ] **Step 1: Write failing API test**

Add:

```python
def test_dashboard_summary_requires_login_and_returns_counts(client, logged_in_admin):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "source_count" in body["data"]
    assert "subscription_count" in body["data"]
    assert "queued_job_count" in body["data"]
    assert "latest_generated_at" in body["data"]
```

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py -q
```

Expected: fail with 404.

- [ ] **Step 2: Implement summary route**

Add:

```python
@app.get("/api/dashboard/summary")
async def dashboard_summary(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    sources = store.list_visible_sources(user)
    subscriptions = store.list_user_subscriptions(user["id"])
    jobs = queue.list_jobs(workspace_id=user["workspace_id"], user_id=None if _is_admin(user) else user["id"])
    latest = feed_archive.latest_feed()
    return ok({
        "source_count": len(sources),
        "subscription_count": len(subscriptions),
        "queued_job_count": len([job for job in jobs if job["status"] == "queued"]),
        "running_job_count": len([job for job in jobs if job["status"] == "running"]),
        "latest_generated_at": latest.get("generated_at"),
        "current_user": _sanitize_user(user),
    })
```

- [ ] **Step 3: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_service.py -q
```

Expected: pass.

### Task 4: Build Static Subscription Console View

**Files:**
- Modify: `src/ui/static/index.html`
- Modify: `src/ui/static/state.js`
- Modify: `src/ui/static/app.js`
- Modify: `src/ui/static/reader.js`
- Create: `src/ui/static/subscriptions.js`
- Create: `src/ui/static/subscriptions.css`
- Modify: `tests/test_static_reading_ui.py`

**Interfaces:**
- Consumes:
  - `GET /api/dashboard/summary`
  - `GET /api/catalog/sources`
  - `POST /api/catalog/sources/{id}/subscribe`
  - `DELETE /api/catalog/sources/{id}/subscription`
  - `GET /api/me/subscriptions`
  - `PATCH /api/me/subscriptions/{id}`
  - `POST /api/jobs/user-feed-refresh`
  - `GET /api/jobs`
- Produces: logged-in `订阅` view with marketplace, my subscriptions, private source form, and job status list.

- [ ] **Step 1: Write static contract tests**

Add assertions in `tests/test_static_reading_ui.py`:

```python
def test_subscription_console_static_contract():
    index_html = STATIC_DIR.joinpath("index.html").read_text()
    subscriptions_js = STATIC_DIR.joinpath("subscriptions.js").read_text()
    assert 'data-view="subscriptions"' in index_html
    assert "./subscriptions.js" in index_html
    assert "/api/catalog/sources" in subscriptions_js
    assert "/api/me/subscriptions" in subscriptions_js
    assert "/api/jobs/user-feed-refresh" in subscriptions_js
    assert "/api/jobs" in subscriptions_js
```

Run:

```bash
.venv/bin/python -m pytest tests/test_static_reading_ui.py -q
```

Expected: fail because files/view do not exist.

- [ ] **Step 2: Add view shell**

In `index.html`, add a top nav button:

```html
<button class="tab" type="button" data-view="subscriptions">订阅</button>
```

Add panel:

```html
<section id="subscriptionPanel" class="subscription-panel panel hidden" aria-label="订阅控制台">
  <div class="subscription-head">
    <div>
      <h2>订阅</h2>
      <p id="subscriptionSummary">读取中</p>
    </div>
    <div class="subscription-actions">
      <button id="refreshMyFeedBtn" type="button">刷新我的信息流</button>
      <button id="reloadSubscriptionsBtn" type="button">重新读取</button>
    </div>
  </div>
  <div id="subscriptionMessage" class="config-message"></div>
  <div id="subscriptionConsole" class="subscription-console"></div>
</section>
```

Link assets:

```html
<link rel="stylesheet" href="./subscriptions.css?v=20260708-subscription-console" />
<script src="./subscriptions.js?v=20260708-subscription-console"></script>
```

- [ ] **Step 3: Implement `subscriptions.js`**

Create functions:

```javascript
async function loadSubscriptionConsole() {}
function renderSubscriptionConsole(data) {}
async function subscribeToSource(sourceId) {}
async function unsubscribeFromSource(sourceId) {}
async function toggleSubscription(subscriptionId, enabled) {}
async function refreshMyFeed() {}
async function loadJobsPreview() {}
```

Rules:

- Use `unwrapApiPayload` for every fetch.
- Disable mutation buttons when `state.auth.user.role === 'viewer'`.
- Show public/workspace/private badges.
- Show queued job id after refresh.
- Never expose secret values; render only `secret_env` name when present.

- [ ] **Step 4: Wire view switching**

Update existing view switching so `subscriptions` hides reader/config panels and shows `subscriptionPanel`.

When login succeeds, keep current behavior loading feed; when user clicks `订阅`, call `loadSubscriptionConsole()`.

- [ ] **Step 5: Add CSS**

Create `subscriptions.css` with dense, work-focused layout:

```css
.subscription-panel { min-height: 0; overflow: auto; }
.subscription-console { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
.subscription-section { border-top: 1px solid var(--line); padding-top: 14px; }
.subscription-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.subscription-card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel-bg); }
```

Use existing CSS variables; do not introduce a one-note new palette.

- [ ] **Step 6: Run frontend checks**

Run:

```bash
node --check src/ui/static/*.js
.venv/bin/python -m pytest tests/test_static_reading_ui.py -q
```

Expected: pass.

### Task 5: Add Private Source Creation from Console

**Files:**
- Modify: `src/ui/static/subscriptions.js`
- Modify: `src/ui/static/subscriptions.css`
- Modify: `tests/test_static_reading_ui.py`

**Interfaces:**
- Consumes: `POST /api/catalog/sources`.
- Produces: private source creation path for `rss` first; advanced source types remain available in legacy config.

- [ ] **Step 1: Add test contract**

Assert `subscriptions.js` contains:

```python
assert "createPrivateSource" in subscriptions_js
assert "/api/catalog/sources" in subscriptions_js
assert 'scope: "private"' in subscriptions_js or "scope:\"private\"" in subscriptions_js
```

- [ ] **Step 2: Implement RSS private source form**

Fields:

- `display_name`
- `feed_url`
- `default_channel`
- `default_topics`
- `secret_env` optional env var name

Submit payload:

```javascript
{
  scope: "private",
  type: "rss",
  display_name: name,
  default_channel: channel,
  default_topics: topics,
  config: { url: feedUrl },
  secret_env: secretEnv || null,
  enabled: true
}
```

After create succeeds, auto-subscribe with `/api/catalog/sources/{id}/subscribe`, then reload console.

- [ ] **Step 3: Run checks**

Run:

```bash
node --check src/ui/static/*.js
.venv/bin/python -m pytest tests/test_static_reading_ui.py tests/test_api_service.py -q
```

Expected: pass.

### Task 6: Browser and Docker Smoke

**Files:**
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: running Docker `horizon-light-api` on `127.0.0.1:8080`.
- Produces: verified local preview path for the user.

- [ ] **Step 1: Rebuild and start API**

Run:

```bash
docker compose -f docker-compose.light.yml up -d --build horizon-api
```

Expected: `horizon-light-api` healthy.

- [ ] **Step 2: API smoke**

Run:

```bash
curl -i http://127.0.0.1:8080/api/auth/status
```

Expected: unauthenticated envelope until browser login.

- [ ] **Step 3: Worker once smoke**

Run:

```bash
.venv/bin/python -m src.services.worker --once
```

Expected: exits cleanly when no queued job exists.

- [ ] **Step 4: Browser smoke**

In the in-app browser:

1. Open `http://127.0.0.1:8080/`.
2. Confirm login gate is visible.
3. Login with local `.env` credentials.
4. Click `订阅`.
5. Confirm public source market, my subscriptions, private source form, and jobs preview render.
6. Click `刷新我的信息流`.
7. Confirm queued job id is shown.

- [ ] **Step 5: Record worklog**

Append to `WORKLOG.md`:

```md
### 2026-07-08 HH:MM Codex
- 任务：实现订阅控制台 MVP
- 读取文件：`src/api/server.py`、`src/storage/service_store.py`、`src/ui/static/*`、相关测试
- 修改文件：列出本次实际修改文件
- 执行验证：列出 pytest、node、Docker、browser smoke 结果
- 结果：登录后可通过订阅控制台管理公共源订阅、私有 RSS 源、任务队列和手动刷新
- 未解决问题：高级 source 类型仍在旧配置页；Worker 生产级重试和保留策略另排计划
- 控制面变更：更新 API 合同和订阅控制台计划
```

## Out of Scope

- 不迁移 React/Vite/Next。
- 不做多 workspace 切换和商业计费。
- 不做真实 API key 输入 UI，只允许环境变量名。
- 不做生产级 scheduler、重试退避、任务保留策略。
- 不做完整归档分析仪表盘；归档 API 已有，视觉化后续单独排期。

## Validation Bundle

Run before marking complete:

```bash
.venv/bin/python -m pytest tests/test_api_service.py tests/test_service_store.py tests/test_job_queue.py tests/test_worker.py tests/test_static_reading_ui.py -q
node --check src/ui/static/*.js
git diff --check
docker compose -f docker-compose.light.yml up -d --build horizon-api
curl -i http://127.0.0.1:8080/api/auth/status
```
