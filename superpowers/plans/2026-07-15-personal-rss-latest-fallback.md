# Personal RSS Latest Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let explicitly configured personal-activity RSS sources return all in-window entries or, when that set is empty, the feed's single newest dated entry, while reporting source-fetch results without calling the final Feed total “new content”.

**Architecture:** Add an opt-in `keep_latest_item` flag to the existing RSS catalog/config contract. The RSS adapter selects entries after parsing all valid dates and marks only the selected newest item with `latest_per_source`; the existing Feed finalizer then retains and atomically replaces that anchor. A source-fetch job adds an actual `fetched_count`, and the React presenter combines it with `snapshot_created` instead of interpreting `item_count` as a delta.

**Tech Stack:** Python 3.12, Pydantic, feedparser, SQLite service store, pytest, React 19, TypeScript, Vitest, Docker Compose.

## Global Constraints

- `keep_latest_item` defaults to `false`; existing RSS sources keep strict time-window behavior.
- In-window personal RSS entries are all returned; fallback returns exactly one newest valid-dated entry only when the in-window set is empty.
- HTTP/parse failures and feeds without any valid-dated entry do not fabricate fallback content.
- Only the selected newest item uses `retention_policy=latest_per_source`; all other RSS items use `time_window`.
- `item_count` remains the final user Feed total for compatibility; `fetched_count` is the target source outcome count.
- Old jobs without `fetched_count` must never use `item_count` as a new-item count.
- Do not change the global `time_window_hours=24` default or auto-detect Bilibili URLs.
- Preserve unrelated dirty-worktree changes; stage only files listed by each task.

---

### Task 1: Add the opt-in RSS configuration contract

**Files:**
- Modify: `tests/test_source_type_registry.py`
- Modify: `tests/test_user_config_builder.py`
- Modify: `src/models.py:137-149`
- Modify: `src/services/source_type_registry.py:107-130,458-470`

**Interfaces:**
- Consumes: existing RSS catalog config dictionaries.
- Produces: `RSSSourceConfig.keep_latest_item: bool` and normalized worker payload key `keep_latest_item`.

- [ ] **Step 1: Write failing registry and config-projection tests**

Add this test with the exact assertions below:

```python
def test_rss_latest_item_flag_is_opt_in_and_reaches_worker_payload():
    definition = next(item for item in list_source_types() if item["type"] == "rss")
    field = next(item for item in definition["fields"] if item["name"] == "keep_latest_item")
    assert field | {"input_type": "boolean", "default": False} == field

    default = validate_source_config("rss", {"url": "https://example.com/feed.xml"})
    enabled = validate_source_config(
        "rss",
        {"url": "https://example.com/feed.xml", "keep_latest_item": True},
    )
    assert default["keep_latest_item"] is False
    assert enabled["keep_latest_item"] is True
    assert build_source_payload({
        "id": "src-rss",
        "type": "rss",
        "display_name": "Profile RSS",
        "config": enabled,
    })["keep_latest_item"] is True
```

Extend the existing user-config-builder RSS test so the catalog config includes `keep_latest_item=True` and assert the projected RSS entry retains it.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/test_source_type_registry.py tests/test_user_config_builder.py -q
```

Expected: FAIL because the registry field and normalized default do not exist.

- [ ] **Step 3: Implement the minimal config contract**

Add to `RSSSourceConfig`:

```python
keep_latest_item: bool = False
```

Add this field to the RSS registry definition:

```python
_field(
    "keep_latest_item",
    "Keep latest item",
    "boolean",
    default=False,
    help="When the time window is empty, return and retain the newest dated feed item.",
),
```

Normalize the value in the RSS validation branch:

```python
data["keep_latest_item"] = _bool(data.get("keep_latest_item"), default=False)
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit only this task's files**

```bash
git add src/models.py src/services/source_type_registry.py tests/test_source_type_registry.py tests/test_user_config_builder.py
git commit -m "feat: add personal RSS latest-item option"
```

### Task 2: Select and mark the personal RSS anchor

**Files:**
- Modify: `tests/test_rss.py`
- Modify: `src/scrapers/rss.py:60-139`

