# Personal Source Radar Lightweight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the light worktree behave as a low-cost personal source radar: only configured sources, manual refresh, readable output without AI keys, and no scheduler or Apify surprises.

**Architecture:** Keep the existing backend modules in place, but make the light product path explicit through runtime gates, UI grouping, and light-safe scripts. The already-implemented `ai.enabled=false` path remains the central switch; this plan hardens the surrounding UX, templates, and verification so disabled cost features are neither shown as required nor started accidentally.

**Tech Stack:** Python 3, Pydantic models, `http.server` UI API, vanilla JavaScript/CSS static UI, Docker Compose, pytest.

---

## Current Baseline

- Worktree: `/Users/stealmac/Documents/jie/infohub-light`
- Branch: `Horizon-light`
- Light web service: `horizon-light-web` at `http://127.0.0.1:8081`
- Heavy worktree must not be touched: `/Users/stealmac/Documents/jie/infohub/Horizon`
- Scheduler must remain off unless explicitly requested.
- Ignored local files must not be committed: `.env`, `data/config.json`, `data/config.json.bak`
- Already implemented in the current worktree:
  - `ai.enabled` in `src/models.py`
  - no-score publish path in `src/orchestrator.py`
  - `POST /api/source/update`
  - single-source selection helpers
  - AI scoring toggle in config UI

## File Structure

- Modify `/Users/stealmac/Documents/jie/infohub-light/scripts/up-latest.sh`
  - Responsibility: local rebuild/restart command; must prefer `docker-compose.light.yml` and only recreate `horizon-web` in the light worktree.
- Modify `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/utils.js`
  - Responsibility: view labels, descriptions, filtering behavior, score visibility decisions.
- Modify `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/reader.js`
  - Responsibility: reader panel, queue, context panel, score badges, no-score wording.
- Modify `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/config.js`
  - Responsibility: config page layout, source forms, advanced/cost feature grouping.
- Modify `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/config.css`
  - Responsibility: visual treatment for core cards, advanced sections, cost badges, muted disabled controls.
- Modify `/Users/stealmac/Documents/jie/infohub-light/src/ui/server.py`
  - Responsibility: env status, config actions, static asset routing. Hide env vars for disabled cost features.
- Modify `/Users/stealmac/Documents/jie/infohub-light/src/ui/site.py`
  - Responsibility: static site payload. Add explicit reading mode metadata if needed by UI.
- Create `/Users/stealmac/Documents/jie/infohub-light/data/config.light.example.json`
  - Responsibility: safe light template with AI, webhook, email, scheduler-like side effects, Apify, OpenBB, premium analysis, and article graph disabled.
- Modify `/Users/stealmac/Documents/jie/infohub-light/tests/test_config_server.py`
  - Responsibility: config API and env status tests.
- Modify `/Users/stealmac/Documents/jie/infohub-light/tests/test_static_reading_ui.py`
  - Responsibility: static UI string and syntax coverage.
- Modify `/Users/stealmac/Documents/jie/infohub-light/tests/test_orchestrator_token_budget.py`
  - Responsibility: no-score runtime guard coverage.
- Create `/Users/stealmac/Documents/jie/infohub-light/tests/test_light_runtime_scripts.py`
  - Responsibility: light-safe script and template assertions.

## Task 1: Make `up-latest.sh` Light-Safe

**Files:**
- Modify: `/Users/stealmac/Documents/jie/infohub-light/scripts/up-latest.sh`
- Create: `/Users/stealmac/Documents/jie/infohub-light/tests/test_light_runtime_scripts.py`

