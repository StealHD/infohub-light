# Source Response Schema and Avatar Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely cache X avatars, refresh cached source avatars when their version changes, and show value-free upstream and normalized response structures in source Job history.

**Architecture:** A new pure response-schema module converts transient JSON-like values into bounded `path + type` summaries. Scrapers retain only that summary, Orchestrator attaches it to source outcomes, and safe Job diagnostics expose it without allowing raw values into Feed or content storage. Media cache keeps the existing pinned-network boundary, adds only `pbs.twimg.com` to the synthetic-DNS suffixes, and replaces avatars only after a candidate is verified and written successfully.

**Tech Stack:** Python 3.12, dataclasses/Pydantic, FastAPI service Job JSON, SQLite media assets, React 19, TypeScript strict, Material UI, pytest, Vitest, Playwright, Docker Compose.

## Global Constraints

- Never persist raw upstream values, source config, request URLs, Actor input, credentials, content text, or headers in response schemas.
- Schema types are exactly `object/array/string/integer/number/boolean/null/mixed`.
- Limit each upstream or normalized schema to depth 6, 256 paths, and 8 KiB; limit one Job to 64 KiB.
- Allow synthetic DNS only for exact/suffix-safe `pbs.twimg.com`; all existing SSRF, redirect, size, and image-magic checks remain active.
- Avatar identity ignores query and fragment; unchanged identities are rechecked no more than once per 24 hours.
- Candidate failure must preserve the current ready avatar and must not fail an otherwise successful source Job.
- Do not trigger a real source, Apify, AI, Worker, scheduler, or paid request during automated verification.
- The working tree is already dirty. Do not stage or commit overlapping implementation files; use scoped diff checkpoints and preserve all pre-existing changes.

---

### Task 1: Bounded Value-Free Response Schema Primitive

**Files:**
- Create: `src/services/response_schema.py`
- Create: `tests/test_response_schema.py`

**Interfaces:**
- Produces: `extract_response_schema(value: Any, *, max_depth: int = 6, max_fields: int = 256, max_bytes: int = 8192) -> dict[str, Any]`
- Produces: `merge_response_schemas(schemas: Iterable[dict[str, Any]], *, max_fields: int = 256, max_bytes: int = 8192) -> dict[str, Any]`
- Produces: `bound_source_response_schemas(records: Iterable[dict[str, Any]], *, max_bytes: int = 65536) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing extraction and leak-prevention tests**

```python
from src.services.response_schema import extract_response_schema


def test_extract_response_schema_keeps_paths_and_types_but_no_values():
    secret = "sk-private-do-not-store"
    schema = extract_response_schema([
        {"author": {"profilePicture": "https://pbs.twimg.com/a.jpg?token=secret"}, "count": 1, "ok": True},
        {"author": {"profilePicture": None}, "count": 1.5, "ok": False, "secret": secret},
    ])
    assert schema["root_type"] == "array"
    assert {tuple(field.values()) for field in schema["fields"]} >= {
        ("author", "object"),
        ("author.profilePicture", "mixed"),
        ("count", "mixed"),
        ("ok", "boolean"),
        ("secret", "string"),
    }
    serialized = json.dumps(schema)
    assert secret not in serialized
    assert "pbs.twimg.com" not in serialized
