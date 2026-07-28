# Hub Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the AI-only tag taxonomy with a private hub taxonomy optimized for reading filters now and structured archive analysis later.

**Architecture:** Add a compatibility layer that introduces `channel`, `topics`, `signal_strength`, `signal_type`, and `entities` while continuing to emit legacy `category` and `tags` for existing UI/history consumers. Treat `category/tags` as derived aliases during serialization and cache reads.

**Tech Stack:** Python 3.11, Pydantic models, static JavaScript UI, pytest, node syntax checks.

---

### Task 1: Taxonomy Primitives

**Files:**
- Modify: `src/tag_policy.py`
- Test: `tests/test_config_server.py`

- [x] Add hub channels, default topics, signal strength/type constants, and normalizers.
- [x] Change topic normalization so custom reading topics are accepted, while channel values remain controlled.
- [x] Run targeted config tests for migration and tag action behavior.

### Task 2: Model And Config Compatibility

**Files:**
- Modify: `src/models.py`
- Modify: `src/config_migration.py`
- Modify: `src/scrapers/base.py`
- Modify: `src/ui/server.py`
- Test: `tests/test_config_server.py`

- [x] Add optional `channel` and `topics` to source config models.
- [x] Add AI analysis fields for channel, topics, signal strength/type, and entities to `ContentItem`.
- [x] Keep legacy source `tags/category` readable, but save new source actions with `channel/topics` plus legacy aliases.
- [x] Preserve custom topics in migration instead of moving them into `personal_tags`.

### Task 3: AI Analysis Output

**Files:**
- Modify: `src/ai/prompts.py`
- Modify: `src/ai/analyzer.py`
- Modify: `src/ai/analysis_cache.py`
- Test: `tests/test_analyzer.py`

- [x] Update prompt schema to request `channel`, `topics`, `signal_strength`, `signal_type`, and `entities`.
- [x] Parse new fields, normalize them, and populate legacy `ai_category/ai_tags` from `ai_channel/ai_topics`.
- [x] Bump the analysis cache prompt version and persist/load the new fields.
- [x] Verify `personal_tags` still do not enter AI prompts.

### Task 4: Static Payload And UI Filters

**Files:**
- Modify: `src/ui/site.py`
- Modify: `src/ui/static/reader.js`
- Modify: `src/ui/static/utils.js`
- Modify: `src/ui/static/config.js`
- Test: `tests/test_static_reading_ui.py`

- [x] Serialize new fields to `radar-data.json`, keeping `category/tags` aliases.
- [x] Stop treating non-canonical topics as personal tags.
- [x] Render channel, topics, and signal labels in the reading UI.
- [x] Search and filter across channel/topics/entities while preserving old tag filters.

### Task 5: Archive Storage

**Files:**
- Modify: `src/storage/article_store.py`
- Test: `tests/test_article_graph.py`

- [x] Persist `channel`, `topics_json`, `signal_strength`, `signal_type`, and `entities_json` to `articles_light`.
- [x] Keep `category/tags_json` populated as compatibility aliases.
- [x] Migrate existing `articles_light` tables in place.
- [x] Return new fields from archive load paths with legacy fallbacks.

### Task 6: Verification

**Files:**
- Python files changed above
- Static JS files changed above

- [x] Run `python3 -m py_compile` on changed Python files.
- [x] Run `node --check src/ui/static/*.js`.
- [x] Run targeted pytest for config server, analyzer, static UI, orchestrator token budget, and article graph.

### Task 7: Real-Run Checklist

**Files:**
- Add: `docs/dev/hub-taxonomy-real-run.md`

- [x] Document no-secret validation rules.
- [x] Document cheap single-source UI validation.
- [x] Document optional archive/SQLite validation.
