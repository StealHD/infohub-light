<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=AGENTS.md -->
# Inteliscope InfoHub Light Agent Guide

<!-- init-pro:section name=purpose -->
## 1. Project Context
Inteliscope InfoHub Light is a private multi-user, multi-source information hub. Its current product job is source subscription, acquisition, Feed display, per-user Feed history retention, and opt-in new-item notification for user-selected sources; archive analytics, recommendation, Graph, and in-site article proxying are not the current product line.

Current domain objects:

1. `ContentItem`: normalized item from RSS, GitHub, Reddit, Telegram, Hacker News, Apify social, OpenBB, or OSS Insight.
2. Source catalog and subscriptions: user-managed source definitions and per-user subscription state in the Service database; `data/config.json` remains a legacy/global compatibility input.
3. Hub taxonomy: `channel`, `topics`, `signal_strength`, `signal_type`, `entities`, with legacy `category/tags` compatibility.
4. User Feed snapshots: latest and historical per-user payloads stored in `data/service.db`, consumed by the React UI through `/api/*`.
5. Retired runtime artifacts such as `data/site/**`, `data/horizon.db`, summaries and local MCP runs are operator-owned inert data: current code must not read, migrate, rewrite or delete them.

## 2. Hard Constraints
- Do not put API keys, webhook URLs, Telegram Bot Tokens, Telegram Chat IDs, Apify tokens, or model keys in JSON config or code. Store environment variable names only.
- Personal tags are user preference signals and must not be sent to AI scoring prompts.
- `analysis_mode=personal_only` items enter history and personal feed but skip AI analysis, featured selection, and daily push.
- Prefer targeted tests and static checks before running full fetch, enrichment, or push workflows.
- Before commit, final-main verification, or deployment, inspect the task-scoped diff and fix every known or high-confidence defect with directly affected tests, then run one impacted `preflight`. After a full-gate failure, rerun the failing spec first and run the complete gate at most once more. Never knowingly defer a visible defect to CI, Docker, or VPS failure.
- Code-size policy freezes historical monolith paths against task-start growth; shrinking a frozen file never requires a policy edit. New files and functions use the hard limits defined only in `tests/code_size_policy.json`. Put new behavior in focused modules instead of growing a frozen file.
- Do not read `data/site/history-data.json`, `data/site/history/**`, cached media, full logs, generated summaries, or `data/horizon.db` unless the task specifically concerns those files.
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
4. `docs/contracts/api/`: Service, Gateway, storage and ActorOps interfaces.
5. `docs/contracts/architecture/`: module ownership and layering boundaries.
6. `docs/contracts/ui/`: React visual system, interaction and browser acceptance.
7. `docs/decisions/`: durable decision reasons and compatibility rationale.
8. `WORKLOG.md`: compact task execution record.
9. `project-defaults.yaml`: editable capabilities, limits, and output behavior.

`AGENTS.md` is intentionally both the `instructions` and `context` authority. Historical plans, former context rules, superseded runbooks and implementation reports live under `archive/project-history/` and are never default context.

## 4. 控制文件唯一真源
Use one authoritative file for each topic:

| Topic | Source of truth |
|---|---|
| Machine-readable control topic mapping and worklog policy | `project-controls.json` |
| Overall goal, hard constraints, output format | `AGENTS.md` |
| Current phase, priorities, non-goals | `PLAN.md` |
| Service API and current compatibility interfaces | `docs/contracts/api/` |
| Layering and module boundaries | `docs/contracts/architecture/` |
| React visual system, UI components, layout, interaction and visual gates | `docs/contracts/ui/` |
| Runtime/operation logging, redaction, retention and safe query rules | `docs/dev/observability-logging.md` |
| Decision reasons and compatibility rationale | `docs/decisions/` |
| Context reading strategy | this section of `AGENTS.md` |
| Execution history | `WORKLOG.md` |
| Editable defaults and capability vocabulary | `project-defaults.yaml` |

Do not duplicate a rule across several Markdown files. Update the source of truth and record the reason in `docs/decisions/` when the rule meaning changes.

## 5. Agent 默认读取范围与任务读取路由
For most coding tasks, start with:

1. `AGENTS.md` (the applicable root or nested file)
2. `PLAN.md`
3. Task-relevant code and tests

Read `project-defaults.yaml` only when capability, limit, degradation, provider or output vocabulary matters. Do not load a whole interface, architecture, UI or decision contract for an ordinary fix.

| Task | Expand context with |
| --- | --- |
| API, public payload, auth, error, Job or compatibility | `docs/contracts/api/README.md`, then only the linked module |
| Source/AI/frontend/store/tenant boundary | `docs/contracts/architecture/README.md`, then only the linked module |
| React visual, layout, interaction or browser acceptance | `docs/contracts/ui/README.md`, its linked module, relevant `frontend/src/` and Vitest/Playwright |
| Storage or migration | API Feed/storage module, architecture runtime/migration module, target migration and tests |
| Remote MCP or Browser OpenClaw | API Remote MCP/Gateway module, target integration code and tests |
| Durable reason, supersession or compatibility dispute | `docs/decisions/README.md`, then the matching record bucket |
| Historical report or old runbook | `archive/project-history/README.md`, then a targeted `rg` result |
| Control-plane change | `project-controls.json`, the affected authority and this section |

