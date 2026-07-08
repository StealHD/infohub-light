# UI Design Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the UI issues found in browser review: leaked HTML text, topic values appearing as channel filters, poor mobile reading order, and noisy no-score reader copy.

**Architecture:** Keep the static UI contract intact. Add small browser-side presentation helpers for safe plain text and canonical Hub channels, keep Python payload compatibility unchanged, and use CSS responsive ordering for mobile reading flow.

**Tech Stack:** Python pytest, vanilla JavaScript static UI, CSS, Docker Compose light web, in-app Browser validation.

## Global Constraints

- Do not start scheduler or run full fetch unless explicitly requested.
- Keep `category/tags` compatibility while making UI prefer `channel/topics`.
- Do not render arbitrary item HTML with `innerHTML`; display cleaned plain text.
- Add tests before production code for behavior changes.
- Append `WORKLOG.md` at task end.

---

### Task 1: Plain Text Rendering For Item Summaries

**Files:**
- Modify: `tests/test_static_reading_ui.py`
- Modify: `src/ui/static/utils.js`
- Modify: `src/ui/static/reader.js`

**Interfaces:**
- Produces: `plainText(value: any): string`
- Produces: `displayText(value: any, fallback: string): string`
- Consumes: existing `escapeHtml(value)` for final HTML escaping

- [x] **Step 1: Add failing static UI test**

Add assertions to `test_static_ui_keeps_reader_state_and_render_functions`:

```python
assert "function plainText" in js_bundle
assert "function displayText" in js_bundle
assert "displayText(item.summary_zh || item.reason" in js_bundle
assert "displayText(item.summary_zh" in js_bundle
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker run --rm --entrypoint sh -v "$PWD":/app -w /app infohub-light-horizon:latest -lc "uv run --extra dev pytest tests/test_static_reading_ui.py::test_static_ui_keeps_reader_state_and_render_functions -q"
```

Expected: FAIL because `plainText` or `displayText` is missing.

- [x] **Step 3: Implement plain text helpers**

Add to `src/ui/static/utils.js` after `escapeHtml`:

```js
function plainText(value) {
  var text = String(value || '');
  if (!text) return '';
  var blockNormalized = text
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\/\s*(p|div|li|h[1-6])\s*>/gi, '\n');
  var withoutTags = blockNormalized.replace(/<[^>]*>/g, ' ');
  var textarea = document.createElement('textarea');
  textarea.innerHTML = withoutTags;
  return textarea.value.replace(/\s+/g, ' ').trim();
}

function displayText(value, fallback) {
  return plainText(value) || fallback;
}
```

- [x] **Step 4: Use display text in queue and reader**

In `src/ui/static/reader.js`, replace summary rendering with:

```js
'    <p>' + escapeHtml(displayText(item.summary_zh || item.reason, '暂无摘要')) + '</p>',
```

and:

```js
'  <p class="article-lead">' + escapeHtml(displayText(item.summary_zh, '暂无摘要')) + '</p>',
```

- [x] **Step 5: Run test to verify it passes**

Run the same pytest command. Expected: PASS.

### Task 2: Canonical Hub Channel Filter

**Files:**
- Modify: `tests/test_static_reading_ui.py`
- Modify: `src/ui/static/state.js`
- Modify: `src/ui/static/utils.js`
- Modify: `src/ui/static/reader.js`

**Interfaces:**
- Produces: `HUB_CHANNEL_OPTIONS: string[]`
- Produces: `normalizeHubChannel(value: any): string`
- Produces: `itemChannel(item: object): string`
- Consumes: existing `state.channel`

- [x] **Step 1: Add failing channel filter test assertions**

Add to `test_static_ui_keeps_reader_state_and_render_functions`:

```python
assert "HUB_CHANNEL_OPTIONS" in js_bundle
assert "function normalizeHubChannel" in js_bundle
assert "function itemChannel" in js_bundle
assert ".concat((data && data.categories)" not in js_bundle
assert "countBy(items, 'category')" not in js_bundle
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker run --rm --entrypoint sh -v "$PWD":/app -w /app infohub-light-horizon:latest -lc "uv run --extra dev pytest tests/test_static_reading_ui.py::test_static_ui_keeps_reader_state_and_render_functions -q"
```

Expected: FAIL because channel helpers are missing and categories are still mixed into channel filters.

- [x] **Step 3: Define canonical channel options**

Add to `src/ui/static/state.js` after `TAG_LIBRARY_OPTIONS`:

```js
var HUB_CHANNEL_OPTIONS = [
  'AI',
  '投资',
  '产品机会',
  '工作/项目',
  '朋友动态',
  '生活',
  '政策/风险',
  '其他',
];
```

- [x] **Step 4: Add channel normalizers**

Add to `src/ui/static/utils.js` before `getFilteredItems`:

```js
function normalizeHubChannel(value) {
  var raw = String(value || '').trim();
  var key = raw.toLowerCase().replace(/[\s_\\/#:：,，.\-]+/g, '');
  var aliases = {
    ai: 'AI',
    人工智能: 'AI',
    ai编程: 'AI',
    aicoding: 'AI',
    aiagent: 'AI',
    agent: 'AI',
    codex: 'AI',
    模型发布: 'AI',
    ragmcp: 'AI',
    aiinfra: 'AI',
    投资: '投资',
    finance: '投资',
    美股: '投资',
    估值: '投资',
    宏观: '投资',
    产品机会: '产品机会',
    产品创业: '产品机会',
    价格监控: '产品机会',
    工作项目: '工作/项目',
    朋友动态: '朋友动态',
    生活: '生活',
    政策风险: '政策/风险',
    安全治理: '政策/风险',
    其他: '其他',
  };
  if (HUB_CHANNEL_OPTIONS.indexOf(raw) >= 0) return raw;
  return aliases[key] || '';
}

function itemChannel(item) {
  return normalizeHubChannel(item && (item.channel || item.category)) || '其他';
}
```

