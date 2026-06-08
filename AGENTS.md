# Inteliscope Agent Guide

## Default Read Scope
- Start with `src/models.py`, `src/orchestrator.py`, `src/ui/server.py`, `src/ui/site.py`, and the task-relevant tests.
- For frontend work, read only the relevant file under `src/ui/static/`: `state.js`, `utils.js`, `media.js`, `reader.js`, `config.js`, or `app.js`.
- For scraper work, read the target adapter under `src/scrapers/` and its matching tests.

## Avoid By Default
- Do not read `data/site/history-data.json`, `data/site/history/**`, cached media, full logs, or generated summaries unless the task is specifically about those files.
- Do not run the full scheduler while developing a narrow change.
- Do not put API keys, webhook URLs, Apify tokens, or model keys in JSON config or code. Store environment variable names only.

## Verification
- Python syntax smoke: `python3 -m py_compile <changed python files>`.
- Static UI syntax: `node --check src/ui/static/*.js`.
- Targeted tests in Docker when local `uv` is unavailable: `docker compose run --rm --entrypoint sh horizon -lc "uv run --extra dev pytest <tests> -q"`.
- Rebuild latest local web service: `./scripts/up-latest.sh`.

## Runtime Cost Rules
- Personal tags are user preference signals and must not be sent to AI scoring prompts.
- `analysis_mode=personal_only` items enter history and personal feed but skip AI analysis, featured selection, and daily push.
- Prefer targeted tests and static checks before running full fetch/enrichment.
