# Hub Taxonomy Real-Run Checklist

Use this checklist after taxonomy code changes when validating against real local data.

## 1. Secret Safety

- Keep API keys and webhook URLs in `.env` only.
- In `data/config.json`, keep environment variable names such as `api_key_env`, not raw keys.
- Before a full run, confirm email and webhook delivery are disabled unless a push is intentional.

## 2. Rebuild Local Web

```bash
./scripts/up-latest.sh
```

The current light compose file starts `horizon-api` by default and serves the static UI through FastAPI. It does not start the scheduler unless the scheduler profile is explicitly used.

Open:

```text
http://127.0.0.1:8080
```

If `HORIZON_WEB_PORT` is set in `.env`, use that port instead.

## 3. Service API Real-Source Smoke

Use this path for the small-group multi-user service. It validates the real catalog flow:

```text
catalog source -> subscription -> source_test job -> source_fetch job -> worker -> user feed snapshot -> archive/source-quality API
```

Required sources:

- RSS: `https://github.blog/feed/`
- Hacker News: public Firebase top stories
- GitHub Releases: `openai/codex`
- Telegram public channel: `durov`

Optional/degraded sources:

- Reddit `LocalLLaMA`, which may return 403 from public endpoints.
- Apify social smoke only when `APIFY_TOKEN` is already present; the script stores only `secret_env=APIFY_TOKEN`.

Run against a local service:

```bash
docker compose -f docker-compose.light.yml up -d --build horizon-api
uv run python scripts/service_real_source_smoke.py \
  --base-url http://127.0.0.1:8080 \
  --run-worker \
  --hours 168
```

Expected:

- The report is written to `logs/service-real-source-smoke-*.json`.
- Required `source_test` jobs succeed.
- RSS and Hacker News `source_fetch` jobs succeed.
- `/api/feed/latest` returns `scope=user`, a `snapshot_id`, and at least one item.
- `/api/archive/source-quality` returns the user-scoped source quality payload.

## 4. Cheap UI Validation

Run one explicit source first. This path skips notifications, summaries, enrichment, full-text, and article graph work.

```bash
docker compose -f docker-compose.light.yml run --rm horizon --source rss:0 --hours 24
```

Then verify `data/site/radar-data.json` contains both new fields and legacy aliases:

```bash
python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("data/site/radar-data.json").read_text(encoding="utf-8"))
items = payload.get("today_items") or payload.get("items") or []
for item in items[:5]:
    print({
        "channel": item.get("channel"),
        "topics": item.get("topics"),
        "category": item.get("category"),
        "tags": item.get("tags"),
        "signal_strength": item.get("signal_strength"),
        "signal_type": item.get("signal_type"),
        "entities": item.get("entities"),
    })
PY
```

Expected:

- `channel` is one of the Hub channels: `AI`, `投资`, `产品机会`, `工作/项目`, `朋友动态`, `生活`, `政策/风险`, `其他`.
- `topics` drives second-level filtering and matches the legacy `tags` alias.
- `category` remains a legacy alias for `channel`.
- Custom reading topics remain in `topics/tags`; they are not moved into `personal_tags`.

## 5. Archive Validation

Enable `premium_analysis.enabled` or `article_graph.enabled` only when you want the SQLite archive path to run. Then run one full workflow:

```bash
docker compose -f docker-compose.light.yml run --rm horizon --hours 24
```

Inspect the light article table:

```bash
sqlite3 data/horizon.db "PRAGMA table_info(articles_light);"
sqlite3 data/horizon.db "SELECT channel, topics_json, signal_strength, signal_type, entities_json FROM articles_light ORDER BY updated_at DESC LIMIT 5;"
```

Expected columns:

- `channel`
- `topics_json`
- `signal_strength`
- `signal_type`
- `entities_json`

Expected compatibility:

- Old `category/tags_json` fields are still populated.
- Existing old databases are migrated in place by `ArticleStore.initialize()`.
- Historical rows without new fields still read back with `channel/category` and `topics/tags` fallbacks.

## 6. Regression Commands

```bash
python3 -m py_compile src/tag_policy.py src/config_migration.py src/models.py src/scrapers/base.py src/ui/server.py src/ai/prompts.py src/ai/analyzer.py src/ai/analysis_cache.py src/orchestrator.py src/ui/site.py src/storage/article_store.py
node --check src/ui/static/*.js
docker run --rm --entrypoint sh -v "$PWD":/app -w /app infohub-light-horizon:latest -lc "uv run --extra dev pytest tests/test_config_server.py tests/test_analyzer.py tests/test_static_reading_ui.py tests/test_orchestrator_token_budget.py tests/test_article_graph.py -q"
```
