# Task 3 Report: HeroUI 订阅、助手连接、设置与登录

## Status

Completed. The authenticated development-only `/__preview/workbench-live` route family now includes HeroUI subscriptions, Agent connections, and settings pages, plus a standalone HeroUI login route. Legacy MUI routes, APIs, query keys, permissions, data models, and production defaults remain unchanged.

## RED evidence

Implementation used focused RED→GREEN loops before page code:

```text
npm test -- --run src/app/App.test.tsx -t 'live administration|live one-time|live settings|DEV-only HeroUI login'
RED: 4/4 selected tests failed because the live routes were missing or resolved to the legacy MUI pages.

npm test -- --run src/app/App.test.tsx -t 'explains a live single-source fetch block'
RED: the Worker-stale path did not expose a HeroUI-local blocked explanation.

npm test -- --run src/app/App.test.tsx -t 'applies the existing provider defaults'
RED: switching provider retained the Gemini model instead of applying the existing provider defaults.

npx playwright test e2e/live-admin.spec.ts
RED: 6/6 failed; the login assertion used the wrong product heading and Axe found the default HeroUI danger token at 4.34:1 contrast.
```

The subscription route was closed first, then Agents, Settings, and Login. Each page's focused test was made green before moving to the next page.

## Implementation

- Added `features/admin-heroui` modules for shared administration controls, subscription orchestration/dialogs/schema details, Agent lifecycle, settings/topic editing, and login.
- Preserved exactly three subscription tabs, effective-channel grouping, search-driven group expansion, type/health/scope filters, existing source/subscription permission functions, Worker preflight, job deduplication/cache invalidation, Chinese job presentation, technical details, response-schema states, and global/single-source schedules.
- Preserved Agent create/rename/revoke/copy/configuration flows. The one-time token uses component state only, cannot close via Escape or backdrop, and is cleared only by explicit “我已保存”.
- Reorganized settings into “助手与 AI / 获取与主题 / 密钥 / 成员”. Members receive the read-only explanation and Agent entry only; Owner/Admin retain the existing AI, topic, SecretStore, and member operations. Removed featured/daily controls from this surface.
- Secret create/rotate values are cleared immediately before the request; failed creation retains non-secret metadata. Existing provider defaults, including DeepSeek, are reused from `settingsModel`.
- Added the standalone HeroUI Card/Form/Input/Button login while preserving the existing authentication/error/password-clear/invalidation semantics.
- Updated the live shell so administration pages consume the full content column, omit Feed search/update controls and Agent queries/panel, and keep responsive live-family navigation. The shared MUI feedback surface is disabled only inside the live shell.
- Extended the design-system facade only with required HeroUI exports and corrected its dark-theme danger token to pass WCAG AA. Business modules import UI primitives only through `frontend/src/design-system`.
- Added desktop 1440×900, tablet 1024×768, and mobile 390×844 Playwright/Axe coverage for all four DEV page types, including no MUI, no Agent panel, and no horizontal overflow.

## Files changed

- `frontend/src/features/admin-heroui/**`
- `frontend/src/app/App.tsx`, `App.test.tsx`, `ActionFeedback.tsx`
- `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- `frontend/src/design-system/index.ts`, `theme.css`
- `frontend/e2e/live-admin.spec.ts`
- `.superpowers/sdd/task-3-report.md`
- `WORKLOG.md`

## GREEN verification

```text
npm test -- --run src/app/App.test.tsx
24/24 passed.

npm test
33 files / 158 tests passed.

npm run check:ui && npm run lint && npm run typecheck && npm run build
UI contract passed; ESLint 0 errors with 1 pre-existing Fast Refresh warning; TypeScript passed; production build and preview exclusion passed.

npx playwright test e2e/live-admin.spec.ts
6/6 passed across desktop/tablet/mobile; Axe serious/critical zero.

npx playwright test e2e/live-workbench.spec.ts --project=mobile --grep 'filtered unread-first'
1/1 passed on the isolated retry of the pre-existing virtual-anchor regression.

git diff --check
Passed.