**Interfaces:**
- Consumes: `RSSSourceConfig.keep_latest_item` and `since: datetime`.
- Produces: all valid in-window `ContentItem` objects, or one latest fallback item, with at most one `metadata.retention_policy=latest_per_source`.

- [ ] **Step 1: Write failing RSS selection tests**

Add this exact helper and three focused tests. The helper deliberately leaves the source order untouched so the assertions prove selection is date-based:

```python
def _fetch_selection_feed(
    entries: list[tuple[str, str]],
    *,
    keep_latest_item: bool,
    since: datetime,
):
    xml_items = "".join(
        f"""
        <item><guid>{title}</guid><title>{title}</title>
          <link>https://example.com/{title.replace(' ', '-')}</link>
          <pubDate>{published}</pubDate><description>{title}</description>
        </item>
        """
        for title, published in entries
    )
    response = MagicMock()
    response.text = f"<rss version='2.0'><channel><title>Selection</title>{xml_items}</channel></rss>"
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Selection",
        url="https://example.com/selection.xml",
        keep_latest_item=keep_latest_item,
    )
    return asyncio.run(RSSScraper([source], client).fetch(since))


def test_rss_default_does_not_backfill_items_before_window():
    items = _fetch_selection_feed(
        [
            ("Older item", "Thu, 02 Jul 2026 09:00:00 GMT"),
            ("Newest old item", "Thu, 09 Jul 2026 09:00:00 GMT"),
        ],
        keep_latest_item=False,
        since=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert items == []


def test_personal_rss_backfills_only_newest_dated_item_when_window_is_empty():
    items = _fetch_selection_feed(
        [
            ("Newest old item", "Thu, 09 Jul 2026 09:00:00 GMT"),
            ("Older item", "Thu, 02 Jul 2026 09:00:00 GMT"),
        ],
        keep_latest_item=True,
        since=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert [item.title for item in items] == ["Newest old item"]
    assert items[0].metadata["retention_policy"] == "latest_per_source"


def test_personal_rss_returns_all_in_window_items_and_marks_only_newest():
    items = _fetch_selection_feed(
        [
            ("Recent two", "Wed, 15 Jul 2026 12:00:00 GMT"),
            ("Old item", "Thu, 09 Jul 2026 09:00:00 GMT"),
            ("Recent one", "Wed, 15 Jul 2026 08:00:00 GMT"),
        ],
        keep_latest_item=True,
        since=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert {item.title for item in items} == {"Recent one", "Recent two"}
    assert [
        item.title for item in items
        if item.metadata.get("retention_policy") == "latest_per_source"
    ] == ["Recent two"]
    assert next(item for item in items if item.title == "Recent one").metadata["retention_policy"] == "time_window"
```

- [ ] **Step 2: Run the RSS tests and verify RED**

Run:

```bash
uv run pytest tests/test_rss.py -q
```

Expected: the opt-in fallback tests fail because `_fetch_feed` currently discards every pre-window entry.

- [ ] **Step 3: Implement parse-then-select in the RSS adapter**

Refactor `_fetch_feed` to collect `(published_at, entry)` pairs first:

```python
dated_entries = []
for entry in feed.entries:
    published_at = self._parse_date(entry)
    if published_at is not None:
        dated_entries.append((published_at, entry))

selected = [candidate for candidate in dated_entries if candidate[0] >= since]
if not selected and source.keep_latest_item and dated_entries:
    selected = [max(dated_entries, key=lambda candidate: candidate[0])]

latest = max(selected, key=lambda candidate: candidate[0], default=None)
for published_at, entry in selected:
    retention_policy = (
        "latest_per_source"
        if source.keep_latest_item and latest is not None and (published_at, entry) == latest
        else "time_window"
    )
    # Build the existing ContentItem unchanged, adding retention_policy to metadata.
```

Keep deterministic IDs, media extraction, tags, security checks, and strict error handling unchanged.

- [ ] **Step 4: Run the RSS tests and verify GREEN**

Run the Step 2 command. Expected: all RSS tests pass.

- [ ] **Step 5: Commit only this task's files**

```bash
git add src/scrapers/rss.py tests/test_rss.py
git commit -m "feat: backfill latest personal RSS item"
```

