# Inteliscope Project Map

## Core Flow
- `src/orchestrator.py`: fetch, dedupe, AI analysis, enrichment, summaries, notifications, web payload generation.
- `src/models.py`: Pydantic config and content models.
- `src/config_migration.py`: compatibility migrations for config shape, especially tag layering.

## AI Cost Path
- `src/ai/analyzer.py`: first-pass scoring prompt, prompt truncation, analysis cache integration.
- `src/ai/analysis_cache.py`: JSONL cache for analysis results.
- `src/ai/enricher.py`: second-pass background enrichment.
- `src/ai/tokens.py`: provider and workflow-stage token usage counters.

## Sources
- `src/scrapers/rss.py`, `github.py`, `reddit.py`, `telegram.py`: native source adapters.
- `src/scrapers/apify_social.py`: X, Instagram, Facebook, Telegram through Apify.
- Source configs use `tags` for AI taxonomy and `personal_tags` for user preference labels.

## Web UI
- `src/ui/server.py`: local config API, structured config actions, source tests.
- `src/ui/site.py`: serializes `ContentItem` into static JSON and copies static assets.
- `src/ui/static/state.js`: storage keys, view constants, shared state.
- `src/ui/static/utils.js`: formatting, filtering, tag library helpers.
- `src/ui/static/media.js`: images, thumbnails, lightbox.
- `src/ui/static/reader.js`: queue, reader, context, reader actions.
- `src/ui/static/config.js`: config forms, tag editors, source forms.
- `src/ui/static/app.js`: data loading and startup binding.

## Tests
- `tests/test_config_server.py`: config validation/actions and source-test API behavior.
- `tests/test_analyzer.py`: AI analysis behavior and cache.
- `tests/test_token_usage.py`: token accounting.
- `tests/test_orchestrator_token_budget.py`: personal-only analysis partitioning.
- `tests/test_static_reading_ui.py`: static UI contract checks.