python3 scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 57.338s.
```

## Self-review

- Confirmed the live administration route files have no direct `@heroui/*` or `@mui/*` imports.
- Confirmed no backend, API contract, database, ServiceApi method, query key, permission function, Remote MCP behavior, or production route changed.
- Confirmed legacy `/subscriptions`, `/agents`, `/settings`, and `/login` still render their existing MUI surfaces.
- Confirmed non-workbench live pages do not query or render the shell Agent panel and retain the full available content width at all acceptance viewports.
- Confirmed Viewer/read-only behavior, shared/private source edit rules, ActionGeneration guards, Worker preflight, polling, job presentation, and SecretStore semantics are reused rather than forked.
- Confirmed one-time tokens never enter React Query cache and cannot be dismissed accidentally.
- Confirmed the production build excludes the DEV preview family and that the repository full gate passes.

## Concerns

- A combined 15-test Playwright run under concurrency had one pre-existing mobile virtual-anchor assertion shift from item 147 to 149; the original isolated command immediately passed 1/1. Task 3's six acceptance tests passed in that combined run and in standalone runs.
- ESLint retains the pre-existing `ActionFeedback.tsx` Fast Refresh warning, and Vite retains the existing >500 kB chunk warning.
- The HeroUI route family remains intentionally DEV-only until the coordinated production cutover task.

## Review remediation — 2026-07-17

The Task 3 review findings were closed without changing backend, API, query-key, permission, or production-route contracts:

- Restored full single-source fetch lifecycle parity: optimistic `queued`, authoritative `running`, terminal `succeeded` / `partial` / `failed` / `cancelled`, per-job initiated metadata, terminal deduplication, terminal health/jobs/feed/history invalidation, sanitized local notices, and an idempotent running transition.
- Restored Owner/Admin member-role editing with the HeroUI Select while keeping Owner role/status protected and hiding member administration from Member/Viewer roles.
- Split run creation and completion timestamps, added the unfinished fallback, and retained retry for retryable terminal jobs.
- Added operational type/health/scope filter coverage, the complete source-edit permission matrix, safe response-schema state/value-redaction coverage, and successful HeroUI login redirect coverage.
- Replaced the nested native advanced-source `<details>` editor and native subscription fieldset with design-system `Fieldset` composition.
- Added a jsdom `getAnimations` compatibility shim required by HeroUI tab collection transitions in component tests.

Focused RED→GREEN evidence:

```text
npm test -- --run src/app/App.test.tsx -t 'settles a live source fetch|surfaces sanitized live source fetch|shows run creation'
RED: 5 failed / 24 skipped before lifecycle restoration.
GREEN: 5 passed / 32 skipped after queued/running/terminal parity and idempotence.

npm test -- --run src/app/App.test.tsx src/features/subscriptions/subscriptionModel.test.ts -t 'lets a live|does not expose live member|complete shared'
RED: Owner/Admin role-edit cases failed; Member/Viewer and model cases passed.
GREEN: 5 passed / 41 skipped.

npm test -- --run src/app/App.test.tsx -t 'redirects a successful HeroUI login|advanced source configuration'
RED: advanced editor still used native details; login redirect passed.
GREEN: 2 passed / 35 skipped.

npm test -- --run src/app/App.test.tsx src/features/admin-heroui/HeroResponseSchemaDetails.test.tsx -t 'operates live source|member-owned private|presents safe'
GREEN coverage confirmation: 3 passed / 33 skipped.
```

Final verification:

```text
npm test -- --run src/app/App.test.tsx src/features/subscriptions/subscriptionModel.test.ts src/features/admin-heroui/HeroResponseSchemaDetails.test.tsx
3 files / 51 tests passed.

npm test
34 files / 173 tests passed.

npm run check:ui && npm run lint && npm run typecheck && npm run build
UI contract, TypeScript, and production build/preview exclusion passed; ESLint 0 errors with the existing 1 Fast Refresh warning.

npx playwright test e2e/live-admin.spec.ts
6/6 passed across desktop/tablet/mobile.

git diff --check && python3 -m json.tool project-defaults.yaml >/dev/null
Passed.

python3 scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 57.642s.
```

## Feedback re-review remediation — 2026-07-17

The Important and Minor feedback findings were closed while retaining `ActionFeedback` as the only mutation feedback state and preserving the existing terminal invalidation/deduplication flow:

- Schedule, subscribe, unsubscribe, and retry now register pending/success/error records using action/entity keys. Their Select/Button labels and disabled states read those same entity records, suppressing duplicate requests without blocking unrelated rows.
- The Hero subscriptions page renders those records through an accessible local HeroUI alert/status surface, so the live shell's intentionally suppressed legacy notice surface no longer makes failures silent.
- Source-fetch success notices auto-dismiss at 4 seconds; partial, failed, blocked, cancelled-as-failure, and Worker-unavailable notices auto-dismiss at 8 seconds. Every notice has an accessible manual close button.
- Closing clears the same ActionFeedback record. The existing `seenTerminalJobs` `job_id:status` key remains populated, so polling/cache rerenders cannot recreate a dismissed terminal event. The timer keeps its original deadline across ordinary parent/query rerenders while using the latest close callback.

Focused RED→GREEN evidence:

```text
npm test -- --run src/app/App.test.tsx -t 'scopes live schedule'
RED: 1 failed / 37 skipped; the pending schedule label was absent.
GREEN: 1 passed / 37 skipped; schedule, subscribe, unsubscribe, and retry controls were independently pending and duplicate clicks were suppressed.

npm test -- --run src/app/App.test.tsx -t 'renders local accessible errors'
RED: 1 failed / 38 skipped; the schedule failure was absent from the Hero page.
GREEN (combined feedback slice): 2 passed / 37 skipped; all four action failures rendered in local alerts.

npm test -- --run src/features/admin-heroui/HeroActionNotice.test.tsx
RED: suite failed because the bounded/dismissible notice component did not exist.
GREEN: 6/6 passed, covering 4-second success, 8-second partial/failed/blocked, manual close, and a polling rerender that does not restart the timer.

npm test -- --run src/app/App.test.tsx -t 'keeps a manually dismissed source-fetch'
RED: 1 failed / 39 skipped; no close button existed.
GREEN (combined page/component slice): 2 files / 9 passed / 37 skipped, including same `job_id:status` cache rewrites that stay dismissed.
```

Final verification:

```text
npm test -- --run src/app/App.test.tsx src/features/admin-heroui/HeroActionNotice.test.tsx src/features/admin-heroui/HeroResponseSchemaDetails.test.tsx src/features/subscriptions/subscriptionModel.test.ts
4 files / 60 tests passed.

npm test
35 files / 182 tests passed.

npm run check:ui && npm run lint && npm run typecheck && npm run build
UI contract, TypeScript, and production build/preview exclusion passed; ESLint 0 errors with the existing 1 Fast Refresh warning.

npx playwright test e2e/live-admin.spec.ts
6/6 passed across desktop/tablet/mobile with the existing Axe assertions.

git diff --check && python3 -m json.tool project-defaults.yaml >/dev/null
Passed.

python3 scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 60.132s.
```

## Invalidation-order remediation — 2026-07-17

Schedule, subscribe, unsubscribe, and retry now retain their entity-scoped pending feedback until the corresponding TanStack Query invalidation promise settles. Each success callback awaits the existing invalidation set before publishing success, so controls cannot unlock against stale server-backed state. API calls, query keys, invalidation scope, permissions, and source-fetch lifecycle behavior are unchanged.

Focused RED→GREEN evidence:

```text
npm test -- --run src/app/App.test.tsx -t 'keeps successful live mutations pending'
RED: 1 failed / 40 skipped against the pre-fix callback order. All four API promises were resolved, the QueryClient.invalidateQueries spy had received the exact 19 expected calls, and every invalidation returned the same unresolved deferred promise; the active schedule control had already reverted to ordinary `关闭自动更新` instead of remaining `更新中 自动更新`.
GREEN: 1 passed / 40 skipped after awaiting invalidation before ActionFeedback success. Schedule, subscribe, unsubscribe, and retry all remained disabled/pending, duplicate submissions stayed suppressed, and refreshed controls appeared only after the deferred invalidation resolved.
```

Final verification:

```text
npm test -- --run src/app/App.test.tsx src/features/admin-heroui/HeroActionNotice.test.tsx src/features/admin-heroui/HeroResponseSchemaDetails.test.tsx src/features/subscriptions/subscriptionModel.test.ts
4 files / 61 tests passed.

npm test
35 files / 183 tests passed.

npm run check:ui && npm run lint && npm run typecheck && npm run build
UI contract, TypeScript, and production build/preview exclusion passed; ESLint 0 errors with the existing 1 Fast Refresh warning.

npx playwright test e2e/live-admin.spec.ts
6/6 passed across desktop/tablet/mobile with the existing Axe assertions.

git diff --check && python3 -m json.tool project-defaults.yaml >/dev/null
Passed.

python3 scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false.
```