### Task 3: Preserve the anchor and report source-fetch counts honestly

**Files:**
- Modify: `tests/test_static_reading_ui.py`
- Modify: `src/ui/site.py:186-205`
- Modify: `tests/test_catalog_source_runner.py`
- Modify: `src/services/catalog_source_runner.py:226-253`
- Modify: `frontend/src/features/subscriptions/subscriptionModel.test.ts`
- Modify: `frontend/src/features/subscriptions/subscriptionModel.ts:106-117`

**Interfaces:**
- Consumes: `ContentItem.metadata.retention_policy`, `FeedRunResult.source_outcomes`, job result `snapshot_created`.
- Produces: allowlisted Feed `retention_policy`, job result `fetched_count`, and truthful React run-record copy.

- [ ] **Step 1: Write failing projection, runner, and presenter tests**

Add a site-payload assertion:

```python
item.metadata["retention_policy"] = "latest_per_source"
payload = build_site_payload(all_items=[item], date="2026-07-15")
assert payload["items"][0]["retention_policy"] == "latest_per_source"
```

Also assert an unknown metadata value projects as `time_window`.

In the catalog runner test, include a successful `SourceOutcome` with `fetched_count=1` and assert:

```python
assert result["fetched_count"] == 1
assert result["item_count"] == latest["item_count"]
```

In `subscriptionModel.test.ts`, cover new and legacy results:

```typescript
expect(presentJob({ ...job, status: 'succeeded', result: {
  fetched_count: 1, item_count: 4, snapshot_created: true,
}}, sources).resultLabel).toBe('本次抓取 1 条，信息流已更新')

expect(presentJob({ ...job, status: 'succeeded', result: {
  fetched_count: 1, item_count: 4, snapshot_created: false,
}}, sources).resultLabel).toBe('本次抓取 1 条，信息流无变化')

expect(presentJob({ ...job, status: 'succeeded', result: {
  item_count: 4, snapshot_created: false,
}}, sources).resultLabel).toBe('信息流无变化')
```

- [ ] **Step 2: Run focused Python and React tests and verify RED**

Run:

```bash
uv run pytest tests/test_static_reading_ui.py tests/test_catalog_source_runner.py -q
cd frontend && npm test -- --run src/features/subscriptions/subscriptionModel.test.ts
```

Expected: projection ignores explicit RSS retention, runner lacks `fetched_count`, and React still renders `item_count` as `N 条新内容`.

- [ ] **Step 3: Implement allowlisted retention projection**

Use explicit metadata only when valid, otherwise preserve the existing Apify-profile rule:

```python
explicit_retention = str(item.metadata.get("retention_policy") or "")
if explicit_retention in {"latest_per_source", "time_window"}:
    retention_policy = explicit_retention
else:
    retention_policy = (
        "latest_per_source"
        if (
            str(item.metadata.get("catalog_source_type") or "") == "apify_social"
            and str(item.metadata.get("apify_platform") or "").lower()
            in {"x", "twitter", "instagram"}
            and str(item.metadata.get("apify_kind") or "").lower() == "profile"
        )
        else "time_window"
    )
```

- [ ] **Step 4: Add `fetched_count` to the source-fetch job result**

Compute it from the target outcome only:

```python
source_outcomes = tuple(
    outcome for outcome in run_result.source_outcomes
    if outcome.source_id == source_id
)
fetched_count = sum(max(int(outcome.fetched_count), 0) for outcome in source_outcomes)
```

Reuse `source_outcomes` for `SourceHealthService.apply_outcomes(...)` and return `"fetched_count": fetched_count` next to `item_count`.

- [ ] **Step 5: Replace the React result label mapping**

Implement:

```typescript
const fetched = result.fetched_count
const changed = result.snapshot_created === true
const changeLabel = changed ? '信息流已更新' : '信息流无变化'
const resultLabel = typeof fetched === 'number'
  ? `本次抓取 ${fetched} 条，${changeLabel}`
  : changeLabel
```

Keep failed-job error details and job/source labels unchanged.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 2 commands. Expected: all selected Python and React tests pass.

- [ ] **Step 7: Commit only this task's files**

