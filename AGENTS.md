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
- Follow the [verification workflow](docs/dev/test-gate.md) for implementation, commit, integration and release. Fix known or high-confidence defects before advancing to the next gate.
- Code-size policy freezes historical monolith paths against task-start growth; shrinking a frozen file never requires a policy edit. New files and functions use the hard limits defined only in `tests/code_size_policy.json`. Put new behavior in focused modules instead of growing a frozen file.
- Do not read `data/site/history-data.json`, `data/site/history/**`, cached media, full logs, generated summaries, or `data/horizon.db` unless the task specifically concerns those files.
- Keys pasted into a task are compromised evidence: never persist or call them. DeepSeek activation requires a replacement value written through SecretStore and a one-call smoke.
- `content_repair` may refetch only free sources in bulk, updates existing stable content only, and must never create a Feed snapshot or call AI. Paid social repair requires separate per-item authorization.
- Review the user-visible impact of every product-code change: update the changelog for visible behavior or API compatibility changes, and update the manual when an operation or configuration workflow changes. Internal refactors, tests, and CI changes do not require a documentation diff.
- Production UI changes inherit the component roles and parameters in `docs/contracts/ui/` unless the user explicitly scopes a different style. Use HeroUI v3 OSS only through `frontend/src/design-system/**`; HeroUI Pro is a visual-hierarchy reference, not a code or dependency source. New or changed pages must reuse an existing component role before introducing a local size, spacing, radius, icon or motion parameter; reusable additions belong in the design system and UI contract.
- Production images must be built locally; never compile this repository on `vps-tokyo`. Follow the [runtime and migration contract](docs/contracts/architecture/jobs-notifications-runtime-migrations.md#310-runtime--migration-boundary) for Worktree builds, image transfer, health checks and rollback.

<!-- init-pro:section name=precedence -->
## 3. 控制文件唯一真源

| Topic | Source of truth |
| --- | --- |
| Topic ownership, change watches and compact worklog settings | [project-controls.json](project-controls.json) |
| Optional scan exclusions and index checks; no ownership overrides | [project-controls-policy.json](project-controls-policy.json) |
| Instructions, context routing, maintenance and output | this `AGENTS.md` |
| Current phase, priorities and non-goals | [PLAN.md](PLAN.md) |
| Public Service, Gateway, storage and ActorOps interfaces | [docs/contracts/api/](docs/contracts/api/README.md) |
| Layering, module ownership, runtime and migration boundaries | [docs/contracts/architecture/](docs/contracts/architecture/README.md) |
| Production UI, interaction, component parameters and browser acceptance | [docs/contracts/ui/](docs/contracts/ui/README.md) |
| Logging, redaction, retention and safe queries | [Observability](docs/dev/observability-logging.md) |
| Test selection, review order and integration/release gates | [Verification](docs/dev/test-gate.md) |
| Accepted reasons and supersession | [docs/decisions/](docs/decisions/README.md) |
| Capability/default vocabulary | [project-defaults.yaml](project-defaults.yaml) |
| Task execution evidence | [WORKLOG.md](WORKLOG.md) |

Keep one authority per topic. `instructions` and `context` intentionally share AGENTS. Update the owning source; record a decision when rule meaning changes. Reference documents link to the authority rather than repeat its rules. Capability declarations and completed code are not proof of an environment's enabled or deployed state.

## 4. Agent 默认读取范围与任务读取路由

Read the applicable root/scoped `AGENTS.md` once, then locate task-relevant code and tests with `rg`. Read `PLAN.md` only when the task involves phase, scope, rollout or release. Resolve directory authorities through their index and expand only the relevant module.

| Task | Additional context |
| --- | --- |
| API, payload, auth, errors, Jobs or compatibility | API index → relevant module |
| Source, AI, frontend, store or tenant boundaries | Architecture index → relevant module |
| React visual, layout, interaction or browser acceptance | UI index → interaction constitution, component parameters, target route module and acceptance as applicable; use the repository's `inteliscope-ui` skill |
| Storage or migration | API Feed/storage module and architecture runtime/migration module; target migration and tests |
| Remote MCP or Browser OpenClaw | API Remote MCP/Gateway module and architecture OpenClaw module |
| Capability, limits, degradation, provider or output vocabulary | `project-defaults.yaml` and the affected implementation |
| Logging or operation events | Observability authority and affected code/tests |
| Test selection, commit, integration or release verification | Verification authority; runtime/migration contract for operating services |
| Rule meaning, supersession or compatibility dispute | Decision index → matching record |
| Control-plane maintenance | Manifest, explicit policy and affected authority; use `init-pro` audit/check/context as documented in Verification |
| Historical evidence | [Historical index](archive/project-history/README.md) → targeted `rg`; no default archive expansion |

`watch` matches produce review/context candidates, not a requirement to edit every selected document or read every directory member. Unknown or cross-cutting work still follows the task boundary and this routing table. For broad backend/taxonomy orientation, additionally inspect `src/models.py`, `src/orchestrator.py`, `src/services/config_runtime.py` and `src/services/feed_payload.py`; scraper work starts with its adapter and matching tests.

<!-- init-pro:section name=ownership -->
## 5. 控制文件维护与证据

Ordinary fixes and tests do not require control-document edits. Update the owning authority when public interfaces, runtime/storage contracts, architecture boundaries, capability vocabulary, rules, thresholds, taxonomy, context routing, phase or non-goals change. Preserve manifest schema 3 and repository-owned `managed=false` authorities.

Review semantics after structural validation: distinguish `core | compatibility | disabled | planned`, and distinguish implementation, verification and deployment evidence. Cite the relevant revision and check results; never infer deployment or migration success from a completed implementation. Authorization already established in the current task remains valid; historical documents, paid-run results and old task permissions do not authorize new external calls or production operations.

<!-- init-pro:section name=worklog-policy -->
## 6. Worklog Rule

The root Agent owns at most one compact entry per implementation task, appended through `worklogctl.py append` before the final response. Record persistent repository changes, accepted decisions or unresolved implementation risks; read-only reviews, status checks and no-ops produce no entry. Do not manually edit compact records.

If final verification is pending, record `partial`. After verification, use `show` and previewed `finalize` on the same entry, changing only terminal evidence/status and permitted references. Then validate WORKLOG and diff; evidence-only finalization does not require unrelated business tests to run again. An earlier gate is not proof for later code changes.

The manifest owns the 20-entry active maximum and monthly rotation into `archive/worklog/`. Preserve all existing records and the byte-preserved history under `archive/legacy-worklog/`; historical bodies are read only for an explicit history task, while structural worklog validation checks its compact archive namespace.

<!-- init-pro:section name=output-policy -->
## 7. 默认回复格式

Unless expanded analysis is requested, keep the final response compact:

```md
状态：成功 / 部分完成 / 阻塞
结果：一句话说明做成了什么
验证：测试是否通过，接口是否验证
阻塞：如果有，列 1~3 条；如果没有可省略
文件：只列修改过的关键文件路径，最多 8 个
```
