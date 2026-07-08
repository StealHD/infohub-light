# Inteliscope InfoHub Light Agent Guide

## 1. Project Context
Inteliscope InfoHub Light is a private multi-source information hub. Its current product job is to help the user quickly read and filter personal information by Hub taxonomy, then preserve enough structured fields for later archive analysis.

Current domain objects:

1. `ContentItem`: normalized item from RSS, GitHub, Reddit, Telegram, Hacker News, Apify social, OpenBB, or OSS Insight.
2. Source config: user-managed runtime source definitions under `data/config.json`.
3. Hub taxonomy: `channel`, `topics`, `signal_strength`, `signal_type`, `entities`, with legacy `category/tags` compatibility.
4. Static site payloads: `data/site/radar-data.json`, history JSON, and static UI assets.
5. Optional archive: `data/horizon.db` and article graph JSON.

## 2. Hard Constraints
- Do not put API keys, webhook URLs, Apify tokens, or model keys in JSON config or code. Store environment variable names only.
- Personal tags are user preference signals and must not be sent to AI scoring prompts.
- `analysis_mode=personal_only` items enter history and personal feed but skip AI analysis, featured selection, and daily push.
- Prefer targeted tests and static checks before running full fetch, enrichment, full-text, scheduler, or push workflows.
- Do not read `data/site/history-data.json`, `data/site/history/**`, cached media, full logs, generated summaries, or `data/horizon.db` unless the task specifically concerns those files.
- Do not run the full scheduler while developing a narrow change.

## 3. Control Files
Current control plane files:

1. `AGENTS.md`: highest-level project constraints, output format, worklog rule, and unique source-of-truth map.
2. `PLAN.md`: current phase, implementation order, non-goals, and verification order.
3. `API_CONTRACT.md`: CLI, Web config API, static JSON, and archive interface contract.
4. `ARCHITECTURE_CONTRACT.md`: module ownership and layering boundaries.
5. `DECISION_LOG.md`: reasons for durable control-plane decisions.
6. `CONTEXT_READ_RULES.md`: minimal context strategy and task-specific read expansion.
7. `WORKLOG.md`: compact task execution record.
8. `project-defaults.yaml`: editable control-plane defaults, capabilities, limits, and output behavior.

## 4. 控制文件唯一真源
Use one authoritative file for each topic:

| Topic | Source of truth |
|---|---|
| Overall goal, hard constraints, output format | `AGENTS.md` |
| Current phase, priorities, non-goals | `PLAN.md` |
| CLI, Web API, static payload, archive contract | `API_CONTRACT.md` |
| Layering and module boundaries | `ARCHITECTURE_CONTRACT.md` |
| Decision reasons and compatibility rationale | `DECISION_LOG.md` |
| Context reading strategy | `CONTEXT_READ_RULES.md` |
| Execution history | `WORKLOG.md` |
| Editable defaults and capability vocabulary | `project-defaults.yaml` |

Do not duplicate a rule across several Markdown files. Update the source of truth and record the reason in `DECISION_LOG.md` when the rule meaning changes.

## 5. Agent 默认读取范围
For most coding tasks, start with:

1. `PLAN.md`
2. `API_CONTRACT.md`
3. `project-defaults.yaml`
4. Task-relevant code
5. Task-relevant tests

For broad orientation or taxonomy/backend changes, also read:

1. `src/models.py`
2. `src/orchestrator.py`
3. `src/ui/server.py`
4. `src/ui/site.py`
5. Task-relevant tests

For frontend work, read only the relevant file under `src/ui/static/`: `state.js`, `utils.js`, `media.js`, `reader.js`, `config.js`, `article_graph.js`, or `app.js`.

For scraper work, read the target adapter under `src/scrapers/` and its matching tests.

## 6. Verification
- Python syntax smoke: `python3 -m py_compile <changed python files>`.
- Static UI syntax: `node --check src/ui/static/*.js`.
- Targeted tests in Docker when local `uv` is unavailable: `docker compose run --rm --entrypoint sh horizon -lc "uv run --extra dev pytest <tests> -q"`.
- Light-compose targeted tests: `docker compose -f docker-compose.light.yml run --rm --no-deps --entrypoint sh horizon -lc "uv run --extra dev pytest <tests> -q"`.
- Rebuild latest local web service: `./scripts/up-latest.sh`.
- Control-plane validation: `python3 "${CODEX_HOME:-$HOME/.codex}/skills/init-pro/scripts/validate_project_controls.py" --project-root . --primary-config project-defaults.yaml --output INIT_PRO_VALIDATION.md`.

## 7. 控制文件维护规则
Do not modify Markdown control files by default during ordinary coding tasks.

Modify control files only when the 控制面发生变化, including:

1. API, CLI, static payload, or archive contract changes.
2. Architecture boundary changes.
3. Capability, degrade, unsupported, or unknown vocabulary changes.
4. Rule, threshold, taxonomy, or output-shape changes.
5. Context-read strategy changes.
6. Current phase, non-goal, or hard-constraint changes.

For ordinary fixes or tests with no control-plane change, update only `WORKLOG.md`.

## 8. Worklog Rule
Every agent task must append one concise entry to `WORKLOG.md` before final response.

Use the template already present in `WORKLOG.md`. Keep entries short and do not paste large command output.

## 9. 默认回复格式
Unless the user explicitly asks for expanded analysis, final responses should be compact:

```md
状态：成功 / 部分完成 / 阻塞
结果：一句话说明做成了什么
验证：测试是否通过，接口是否验证
阻塞：如果有，列 1~3 条；如果没有可省略
文件：只列修改过的关键文件路径，最多 8 个
```