For broad orientation or taxonomy/backend changes, also read:

1. `src/models.py`
2. `src/orchestrator.py`
3. `src/services/config_runtime.py`
4. `src/services/feed_payload.py`
5. Task-relevant tests

For scraper work, read the target adapter under `src/scrapers/` and its matching tests.

## 6. Verification
- Create a task baseline with `python scripts/test_gate.py snapshot --output /tmp/impact.json`; snapshot schema v2 records `base_sha`, so `preflight --snapshot` compares frozen files with the task start. `preflight --staged` compares with HEAD, while `--base BASE --head HEAD` covers committed ranges.
- During development run only the directly affected Pytest, Vitest, or Playwright spec, followed by one impacted-domain preflight. PR Linux UI runs only mapped E2E specs; ActorOps, Workbench, and owned visual snapshots have explicit mappings, while App Shell, design-system, global routing, and unknown UI changes fail closed to all E2E.
- PR/main verification still runs the full impacted backend/frontend code domain; a main push runs the one authoritative complete Playwright gate for that final SHA. Global dependency/build changes fail closed to both code domains. A formal VPS release reuses that exact successful main Gate, then creates the version tag; the tag workflow verifies the same main result and runs only the isolated API Docker smoke. Never create or push a release tag before the exact main SHA is green.
- The standard `scripts/release_vps.sh` path runs bounded impacted preflight before reusing the exact main CI result; it may fail closed to full code checks but must not run release Docker smoke, complete Playwright, or replace the authoritative main gate. `release` smoke must not run real-source smoke, paid providers, AI, Worker, notifications, or any retired scheduler.
- Selector ownership is `tests/test_impact_map.json`. Unmapped executable code, dependency manifests, and build configuration fail closed to full. The fast E2E contract check rejects hard-coded preview ports, count-before-transient-inert assertions, and nondeterministic visual setup before Playwright starts.
- Gate logs stay under ignored `.test-results/<run-id>/` with private permissions. Read only the named failing log section when the bounded first-failure summary is insufficient.
- Rebuild the local web service by running `./scripts/up-latest.sh` from the target task Worktree. The script must build that Worktree while resolving `.env`, `data`, and `logs` from the primary checkout through Git's common directory; use `--runtime-root ABSOLUTE_PATH` only for an intentional alternate runtime. Do not replace this with a temporary Compose override, runtime symlinks, or a build from the primary checkout. The command holds one host-local lock for the shared Compose project and containers. Local and VPS cutover share `scripts/runtime_health.py`: completion requires target version/revision, API and Worker readiness, both Docker health states, served React asset, and public revision where applicable. Docker `starting` keeps waiting; only `unhealthy` or timeout fails. Rollback is successful only after the old API/Worker are healthy; a migration rollback must set `INTELISCOPE_PRE_MIGRATION_BACKUP` to the validated pre-migration backup before cutover. Required migrations remain explicit and are never applied automatically.
- Control-plane validation: this repository uses init-pro schema 3. Run `python scripts/check_markdown_controls.py`, `validate_project_controls.py --project-root . --format markdown`, `worklogctl.py validate --project-root .`, `python3 -m json.tool project-controls.json`, `python3 -m json.tool project-defaults.yaml`, and `git diff --check`. Keep validator output on stdout unless a persistent report is explicitly requested.

<!-- init-pro:section name=ownership -->
## 7. 控制文件维护规则
Do not modify Markdown control files by default during ordinary coding tasks.

Modify control files only when the 控制面发生变化, including:

1. API, runtime entrypoint, public payload, or storage contract changes.
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

<skills_system priority="1">

## Available Skills

<!-- SKILLS_TABLE_START -->
<usage>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke: `npx openskills read <skill-name>` (run in your shell)
  - For multiple: `npx openskills read skill-one,skill-two`
- The skill content will load with detailed instructions on how to complete the task
- Base directory provided in output for resolving bundled resources (references/, scripts/, assets/)

Usage notes:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in your context
- Each skill invocation is stateless
</usage>

<available_skills>

<skill>
<name>kaoyan-reading</name>
<description>考研阅读长难句训练。给定日期后从 hehonghui/awesome-english-ebooks 抓取最近一期《The Economist》,挑出 20 个高价值长难句段落,产出主干/结构树/中英翻译/考研词汇/考点提示,再抽写作万能句型,并把词汇通过 AnkiConnect(http://127.0.0.1:8765)导入 Anki。牌组命名:经济学人::{文章标题}::{YYYY-MM-DD}。报告固定写到 ~/Documents/jie/word/output/。触发:考研阅读、长难句训练、经济学人精读、kaoyan-reading、考研英语精读。</description>
<location>global</location>
</skill>

</available_skills>
<!-- SKILLS_TABLE_END -->

</skills_system>