- [ ] **Step 1: Write the failing script test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_up_latest_prefers_light_compose_and_does_not_start_scheduler_by_default():
    script = (ROOT / "scripts" / "up-latest.sh").read_text(encoding="utf-8")

    assert "docker-compose.light.yml" in script
    assert 'LIGHT_SERVICES=("horizon-web")' in script
    assert 'LIGHT_MANUAL_SERVICE="horizon"' in script
    assert 'horizon-scheduler"' not in script.split('if [[ -f "docker-compose.light.yml" ]]', 1)[1].split("else", 1)[0]
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_light_runtime_scripts.py::test_up_latest_prefers_light_compose_and_does_not_start_scheduler_by_default -q"
```

Expected: FAIL because the current script uses default compose and has `SERVICES=("horizon-web" "horizon-scheduler")`.

- [ ] **Step 3: Update the script**

Replace the service selection block with this logic:

```bash
if [[ -f "docker-compose.light.yml" ]]; then
  COMPOSE=(docker compose -f docker-compose.light.yml)
  LIGHT_SERVICES=("horizon-web")
  LIGHT_MANUAL_SERVICE="horizon"
  SERVICES=("${LIGHT_SERVICES[@]}")
  MANUAL_SERVICE="$LIGHT_MANUAL_SERVICE"
  PRUNE_PROJECT="infohub-light"
else
  COMPOSE=(docker compose)
  SERVICES=("horizon-web" "horizon-scheduler")
  MANUAL_SERVICE="horizon"
  PRUNE_PROJECT="horizon"
fi
```

Then change every `docker compose ...` command in the script to `"${COMPOSE[@]}" ...`, and change the prune label from the hard-coded `horizon` to `$PRUNE_PROJECT`.

- [ ] **Step 4: Run the script test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_light_runtime_scripts.py::test_up_latest_prefers_light_compose_and_does_not_start_scheduler_by_default -q"
```

Expected: PASS.

## Task 2: Hide Disabled Cost Env Vars From Config Status

**Files:**
- Modify: `/Users/stealmac/Documents/jie/infohub-light/src/ui/server.py`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/tests/test_config_server.py`

- [ ] **Step 1: Write failing env status tests**

Add tests beside the existing `build_env_status` coverage:

```python
def test_env_status_hides_ai_key_when_ai_disabled(valid_config_data):
    valid_config_data["ai"]["enabled"] = False
    valid_config_data["ai"]["api_key_env"] = "XIAOMI_API_KEY"
    config = validate_config_data(valid_config_data)

    names = {item["name"] for item in build_env_status(config)}

    assert "XIAOMI_API_KEY" not in names


def test_env_status_hides_apify_tokens_when_apify_social_disabled(valid_config_data):
    valid_config_data["sources"]["apify_social"]["enabled"] = False
    valid_config_data["sources"]["apify_social"]["token_envs"] = [
        "APIFY_TOKEN",
        "APIFY_TOKEN_2",
    ]
    config = validate_config_data(valid_config_data)

    names = {item["name"] for item in build_env_status(config)}

    assert "APIFY_TOKEN" not in names
    assert "APIFY_TOKEN_2" not in names
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_config_server.py::test_env_status_hides_ai_key_when_ai_disabled tests/test_config_server.py::test_env_status_hides_apify_tokens_when_apify_social_disabled -q"
```

Expected: the AI test should already pass; the Apify token test may fail if disabled Apify env vars are still reported.

- [ ] **Step 3: Update `build_env_status`**

Inside `build_env_status(config)`, only add Apify token env vars when both conditions are true:

```python
apify_social = config.sources.apify_social
apify_has_enabled_subscription = any(
    subscription.enabled for subscription in apify_social.subscriptions
)
if apify_social.enabled and apify_has_enabled_subscription:
    for env_name in apify_social.token_envs or [apify_social.token_env]:
        add_env(env_name, "Apify 社交信源")
```

If the current code also reports legacy `twitter.apify_token_env`, apply the same rule: only report it when that legacy source is enabled.

- [ ] **Step 4: Run config server tests**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_config_server.py -q"
```

Expected: PASS.

## Task 3: Make No-Score Reading Mode First-Class

**Files:**
- Modify: `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/utils.js`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/reader.js`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/app.js`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/tests/test_static_reading_ui.py`

- [ ] **Step 1: Write failing static UI assertions**

Extend `test_static_ui_keeps_reader_state_and_render_functions`:

```python
def test_static_ui_has_no_score_mode_labels():
    utils_js = STATIC_DIR.joinpath("utils.js").read_text(encoding="utf-8")
    reader_js = STATIC_DIR.joinpath("reader.js").read_text(encoding="utf-8")
    app_js = STATIC_DIR.joinpath("app.js").read_text(encoding="utf-8")

    assert "function getEffectiveMinScore" in utils_js
    assert "全部动态" in utils_js
    assert "无评分模式" in reader_js
    assert "state.view = 'all'" in app_js