```bash
git add src/ui/site.py src/services/catalog_source_runner.py tests/test_static_reading_ui.py tests/test_catalog_source_runner.py frontend/src/features/subscriptions/subscriptionModel.ts frontend/src/features/subscriptions/subscriptionModel.test.ts
git commit -m "fix: report source refresh results accurately"
```

### Task 4: Full verification, local rollout, and Bilibili acceptance

**Files:**
- Modify: `WORKLOG.md`
- Runtime data only: `data/service.db` source config and generated snapshots/items/jobs.

**Interfaces:**
- Consumes: built API/Worker image and source ID `src_415927451e7a41288fd2408c2443fa74`.
- Produces: enabled `keep_latest_item` for “超Carry的柴西”, a Feed containing the source's latest Bilibili item, and an evidence-backed worklog entry.

- [ ] **Step 1: Run focused regression and static checks**

```bash
uv run pytest tests/test_rss.py tests/test_source_type_registry.py tests/test_user_config_builder.py tests/test_static_reading_ui.py tests/test_catalog_source_runner.py tests/test_feed_production.py -q
cd frontend && npm test -- --run src/features/subscriptions/subscriptionModel.test.ts src/features/subscriptions/SubscriptionsPage.test.tsx
cd frontend && npm run typecheck && npm run build
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 2: Run the repository test gate**

```bash
uv run python scripts/test_gate.py
```

Expected: all configured gate phases pass.

- [ ] **Step 3: Rebuild the local API and Worker**

Confirm there are no queued/running jobs, rebuild with the repository script, and verify runtime identity:

```bash
sqlite3 data/service.db "SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued','running');"
./scripts/up-latest.sh
docker compose -f docker-compose.light.yml ps
curl -fsS http://127.0.0.1:8080/api/health/ready
for file in src/models.py src/services/source_type_registry.py src/scrapers/rss.py src/ui/site.py src/services/catalog_source_runner.py; do
  test "$(shasum -a 256 "$file" | awk '{print $1}')" = "$(docker exec horizon-light-api sha256sum "/app/$file" | awk '{print $1}')"
  test "$(shasum -a 256 "$file" | awk '{print $1}')" = "$(docker exec horizon-light-worker sha256sum "/app/$file" | awk '{print $1}')"
done
test "$(shasum -a 256 src/ui/service_static/index.html | awk '{print $1}')" = "$(docker exec horizon-light-api sha256sum /app/src/ui/service_static/index.html | awk '{print $1}')"
```

Expected: active-job count is `0`; both containers are healthy; readiness returns `ready`; every hash comparison exits 0.

- [ ] **Step 4: Enable the flag through the validated application path**

Update only source `src_415927451e7a41288fd2408c2443fa74` so its existing config gains:

```json
{"keep_latest_item": true}
```

Preserve URL, name, scope, subscription, channel, and six-hour schedule. Verify the stored catalog config after the update.

- [ ] **Step 5: Trigger one source fetch and poll to terminal state**

Use the authenticated local Service API/UI to create one manual `source_fetch`. Poll without creating duplicate active jobs. If the third-party RSSHub returns a retryable 503, allow the existing retry path to reach a terminal state; do not alter the acceptance logic to hide the upstream error.

- [ ] **Step 6: Verify the original symptom end to end**

Query the Service DB/API and confirm all of the following:

```text
job.status = succeeded
job.result.fetched_count = 1
job.result.snapshot_created = true on the first changed snapshot
source health last_fetched_count = 1
Feed contains the newest RSS item from 超Carry的柴西
the item retention_policy = latest_per_source
the run record contains no “N 条新内容” label derived from item_count
```

Run the same source fetch once more and verify the stable item ID prevents duplicate Feed content and yields `snapshot_created=false` unless upstream content changed.

- [ ] **Step 7: Append the mandatory worklog and verify the final diff**

Record task, evidence, modified files, tests, runtime rollout, remaining RSSHub availability risk, and control-plane impact in `WORKLOG.md`. Run:

```bash
git diff --check -- WORKLOG.md
git status --short
```

- [ ] **Step 8: Commit the worklog without staging runtime databases**

```bash
git add WORKLOG.md
git commit -m "docs: record personal RSS fallback rollout"
```
