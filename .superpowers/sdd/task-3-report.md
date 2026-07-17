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
