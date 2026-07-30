<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=AGENTS.md -->
# Inteliscope InfoHub Light Agent Guide

<!-- init-pro:section name=purpose -->
## 1. Project Context
Inteliscope InfoHub Light is a private multi-user, multi-source information hub. Its current product job is source subscription, acquisition, Feed display, per-user Feed history retention, and opt-in new-item notification for user-selected sources; archive analytics, recommendation, Graph, and in-site article proxying are not the current product line.

Current domain objects:

1. `ContentItem`: normalized item from RSS, GitHub, Reddit, Telegram, Hacker News, Apify social, OpenBB, or OSS Insight.
2. Source catalog and subscriptions: user-managed source definitions and per-user subscription state in the Service database; `data/config.json` remains a legacy/global compatibility input.
3. Hub taxonomy: `channel`, `topics`, `signal_strength`, `signal_type`, `entities`, with legacy `category/tags` compatibility.
4. User Feed snapshots: latest and historical per-user payloads stored in `data/service.db`, plus static UI assets that consume `/api/*`.
5. Legacy optional outputs: `data/site/*.json`, `data/horizon.db`, and article graph JSON; the old CLI publisher may maintain them, but the default Service UI/API does not depend on them.

## 2. Hard Constraints
- Do not put API keys, webhook URLs, Telegram Bot Tokens, Telegram Chat IDs, Apify tokens, or model keys in JSON config or code. Store environment variable names only.
- Personal tags are user preference signals and must not be sent to AI scoring prompts.
- `analysis_mode=personal_only` items enter history and personal feed but skip AI analysis, featured selection, and daily push.
- Prefer targeted tests and static checks before running full fetch, enrichment, full-text, scheduler, or push workflows.
- Do not read `data/site/history-data.json`, `data/site/history/**`, cached media, full logs, generated summaries, or `data/horizon.db` unless the task specifically concerns those files.
- Do not run the full scheduler while developing a narrow change.
- Keys pasted into a task are compromised evidence: never persist or call them. DeepSeek activation requires a replacement value written through SecretStore and a one-call smoke.
- `content_repair` may refetch only free sources in bulk, updates existing stable content only, and must never create a Feed snapshot or call AI. Paid social repair requires separate per-item authorization.
- Every merge containing product code must review both `frontend/src/features/manual/manualContent.ts` and `frontend/src/features/changelog/changelogEntries.ts`; `scripts/check_product_docs.py` enforces this in the Test Gate.
- Never build an Inteliscope production image on `vps-tokyo`. Build the revision-locked `linux/amd64` image locally, verify it, upload the image archive, and use `docker load` on the VPS. The VPS may pull pinned third-party runtime images such as RSSHub, but it must not compile or build this repository.

<!-- init-pro:section name=precedence -->
## 3. Control Files
Current control plane files:

1. `project-controls.json`: init-pro schema-v3 machine-readable topic map and compact worklog policy.
2. `AGENTS.md`: highest-level project constraints, output format, worklog rule, and unique source-of-truth map.
3. `PLAN.md`: current phase, implementation order, non-goals, and verification order.
4. `API_CONTRACT.md`: Service Feed/retention API plus legacy CLI, static payload, archive, feedback, and Graph compatibility contracts.
5. `ARCHITECTURE_CONTRACT.md`: module ownership and layering boundaries.
6. `DECISION_LOG.md`: reasons for durable control-plane decisions.
7. `CONTEXT_READ_RULES.md`: minimal context strategy and task-specific read expansion.
8. `WORKLOG.md`: compact task execution record.
9. `project-defaults.yaml`: editable capabilities, limits, and output behavior.

## 4. 控制文件唯一真源
Use one authoritative file for each topic:

| Topic | Source of truth |
|---|---|
| Machine-readable control topic mapping and worklog policy | `project-controls.json` |
| Overall goal, hard constraints, output format | `AGENTS.md` |
| Current phase, priorities, non-goals | `PLAN.md` |
| Service API and legacy compatibility interfaces | `API_CONTRACT.md` |
| Layering and module boundaries | `ARCHITECTURE_CONTRACT.md` |
| React visual system, UI components, layout, interaction and visual gates | `UI_CONTRACT.md` |
| Runtime/operation logging, redaction, retention and safe query rules | `docs/dev/observability-logging.md` |
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