```

- [ ] **Step 2: Run the failing static UI test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_static_reading_ui.py::test_static_ui_has_no_score_mode_labels -q"
```

Expected: FAIL until `getEffectiveMinScore` exists.

- [ ] **Step 3: Add no-score filter helpers**

In `src/ui/static/utils.js`, add:

```javascript
function getEffectiveMinScore() {
  return isAiScoringEnabled() ? state.minScore : 0;
}

function shouldShowScoreControls() {
  return isAiScoringEnabled();
}
```

Change `getFilteredItems()` score filtering to:

```javascript
var minScore = getEffectiveMinScore();
if (isAiScoringEnabled() && (item.score || 0) < minScore) return false;
```

- [ ] **Step 4: Update no-score labels**

In `viewLabel()` and `viewDescription()`, use these exact no-score labels:

```javascript
if (!isAiScoringEnabled() && state.view === 'featured') return '全部动态';
if (!isAiScoringEnabled() && state.view === 'daily') return '全部动态';
```

For no-score descriptions, use:

```javascript
return '无评分模式下按发布时间展示你配置的信源内容。';
```

- [ ] **Step 5: Keep the default no-score view on `all`**

In `src/ui/static/app.js`, preserve:

```javascript
if (state.data && state.data.ai_enabled === false && state.view === 'featured') {
  state.view = 'all';
}
```

Add the same redirect for `daily`:

```javascript
if (state.data && state.data.ai_enabled === false && state.view === 'daily') {
  state.view = 'all';
}
```

- [ ] **Step 6: Run JS syntax and static UI tests**

Run:

```bash
node --check src/ui/static/*.js
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_static_reading_ui.py -q"
```

Expected: both PASS.

## Task 4: Reorganize Config UI Into Core and Advanced

**Files:**
- Modify: `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/config.js`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/src/ui/static/config.css`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/tests/test_static_reading_ui.py`

- [ ] **Step 1: Write failing config UI assertions**

Add:

```python
def test_config_ui_groups_cost_features_as_advanced():
    config_js = STATIC_DIR.joinpath("config.js").read_text(encoding="utf-8")
    config_css = STATIC_DIR.joinpath("config.css").read_text(encoding="utf-8")

    assert "renderCoreSettings" in config_js
    assert "renderAdvancedSettings" in config_js
    assert "成本源" in config_js
    assert "高级 / 可选能力" in config_js
    assert ".advanced-section" in config_css
    assert ".cost-badge" in config_css
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_static_reading_ui.py::test_config_ui_groups_cost_features_as_advanced -q"
```

Expected: FAIL.

- [ ] **Step 3: Split `renderConfigForms`**

Change `renderConfigForms(config)` to this structure:

```javascript
function renderConfigForms(config) {
  var forms = document.getElementById('configForms');
  forms.innerHTML = [
    renderCoreSettings(config),
    renderAdvancedSettings(config),
  ].join('');
}

function renderCoreSettings(config) {
  config = config || {};
  return [
    renderAiForm(config.ai || {}),
    renderNewSourceForm({ includeCostSources: false }),
    renderExistingSources(config.sources || {}, { includeCostSources: false }),
    renderHackerNewsForm((config.sources || {}).hackernews || {}),
    renderPersonalTagLibraryForm(config.personal_tags || []),
  ].join('');
}

function renderAdvancedSettings(config) {
  config = config || {};
  return [
    '<details class="advanced-section">',
    '<summary><span>高级 / 可选能力</span><strong>默认关闭</strong></summary>',
    '<div class="advanced-section-body">',
    renderTagLibraryForm(config.tags || []),
    renderFilteringForm(config.filtering || {}),
    renderWebhookForm(config.webhook || {}),
    renderApifySocialSettings((config.sources || {}).apify_social || {}),
    renderNewSourceForm({ includeCostSources: true, advancedOnly: true }),
    renderExistingSources(config.sources || {}, { includeCostSources: true, costOnly: true }),
    '</div>',
    '</details>',
  ].join('');
}
```

