# Token Budget Notes

## Development Context
- Read targeted files only. Avoid generated `data/site/**`, historical snapshots, logs, and cached media unless debugging those outputs.
- Use `rg` to locate code paths before opening files.
- Prefer `node --check src/ui/static/*.js` and targeted pytest files over full Docker fetch runs.

## Runtime Model Usage
- First-pass analysis is the main per-item token cost.
- Enrichment and summary are second-stage costs and should run only for high-scoring items or explicit daily jobs.
- `analysis_mode=personal_only` skips model scoring for preference-only sources such as personal Instagram accounts.
- Analysis cache lives at `data/cache/analysis-cache.jsonl` and is keyed by content hash, model, and prompt version.

## Config Knobs
- `ai.analysis_content_chars`: max content chars sent to scoring.
- `ai.analysis_comments_chars`: max comment chars sent to scoring.
- `ai.enrichment_content_chars`: max content chars sent to enrichment.
- `sources.apify_social.subscriptions[].analysis_mode`: `full` or `personal_only`.

## Interpreting Usage
- Runtime output prints total tokens by provider and by stage: `analysis`, `dedupe`, `enrichment`, `summary`, or `uncategorized`.
- If analysis dominates, reduce fetch limits, enable `personal_only` for preference feeds, or rely on cache.
- If enrichment dominates, run incremental polling with enrichment disabled and keep enrichment for daily runs.