For React frontend work, read `UI_CONTRACT.md`, the relevant file under `frontend/src/`, and its matching Vitest or Playwright test. For legacy UI work, read only the relevant file under `src/ui/static/`: `state.js`, `utils.js`, `media.js`, `reader.js`, `config.js`, `subscriptions.js`, `auth.js`, or `app.js`.

For scraper work, read the target adapter under `src/scrapers/` and its matching tests.

## 6. Verification
- Observation phase default: `python scripts/test_gate.py run --mode full`. Do not paste or automatically read its complete logs; use the compact stdout summary first.
- A task may create a hash baseline with `python scripts/test_gate.py snapshot --output /tmp/impact.json`, inspect it with `python scripts/test_gate.py plan --snapshot /tmp/impact.json --json`, and explicitly run `targeted` for local iteration. Until 10 distinct CI commits satisfy the observation criteria in `PLAN.md`, `targeted` is not the default completion gate.
- PR/main and merge verification permanently use `python scripts/test_gate.py run --mode full`; formal release verification uses `python scripts/test_gate.py run --mode release`.
- `release` may run Playwright and the isolated `docker-compose.test-gate.yml` API-only smoke. It must not run real-source smoke, paid providers, AI, Worker, or scheduler.
- Selector ownership is `tests/test_impact_map.json`. Unmapped executable code, dependency manifests, and build configuration fail closed to full.
- Gate logs stay under ignored `.test-results/<run-id>/` with private permissions. Read only the named failing log section when the bounded first-failure summary is insufficient.
- Rebuild the local web service by running `./scripts/up-latest.sh` from the target task Worktree. The script must build that Worktree while resolving `.env`, `data`, and `logs` from the primary checkout through Git's common directory; use `--runtime-root ABSOLUTE_PATH` only for an intentional alternate runtime. Do not replace this with a temporary Compose override, runtime symlinks, or a build from the primary checkout. The command holds one host-local lock for the shared Compose project and containers. A rebuild is complete only after the target revision, API readiness with a ready Worker, both container health checks, and the served React asset all pass and the terminal state is rechecked; image build alone is never completion. Required database migrations remain explicit, backup-producing actions and must not be applied automatically.
- Control-plane validation: this repository uses init-pro schema 3. Run `validate_project_controls.py --project-root . --format markdown`, `worklogctl.py validate --project-root .`, `python3 -m json.tool project-controls.json`, `python3 -m json.tool project-defaults.yaml`, and `git diff --check`. Keep validator output on stdout unless a persistent report is explicitly requested.

<!-- init-pro:section name=ownership -->
## 7. 控制文件维护规则
Do not modify Markdown control files by default during ordinary coding tasks.

Modify control files only when the 控制面发生变化, including:

1. API, CLI, static payload, or archive contract changes.
2. Architecture boundary changes.
3. Capability, degrade, unsupported, or unknown vocabulary changes.
4. Rule, threshold, taxonomy, or output-shape changes.
5. Context-read strategy changes.
6. Current phase, non-goal, or hard-constraint changes.

For ordinary fixes or tests with no control-plane change, append only one compact entry through `worklogctl.py`.

<!-- init-pro:section name=worklog-policy -->
## 8. Worklog Rule
Every implementation task must append one concise entry through `worklogctl.py append` before final response. Do not edit compact entries manually.

Keep at most 20 active entries in `WORKLOG.md`; the tool rotates older compact entries into `archive/worklog/YYYY-MM.md`. The byte-preserved schema-v2 history under `archive/legacy-worklog/` is not part of default context and must only be searched when a task needs historical evidence.

<!-- init-pro:section name=output-policy -->
## 9. 默认回复格式
Unless the user explicitly asks for expanded analysis, final responses should be compact:

```md
状态：成功 / 部分完成 / 阻塞
结果：一句话说明做成了什么
验证：测试是否通过，接口是否验证
阻塞：如果有，列 1~3 条；如果没有可省略
文件：只列修改过的关键文件路径，最多 8 个
```