- [ ] **Step 4: Parameterize source rendering**

Update signatures:

```javascript
function renderNewSourceForm(options) {
  options = options || {};
  var includeCostSources = options.includeCostSources === true;
  ...
}

function renderExistingSources(sources, options) {
  options = options || {};
  var includeCostSources = options.includeCostSources !== false;
  var costOnly = options.costOnly === true;
  ...
}
```

Core mode must render RSS, GitHub, Reddit, Telegram, and HackerNews controls. Advanced cost mode must render Apify Social only.

- [ ] **Step 5: Add cost badges**

In `renderApifySocialSettings()` and `renderApifySocialCard()`, include:

```javascript
'<span class="cost-badge">成本源</span>'
```

Also change the Apify source group label to:

```javascript
'Apify 社交信源（成本源，默认关闭）'
```

- [ ] **Step 6: Add CSS for advanced sections**

Append to `src/ui/static/config.css`:

```css
.advanced-section {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}

.advanced-section > summary {
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  font-weight: 700;
}

.advanced-section-body {
  display: grid;
  gap: 16px;
  padding: 0 16px 16px;
}

.cost-badge {
  display: inline-flex;
  align-items: center;
  border: 1px solid #f59e0b;
  border-radius: 999px;
  color: #92400e;
  background: #fffbeb;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
}
```

- [ ] **Step 7: Run UI checks**

Run:

```bash
node --check src/ui/static/*.js
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_static_reading_ui.py -q"
```

Expected: PASS.

## Task 5: Add a Safe Light Config Template

**Files:**
- Create: `/Users/stealmac/Documents/jie/infohub-light/data/config.light.example.json`
- Modify: `/Users/stealmac/Documents/jie/infohub-light/tests/test_light_runtime_scripts.py`

- [ ] **Step 1: Write failing template test**

Add:

```python
import json

from src.models import Config


def test_light_config_template_is_safe_and_valid():
    payload = json.loads((ROOT / "data" / "config.light.example.json").read_text(encoding="utf-8"))
    config = Config.model_validate(payload)

    assert config.ai.enabled is False
    assert config.webhook is None or config.webhook.enabled is False
    assert config.email is None or config.email.enabled is False
    assert config.sources.apify_social.enabled is False
    assert config.sources.openbb.enabled is False
    assert config.sources.ossinsight.enabled is False
    assert config.premium_analysis.enabled is False
    assert config.article_graph.enabled is False
```