```

Include these concrete assertions in the same test module:

```python
assert extract_response_schema([]) == {"root_type": "array", "fields": [], "truncated": False}
assert extract_response_schema({"flag": True})["fields"] == [{"path": "flag", "type": "boolean"}]
assert extract_response_schema({"value used as a key\n": 1})["fields"][0]["path"] == "[dynamic-key]"
assert extract_response_schema({"z": 1, "a": 1})["fields"] == [
    {"path": "a", "type": "integer"}, {"path": "z", "type": "integer"}
]
assert extract_response_schema({"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}})["truncated"] is True
assert extract_response_schema({f"field_{i}": i for i in range(300)})["truncated"] is True
assert len(json.dumps(extract_response_schema({f"long_field_{i:03d}": i for i in range(300)})).encode()) <= 8192
assert len(json.dumps(bound_source_response_schemas(oversized_records)).encode()) <= 65536
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest tests/test_response_schema.py -q`

Expected: collection fails because `src.services.response_schema` does not exist.

- [ ] **Step 3: Implement the pure extractor**

Use a private `_value_type()` that checks `bool` before `int`, a `_safe_key()` that accepts ordinary field identifiers up to 80 characters, and a path/type accumulator that merges conflicting types to `mixed`. Serialize candidate results with compact JSON after each bound is applied; remove trailing fields until the byte limit is satisfied and set `truncated=true`.

The public result must have exactly:

```python
{
    "root_type": "array",
    "fields": [{"path": "author.profilePicture", "type": "string"}],
    "truncated": False,
}
```

`merge_response_schemas()` merges field paths without accessing original values. `bound_source_response_schemas()` preserves stable input order and drops trailing source records only when the 64 KiB limit is exceeded; the last retained record receives `job_truncated=true`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_response_schema.py -q`

Expected: all response-schema tests pass and injected values are absent from serialized output.

- [ ] **Step 5: Record a scoped diff checkpoint**

Run: `git diff --check -- src/services/response_schema.py tests/test_response_schema.py`

Expected: no output.

---

### Task 2: Scraper Observation and Job Diagnostic Integration

**Files:**
- Modify: `src/scrapers/base.py`
- Modify: `src/scrapers/apify_social.py`
- Modify: `src/scrapers/rss.py`
- Modify: `src/scrapers/github.py`
- Modify: `src/scrapers/reddit.py`
- Modify: `src/scrapers/hackernews.py`
- Modify: `src/scrapers/telegram.py`
- Modify: `src/services/feed_run.py`
- Modify: `src/orchestrator.py`
- Modify: `src/services/source_acquisition.py`
- Modify: `tests/test_apify_social.py`
- Modify: `tests/test_orchestrator_execute.py`
- Modify: `tests/test_feed_run_analysis_usage.py`
- Modify: `tests/test_source_acquisition.py`

**Interfaces:**
- Consumes: `extract_response_schema`, `merge_response_schemas`, `bound_source_response_schemas` from Task 1.
- Produces: `BaseScraper.observe_upstream_response(value: Any) -> None` and read-only `BaseScraper.upstream_response_schema`.
- Produces: optional `SourceOutcome.response_schema` and top-level Job result `response_schemas`.

- [ ] **Step 1: Write failing scraper observation tests**

For Apify, feed one Xquik row containing a sentinel URL/token and assert:

```python
await scraper.fetch(since)
schema = scraper.upstream_response_schema
assert {field["path"] for field in schema["fields"]} >= {
    "author.profilePicture", "author.username", "text"
}
assert "sentinel-secret-value" not in json.dumps(schema)
```

Add fixture-level assertions that RSS observes `feed.image` and entry fields; GitHub observes release/event dictionaries; Reddit observes post/comment dictionaries; Hacker News observes story/comment dictionaries; Telegram observes extracted message record fields. These tests must use existing mocks/fixtures and make no network request.

- [ ] **Step 2: Run adapter tests and verify RED**

Run: `.venv/bin/pytest tests/test_apify_social.py tests/test_rss.py tests/test_source_presentation_adapters.py -q`

Expected: failures because `upstream_response_schema` and observation calls do not exist.

- [ ] **Step 3: Add summary-only observation to BaseScraper and adapters**

Initialize an empty list of schema summaries in `BaseScraper`. `observe_upstream_response()` immediately extracts a bounded schema and appends only that summary. `upstream_response_schema` merges the summaries and never retains the input object.

Call observation at these adapter boundaries:

- Apify: the content-candidate dataset row before `_parse_row`.
- RSS: `{ "feed": feed.feed, "entry": entry }` before `ContentItem` construction; observe `{ "feed": feed.feed, "entry": [] }` for an empty feed.
- GitHub: each event/release dictionary before parsing.
- Reddit: `{ "post": post, "comments": comments }` before `_parse_post`; observe the listing envelope when empty.
- Hacker News: each story/comment dictionary after JSON decode.
- Telegram: an extracted record `{data_post, datetime, text, links}` before `ContentItem` construction; never retain raw HTML.

- [ ] **Step 4: Write failing run-diagnostic tests**

Construct a successful `SourceOutcome` with a structural summary and assert:

```python
diagnostics = safe_run_diagnostics(result, item_count=1)
record = diagnostics["response_schemas"][0]
assert record["capture_status"] == "captured"
assert record["upstream"]["fields"][0] == {"path": "author.name", "type": "string"}
assert record["normalized"]["fields"]
assert "raw-author-value" not in json.dumps(diagnostics)
```

Use a parametrized assertion for the remaining statuses and compatibility:

```python
@pytest.mark.parametrize("status", ["empty", "unavailable", "cached"])
def test_safe_diagnostics_preserves_capture_status_without_values(status):
    diagnostics = safe_run_diagnostics(result_with_status(status), item_count=0)
    assert diagnostics["response_schemas"][0]["capture_status"] == status
    assert "sentinel-secret-value" not in json.dumps(diagnostics)

def test_safe_diagnostics_bounds_source_and_job_schemas():
    diagnostics = safe_run_diagnostics(oversized_result(), item_count=0)
    assert len(json.dumps(diagnostics["response_schemas"]).encode()) <= 65536
    assert any(record.get("job_truncated") for record in diagnostics["response_schemas"])

def test_old_job_result_without_response_schemas_remains_valid():
    assert "response_schemas" not in {"item_count": 1, "snapshot_created": False}
```

- [ ] **Step 5: Run diagnostic tests and verify RED**

Run: `.venv/bin/pytest tests/test_feed_run_analysis_usage.py tests/test_orchestrator_execute.py tests/test_source_acquisition.py -q`

Expected: failures because SourceOutcome and diagnostics do not yet expose response schemas.

- [ ] **Step 6: Integrate the safe schema into source outcomes**

Extend `SourceOutcome` with optional keyword-only/default fields:

```python
catalog_type: str = ""
capture_status: Literal["captured", "empty", "cached", "unavailable"] = "unavailable"
upstream_schema: dict[str, Any] | None = None
normalized_schema: dict[str, Any] | None = None
```

In `fetch_service_sources()`, derive `catalog_type` from `source.catalog_source_type`, read the scraper summary, and derive the normalized schema from `[item.model_dump(mode="json") for item in fetched]`. Failed pre-response runs use `unavailable`; successful observed empty responses use `empty`.

When shared acquisition is enabled, record per-source origin inside `SourceAcquisitionCoordinator` as `upstream` or `cache`; expose `origin_for(source_id: str) -> str | None`. A cache return sets `capture_status=cached` and must not reuse a prior Job's upstream schema.

Keep `safe_source_outcome()` unchanged except for existing fields. `safe_run_diagnostics()` separately projects response schemas through `bound_source_response_schemas()` so the source outcome list does not duplicate them.

- [ ] **Step 7: Run integration tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_apify_social.py tests/test_rss.py tests/test_source_presentation_adapters.py tests/test_feed_run_analysis_usage.py tests/test_orchestrator_execute.py tests/test_source_acquisition.py -q`

Expected: all selected tests pass; no serialized diagnostic contains sentinel values.

- [ ] **Step 8: Verify schemas never enter Feed/content storage**

Use this storage assertion in Feed production tests:

```python
serialized_snapshot = json.dumps(saved_snapshot["payload"])
stored_item = store.connect().execute(
    "SELECT item_json FROM user_content_items WHERE article_id = ?", (article_id,)
).fetchone()["item_json"]
for forbidden in ("response_schemas", "upstream_schema", "sentinel-raw-value"):
    assert forbidden not in serialized_snapshot
    assert forbidden not in stored_item
```

Run: `.venv/bin/pytest tests/test_feed_production.py tests/test_user_feed_store.py -q`

Expected: all tests pass.

- [ ] **Step 9: Record a scoped diff checkpoint**

Run: `git diff --check -- src/scrapers src/services/feed_run.py src/services/source_acquisition.py src/orchestrator.py tests`

Expected: no whitespace errors.

---

### Task 3: X Synthetic DNS and Atomic Avatar Refresh

**Files:**
- Modify: `src/services/media_cache.py`
- Modify: `tests/test_user_feed_store.py`
- Modify: `tests/test_rss.py`

**Interfaces:**
- Produces: `X_MEDIA_HOST_SUFFIXES = ("pbs.twimg.com",)` and combined trusted media suffixes passed only by `MediaCacheService._download()`.
- Produces: `_remote_identity(url: str) -> str` and avatar refresh behavior inside `_cache_item()`.

- [ ] **Step 1: Write failing X network-boundary tests**

Use the existing synthetic DNS transport fixtures and assert:

```python
response = asyncio.run(fetch_public_http(
    "https://pbs.twimg.com/profile_images/a.jpg",
    synthetic_dns_host_suffixes=media_cache.TRUSTED_MEDIA_HOST_SUFFIXES,
    transport_factory=transport_factory,
))
assert response.status_code == 200
```

Add negative cases for `pbs.twimg.com.example.com`, `video.twimg.com`, a private `10.0.0.1`, a loopback redirect, and a non-`198.18.0.0/15` non-public resolution.

- [ ] **Step 2: Run network tests and verify RED**

Run: `.venv/bin/pytest tests/test_user_feed_store.py::test_media_cache_download_allows_synthetic_dns_only_for_x_and_instagram_cdns tests/test_rss.py::test_synthetic_dns_is_limited_to_explicit_cdn_suffixes -q`

Expected: X host is rejected because only Instagram suffixes are currently passed.

- [ ] **Step 3: Add the narrow X suffix**

Define:

```python
INSTAGRAM_MEDIA_HOST_SUFFIXES = ("cdninstagram.com", "fbcdn.net")
X_MEDIA_HOST_SUFFIXES = ("pbs.twimg.com",)
TRUSTED_MEDIA_HOST_SUFFIXES = (*INSTAGRAM_MEDIA_HOST_SUFFIXES, *X_MEDIA_HOST_SUFFIXES)
```

Pass only `TRUSTED_MEDIA_HOST_SUFFIXES` from `MediaCacheService._download()`. Do not change the default of `fetch_public_http()` or the RSS/member-controlled source path.

- [ ] **Step 4: Run network tests and verify GREEN**

Run the command from Step 2.

Expected: exact X/Instagram synthetic hosts pass; all negative cases remain rejected.

- [ ] **Step 5: Write failing avatar-version tests**

Use a controllable `fetch_image` and seeded `media_assets` rows to cover:

```python
def test_avatar_identity_change_replaces_only_after_candidate_succeeds(...):
    # Seed old ready JPEG and row.
    # Cache an item whose author_avatar_url has a different path.
    # Assert the API resolves the new media id and the old file is removed.

def test_avatar_refresh_failure_keeps_old_ready_asset(...):
    # Raise from fetch_image for a changed path.
    # Assert the old row/file and /api/media id remain unchanged.

def test_avatar_query_rotation_within_24h_does_not_download(...):
    # Same scheme/host/path, different query.
    # Assert fetch_image was not called.

def test_avatar_same_identity_after_24h_rechecks_checksum(...):
    # Old updated_at; same bytes updates remote_url/updated_at without a second file.
```

The different-checksum test must assert the complete swap:

```python
def test_avatar_same_identity_after_24h_with_new_checksum_swaps_version(...):
    old_id, old_path = seed_old_avatar(updated_at=old_time, data=OLD_JPEG)
    cache = MediaCacheService(store, data_dir=tmp_path, fetch_image=lambda _: (NEW_JPEG, "image/jpeg"))
    cache.cache_items(workspace_id=workspace_id, user_id=user_id, items=[item_with_same_avatar_path])
    current = cache.avatar_for_source(workspace_id=workspace_id, source_id=source_id)
    assert current["id"] != old_id
    assert current["checksum"] == hashlib.sha256(NEW_JPEG).hexdigest()
    assert not old_path.exists()
```

- [ ] **Step 6: Run avatar tests and verify RED**

Run: `.venv/bin/pytest tests/test_user_feed_store.py -k 'avatar' -q`

Expected: version/TTL assertions fail because current code always reuses the first ready avatar.

- [ ] **Step 7: Implement candidate verification and replacement**

Normalize identity with `urlsplit()` and remove query/fragment. Reuse a ready avatar within 24 hours when identity matches. Otherwise fetch and validate bytes before changing database state.

For equal checksum, update only `remote_url` and `updated_at`. For a new checksum, atomically write the candidate file, insert the new ready row, then delete all older source-avatar rows and unlink only their files under the media root. If any candidate step fails, return the old row.

Keep content-image behavior unchanged. Keep `invalidate_source_avatar()` for explicit source identity changes.

- [ ] **Step 8: Run avatar tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_user_feed_store.py tests/test_rss.py -q`

Expected: all media/network tests pass.

- [ ] **Step 9: Record a scoped diff checkpoint**

Run: `git diff --check -- src/services/media_cache.py tests/test_user_feed_store.py tests/test_rss.py`

Expected: no output.

---

### Task 4: React Dual Response-Structure View

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/features/subscriptions/ResponseSchemaDetails.tsx`
- Create: `frontend/src/features/subscriptions/ResponseSchemaDetails.test.tsx`
- Modify: `frontend/src/features/subscriptions/SubscriptionsPage.tsx`
- Modify: `frontend/src/features/subscriptions/SubscriptionsPage.test.tsx`

**Interfaces:**
- Consumes: optional `Job.result.response_schemas` from Task 2.
- Produces: `ResponseSchemaDetails({ job, sources }: { job: Job; sources: Map<string, CatalogSource> })`.

- [ ] **Step 1: Add TypeScript types and failing component tests**

Define:

```ts
export type ResponseSchemaField = { path: string; type: 'object' | 'array' | 'string' | 'integer' | 'number' | 'boolean' | 'null' | 'mixed' }
export type ResponseSchemaShape = { root_type: ResponseSchemaField['type']; fields: ResponseSchemaField[]; truncated: boolean }
export type SourceResponseSchema = {
  source_id: string
  catalog_type: string
  capture_status: 'captured' | 'empty' | 'cached' | 'unavailable'
  upstream: ResponseSchemaShape
  normalized: ResponseSchemaShape
  job_truncated?: boolean
}
```

Extend `Job.result/result_json` compatibility through the existing `Record<string, unknown>` access path and add a type guard in the component.

Tests must assert the control is collapsed by default, expands to “上游响应” and “标准化结果”, renders field paths/types but not injected raw values, displays empty/cached/unavailable/truncated copy, resolves the source display name, and uses semantic `<details>/<summary>`.

- [ ] **Step 2: Run Vitest and verify RED**

Run: `npm --prefix frontend test -- --run src/features/subscriptions/ResponseSchemaDetails.test.tsx`

Expected: test fails because the component does not exist.

- [ ] **Step 3: Implement the bounded structure table**

Render one outer `<details>` labelled “响应结构”. For each source render its name, capture-status copy, and two compact tables with headings “字段路径” and “类型”. Use `overflowWrap: 'anywhere'`, `tableLayout: 'fixed'`, and `maxWidth: '100%'`; do not use `dangerouslySetInnerHTML` or make any additional API request.

Status copy:

- `empty`: “上游成功返回空结果，本次没有可展示字段。”
- `cached`: “本次使用共享缓存，未重新观察上游响应。”
- `unavailable`: “本次运行未能记录上游响应结构。”
- `truncated`: “字段较多，已按安全上限截断。”

- [ ] **Step 4: Integrate into Job cards and verify GREEN**

Mount `ResponseSchemaDetails` after existing “技术详情” for terminal jobs. Old jobs without schema render a collapsed control whose expanded body says “本次运行未记录响应结构”。

Run: `npm --prefix frontend test -- --run src/features/subscriptions/ResponseSchemaDetails.test.tsx src/features/subscriptions/SubscriptionsPage.test.tsx`

Expected: both suites pass.

- [ ] **Step 5: Run frontend static gates**

Run: `npm --prefix frontend run lint`

Expected: 0 errors.

Run: `npm --prefix frontend run typecheck`

Expected: exit 0.

Run: `npm --prefix frontend run build`

Expected: production build succeeds and updates `src/ui/service_static` through the existing build flow.

- [ ] **Step 6: Record a scoped diff checkpoint**

Run: `git diff --check -- frontend/src src/ui/service_static`

Expected: no output.

---

### Task 5: Public Contracts and Decision Record

**Files:**
- Modify: `API_CONTRACT.md`
- Modify: `ARCHITECTURE_CONTRACT.md`
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Documents the exact Job shape and limits implemented by Tasks 1-4.

- [ ] **Step 1: Update the API contract**

Add the exact optional `response_schemas` fields, capture-status vocabulary, path/type enums, 6/256/8 KiB/64 KiB limits, compatibility for old Jobs, and the prohibition on raw values/config/URLs/content/secrets.

- [ ] **Step 2: Update architecture and UI ownership**

Record that scrapers discard raw values after structural extraction, `safe_run_diagnostics` owns the Job projection, media cache owns avatar refresh, and the React Job card owns the dual collapsed view and 390px wrapping behavior.

- [ ] **Step 3: Record the decision**

Add a Decision Log entry explaining why Job-bounded summaries were selected instead of raw response storage, on-demand recomputation, or a permanent response-history table.

- [ ] **Step 4: Validate control files**

Run: `python3 -m json.tool project-defaults.yaml >/dev/null`

Expected: exit 0.

Run: `git diff --check -- API_CONTRACT.md ARCHITECTURE_CONTRACT.md UI_CONTRACT.md DECISION_LOG.md WORKLOG.md`

Expected: no output.

---

### Task 6: Completion Gate, Local Rebuild, and Browser Verification

**Files:**
- Verify only; update `WORKLOG.md` with bounded evidence.

- [ ] **Step 1: Run impacted tests**

Run the focused pytest and Vitest commands from Tasks 1-4.

Expected: all pass without real network/provider calls.

- [ ] **Step 2: Run the full low-token gate**

Run: `python scripts/test_gate.py run --mode full`

Expected: compact summary reports `status=passed` and `mapping_miss=false`; do not load full successful logs into chat.

- [ ] **Step 3: Check paid-job safety before rebuilding**

Inspect active `queued/running` Jobs and enabled automatic schedules in `data/service.db`. Do not recreate Worker while a paid Apify Job can be claimed. If blocked, leave the existing containers running and report the exact Job/schedule blocker.

- [ ] **Step 4: Rebuild the latest local API and Worker**

Run: `./scripts/up-latest.sh`

Expected: API and Worker use the same newly built image, both containers are healthy, API readiness reports database and Worker ready, and scheduler remains absent.

- [ ] **Step 5: Verify without a paid fetch**

Use an existing or mock terminal Job payload to verify the React structure view. Do not click “立即获取” for X and do not enqueue a source Job. Verify desktop and 390px layouts with Playwright: the response structure expands, both tables render, no raw value appears, and the page has no horizontal overflow.

- [ ] **Step 6: Verify runtime media policy**

Run an in-process mocked/synthetic-DNS media-cache test inside the current image; do not download or persist a real X avatar. Confirm exact `pbs.twimg.com` acceptance and lookalike rejection.

- [ ] **Step 7: Final integrity and worklog**

Run: `sqlite3 data/service.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'`

Expected: `ok` followed by no foreign-key rows.

Append one concise `WORKLOG.md` entry with focused/full tests, image identity, health/readiness, scheduler state, browser widths, and the fact that no paid request was created.