- [x] **Step 5: Use canonical channels in filtering and context**

Change `getFilteredItems`, `getChannelFilterOptions`, scoped topic filtering, story meta, source line, and `contextBrief` to use `itemChannel(item)`.

- [x] **Step 6: Run test to verify it passes**

Run the same pytest command. Expected: PASS.

### Task 3: No-Score Reader Copy Reduction

**Files:**
- Modify: `tests/test_static_reading_ui.py`
- Modify: `src/ui/static/reader.js`
- Modify: `src/ui/static/reader.css`

**Interfaces:**
- Produces: `renderInsightBlocks(item: object, actionSuggestion: string): string`
- Produces: `.article-note`

- [x] **Step 1: Add failing test assertions**

Add to `test_static_ui_keeps_reader_state_and_render_functions` and `test_static_ui_uses_reader_layout_css`:

```python
assert "function renderInsightBlocks" in js_bundle
assert "无评分模式：按发布时间和信源优先级阅读" in js_bundle
assert ".article-note" in css
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
docker run --rm --entrypoint sh -v "$PWD":/app -w /app infohub-light-horizon:latest -lc "uv run --extra dev pytest tests/test_static_reading_ui.py::test_static_ui_keeps_reader_state_and_render_functions tests/test_static_reading_ui.py::test_static_ui_uses_reader_layout_css -q"
```

Expected: FAIL because the helper and CSS class are missing.

- [x] **Step 3: Extract reader insight block helper**

Add `renderInsightBlocks(item, actionSuggestion)` in `reader.js`. For `item.scoring_disabled`, return one `.article-note` paragraph instead of three repeated explanatory blocks.

- [x] **Step 4: Add article note styling**

Add `.article-note` to `reader.css` with compact spacing, soft border, and muted text.

- [x] **Step 5: Run tests to verify pass**

Run the same pytest command. Expected: PASS.

### Task 4: Mobile Reading Flow

**Files:**
- Modify: `tests/test_static_reading_ui.py`
- Modify: `src/ui/static/reader.css`

**Interfaces:**
- Produces: mobile rule `@media (max-width: 720px)`
- Produces: `.reader-panel { order: 1; }`, `.reading-queue { order: 2; }`, `.context-panel { order: 3; }`

- [x] **Step 1: Add failing CSS assertions**

Add to `test_static_ui_uses_reader_layout_css`:

```python
assert "@media (max-width: 720px)" in css
assert ".reader-panel {\\n    order: 1;" in css
assert ".reading-queue {\\n    order: 2;" in css
assert ".context-panel {\\n    order: 3;" in css
assert ".story-list {\\n    max-height: 480px;" in css
```

- [x] **Step 2: Run CSS contract test**

Run:

```bash
docker run --rm --entrypoint sh -v "$PWD":/app -w /app infohub-light-horizon:latest -lc "uv run --extra dev pytest tests/test_static_reading_ui.py::test_static_ui_uses_reader_layout_css -q"
```

Expected: FAIL because mobile ordering rules are missing.

- [x] **Step 3: Add mobile responsive CSS**

In `reader.css`, add a `max-width: 720px` media rule that changes the shell to one column, places the reader before the queue, disables sticky side panels, and caps the story list at `480px`.

- [x] **Step 4: Run CSS contract test**

Run the same command. Expected: PASS.

### Task 5: Asset Version And Browser Verification

**Files:**
- Modify: `src/ui/static/index.html`
- Modify: `WORKLOG.md`

**Interfaces:**
- Produces: fresh static asset version string

- [x] **Step 1: Bump static asset version**

Change `20260608-article-graph` to `20260708-ui-design-fixes` in `index.html`.

- [x] **Step 2: Run static checks**

Run:

```bash
node --check src/ui/static/state.js && node --check src/ui/static/utils.js && node --check src/ui/static/reader.js && node --check src/ui/static/config.js && node --check src/ui/static/app.js
docker run --rm --entrypoint sh -v "$PWD":/app -w /app infohub-light-horizon:latest -lc "uv run --extra dev pytest tests/test_static_reading_ui.py -q"
git diff --check
```

Expected: all pass.

- [x] **Step 3: Rebuild and validate rendered UI**

Run:

```bash
./scripts/up-latest.sh
```

Then use the in-app Browser:

1. Page identity: URL is `http://127.0.0.1:8081/`, title is `Inteliscope`.
2. Desktop screenshot: channel select shows canonical Hub channels, not topic labels.
3. Desktop screenshot: item summaries do not show raw `<p>`, `<small>`, `<var>`, or `<h2>` tags.
4. Mobile screenshot at `390x844`: reader panel appears before the long queue; story list is capped.
5. Console health: no relevant warn/error logs.

- [x] **Step 4: Append `WORKLOG.md`**

Add one concise worklog entry with files read, files changed, validations, result, and control-plane change `无`.

## Self-Review

- Spec coverage: P0 HTML leak covered by Task 1; P0 channel/topic mix covered by Task 2; P1 no-score copy covered by Task 3; P1 mobile flow covered by Task 4; rendered QA covered by Task 5.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: `plainText`, `displayText`, `normalizeHubChannel`, `itemChannel`, and `renderInsightBlocks` are defined before use.