- [ ] **Step 2: Run the failing template test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_light_runtime_scripts.py::test_light_config_template_is_safe_and_valid -q"
```

Expected: FAIL because `data/config.light.example.json` does not exist yet.

- [ ] **Step 3: Create the template**

Create `data/config.light.example.json` with valid JSON containing:

```json
{
  "version": "1.0",
  "ai": {
    "enabled": false,
    "provider": "xiaomi",
    "model": "xai-latest",
    "api_key_env": "XIAOMI_API_KEY",
    "temperature": 0.3,
    "max_tokens": 4096,
    "throttle_sec": 0,
    "analysis_concurrency": 1,
    "enrichment_concurrency": 1,
    "analysis_content_chars": 1000,
    "analysis_comments_chars": 1500,
    "enrichment_content_chars": 4000,
    "languages": ["zh"]
  },
  "tags": [
    "AI Agent",
    "AI 编程",
    "模型发布",
    "RAG/MCP",
    "AI Infra",
    "开源模型",
    "推理框架",
    "产品创业",
    "研究论文",
    "安全治理",
    "行业动态"
  ],
  "personal_tags": [],
  "email": {
    "enabled": false,
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "imap_server": "imap.qq.com",
    "imap_port": 993,
    "email_address": "xxx@qq.com",
    "sender_name": "Horizon Daily",
    "subscribe_keyword": "SUBSCRIBE",
    "unsubscribe_keyword": "UNSUBSCRIBE"
  },
  "sources": {
    "github": [],
    "hackernews": {
      "enabled": false,
      "fetch_top_stories": 20,
      "min_score": 100
    },
    "rss": [],
    "reddit": {
      "enabled": false,
      "subreddits": [],
      "users": [],
      "fetch_comments": 0
    },
    "telegram": {
      "enabled": false,
      "channels": []
    },
    "twitter": {
      "enabled": false,
      "apify_token_env": "APIFY_TOKEN",
      "users": [],
      "fetch_limit": 10,
      "fetch_reply_text": false,
      "max_replies_per_tweet": 3,
      "max_tweets_to_expand": 10,
      "reply_min_likes": 5
    },
    "apify_social": {
      "enabled": false,
      "token_env": "APIFY_TOKEN",
      "token_envs": ["APIFY_TOKEN"],
      "timeout_seconds": 180,
      "actors": {
        "x": { "actor_id": "altimis~scweet" },
        "instagram": { "actor_id": "apify/instagram-api-scraper" },
        "facebook": { "actor_id": "whoareyouanas/facebook-group-scraper" },
        "telegram": { "actor_id": "thescrapelab/apify-telegram-scraper" }
      },
      "subscriptions": []
    },
    "openbb": {
      "enabled": false,
      "fetch_filings": false,
      "filings_provider": "sec",
      "watchlists": []
    },
    "ossinsight": {
      "enabled": false,
      "period": "past_24_hours",
      "languages": ["All"],
      "keywords": [],
      "min_stars": 10,
      "max_items": 30
    }
  },
  "filtering": {
    "ai_score_threshold": 7.5,
    "featured_score_threshold": 7.5,
    "daily_push_score_threshold": 8.5,
    "daily_push_limit": 10,
    "homepage_min_score": 6.0,
    "time_window_hours": 24,
    "recent_item_limit": 20
  },
  "premium_analysis": {
    "enabled": false,
    "full_fetch_score_threshold": 8.5,
    "max_full_fetch_per_run": 10,
    "max_full_text_chars": 12000,
    "full_fetch_concurrency": 2,
    "keep_premium_articles": 1000,
    "keep_full_text_days": 90
  },
  "article_graph": {
    "enabled": false,
    "premium_score_threshold": 8.5,
    "active_window_days": 30,
    "extended_window_days": 90,
    "max_active_nodes": 300,
    "max_visible_nodes": 30,
    "max_visible_edges": 100,
    "relation_top_k": 3,
    "min_relation_score": 0.55,
    "strong_relation_score": 0.75,
    "snapshot_min_new_premium_articles": 3,
    "snapshot_max_age_hours": 6,
    "enable_embedding": false,
    "enable_ai_group_summary": false
  },
  "webhook": {
    "enabled": false,
    "url_env": "HORIZON_WEBHOOK_URL",
    "delivery": "summary",
    "overview_position": "first",
    "platform": "generic",
    "layout": "markdown",
    "fallback_layout": "markdown",
    "languages": null,
    "request_body": {
      "text": "#{message_title}\\n\\n#{summary}"
    },
    "headers": ""
  }
}
```

- [ ] **Step 4: Run the template test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_light_runtime_scripts.py::test_light_config_template_is_safe_and_valid -q"
```

Expected: PASS.

## Task 6: Harden No-AI Runtime Guards

**Files:**
- Modify: `/Users/stealmac/Documents/jie/infohub-light/tests/test_orchestrator_token_budget.py`
- Modify only if tests fail: `/Users/stealmac/Documents/jie/infohub-light/src/orchestrator.py`

- [ ] **Step 1: Add guard test for disabled secondary pipelines**

Add a test that monkeypatches these methods to raise if called while `ai.enabled=false`:

```python
async def test_no_ai_run_skips_all_secondary_cost_pipelines(monkeypatch, tmp_path):
    config = _ai_disabled_config(tmp_path)
    storage = StorageManager(tmp_path)
    orchestrator = HorizonOrchestrator(config, storage)
    item = _news_item("rss:item:secondary-guard")

    async def fake_fetch_all_sources(since):
      return [item]

    async def fail_analyze(items):
      raise AssertionError("_analyze_content should not run when ai.enabled=false")

    async def fail_enrich(items):
      raise AssertionError("_enrich_important_items should not run when ai.enabled=false")

    async def fail_graph(items):
      raise AssertionError("_run_article_graph_pipeline should not run when ai.enabled=false")

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fake_fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", fail_analyze)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", fail_enrich)
    monkeypatch.setattr(orchestrator, "_run_article_graph_pipeline", fail_graph)

    await orchestrator.run(send_notifications=True, write_summaries=True, enrich=True)

    payload = json.loads((tmp_path / "site" / "radar-data.json").read_text(encoding="utf-8"))
    assert payload["ai_enabled"] is False
    assert payload["today_items"][0]["scoring_disabled"] is True
```

- [ ] **Step 2: Run the guard test**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_orchestrator_token_budget.py::test_no_ai_run_skips_all_secondary_cost_pipelines -q"
```

Expected: PASS if the current no-score path is complete. If it fails, update `HorizonOrchestrator.run()` so the `if not self._ai_enabled()` branch returns before enrichment, summaries, notifications, premium full-text, and article graph.

## Task 7: Final Verification and Local Deploy

**Files:**
- No source changes expected in this task.

- [ ] **Step 1: Run Python syntax smoke**

Run:

```bash
python3 -m py_compile src/models.py src/orchestrator.py src/ui/site.py src/ui/server.py src/services/source_update.py src/main.py src/mcp/horizon_adapter.py
```

Expected: no output and exit code 0.

- [ ] **Step 2: Run JS syntax check**

Run:

```bash
node --check src/ui/static/*.js
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run targeted tests**

Run:

```bash
docker compose -f docker-compose.light.yml run --rm --no-deps --build --entrypoint sh horizon -lc "uv run --extra dev pytest tests/test_config_server.py tests/test_orchestrator_token_budget.py tests/test_private_radar.py tests/test_auth.py tests/test_source_selection.py tests/test_static_reading_ui.py tests/test_light_runtime_scripts.py -q"
```

Expected: PASS.

- [ ] **Step 4: Rebuild only the light web container**

Run:

```bash
docker compose -f docker-compose.light.yml up -d --build horizon-web
```

Expected: only `horizon-light-web` is recreated.

- [ ] **Step 5: Verify scheduler is not running**

Run:

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | rg 'horizon-light|horizon-scheduler|horizon-web'
```

Expected:

```text
horizon-light-web    Up ...    127.0.0.1:8081->8080/tcp
```

The output must not include `horizon-light-scheduler`.

- [ ] **Step 6: Verify web health**

Run:

```bash
curl -I http://127.0.0.1:8081/
```

Expected: `HTTP/1.0 200 OK` or `HTTP/1.1 200 OK`.

## Self-Review Checklist

- Spec coverage:
  - Low-cost restart boundary is covered by Task 1.
  - Env/key confusion for disabled AI and Apify is covered by Task 2.
  - No-score reading mode is covered by Task 3.
  - Config page light/default vs advanced/cost features is covered by Task 4.
  - Safe light template is covered by Task 5.
  - Backend runtime cost guards are covered by Task 6.
  - Deploy and local verification are covered by Task 7.
- Placeholder scan:
  - No step relies on unspecified behavior.
  - Every code-changing task has a concrete test and a concrete implementation target.
- Type consistency:
  - Existing names are preserved: `ai.enabled`, `build_env_status`, `renderConfigForms`, `getFilteredItems`, `HorizonOrchestrator.run`.
  - New helper names are consistent: `renderCoreSettings`, `renderAdvancedSettings`, `getEffectiveMinScore`, `shouldShowScoreControls`.

## Execution Rules

- Do not modify `/Users/stealmac/Documents/jie/infohub/Horizon`.
- Do not start `horizon-light-scheduler`.
- Do not run real Apify, real AI scoring, or real webhook pushes during implementation.
- Do not commit `.env`, `data/config.json`, or `data/config.json.bak`.
- Prefer `docker compose -f docker-compose.light.yml ...` for tests and rebuilds in the light worktree.
