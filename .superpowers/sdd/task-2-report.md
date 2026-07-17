# Task 2 Report: HeroUI 核心工作台、信息流与 Agent

## Status

Completed. A formal authenticated HeroUI workbench now exists behind the development-only real-API acceptance route `/__preview/workbench-live`, with Feed, saved, and history variants. The existing MUI application remains the production default, the fixed-data `/__preview/workbench-heroui` prototype is unchanged, and Task 3 pages were not migrated.

## RED evidence

Implementation followed focused RED→GREEN loops before production code:

- Feed preference tests expected the v2 storage shape and v1 unread-only migration; RED returned the old `{mode,...}` preference object. GREEN: 3/3.
- Stable workbench sorting expected valid timestamps old-to-new with invalid timestamps retaining API order; RED returned API order. GREEN: 7/7 feed-model tests.
- Workbench and Agent-context tests initially failed module resolution because the new model modules did not exist. GREEN: 8/8.
- Virtual feed tests initially failed module resolution because the component did not exist. Subsequent runtime coverage caught direct icon star exports resolving `undefined`; the formal design-system runtime surface was corrected. GREEN: 5/5.
- Authenticated live-route coverage initially rendered the legacy MUI fallback. The final route, deep-link insertion/404 degradation, `/later` redirect, and optimistic rollback suite is GREEN: 8/8.
- Logout/session tests expected the user-scoped Agent draft to be cleared; RED retained the session entry. GREEN after integrating draft cleanup into the existing user-cache boundary.

## Implementation

- Added the exact `@tanstack/react-virtual@3.14.6` dependency, dynamic card measurement, `overscan=5`, bottom-first/deep-link positioning, bounded DOM rendering, source-aware new-content following, and a 112 px rail with at most 12 sampled ticks.
- Added a formal responsive shell with the required 1360/1200/768/mobile column behavior, independent navigation/content/Agent scrolling, the exact six navigation destinations, mobile bottom navigation, tablet drawer, and mobile bottom sheet.
- Added shared `WorkbenchCardModel` projection for Feed/saved/history. Feed reads only `snapshot.items`; ordering is stable by effective published time with invalid dates after valid dates in API-relative order.
- Added in-place `?item=<id>` expansion without implicit read mutation. Missing deep links use the existing `feedItem` query, merge chronologically, and degrade a 404 to a closable notice while keeping the list usable.
- Added the required direct actions and overflow actions, with Viewer server mutations disabled while view/copy remain available.
- Extracted the existing ActionGeneration-backed optimistic item-state mutation into `useOptimisticItemState` so legacy and HeroUI surfaces share cancellation, cache patching, generation guard, rollback, and success behavior.
- Added compact search and preference controls for unread/source/channel/topic/minimum score. V2 preference storage contains only those fields and migrates only `unreadFirst` from v1.
- Reused the existing feed refresh preflight/polling path. Terminal notices are closable and use 4-second success or 8-second failure/partial/blocked lifetimes.
- Added user-scoped `AgentContextDraftV1` session storage, ordered unique IDs capped at eight, a 1200-character question limit, delegation configured/unconfigured/check-failed status, and deterministic OpenClaw handoff text with numbered `get_item item_id` calls. Logout/user switching clears the draft.
- Added a development-only authenticated real-API route family for acceptance. Production routing and the fixed-data preview remain isolated; `/later` redirects to `/saved` while preserving query parameters, and legacy `mode` is removed with replace while preserving `item`.

## Files changed

- `frontend/package.json`, `frontend/package-lock.json`
- `frontend/src/app/App.tsx`, `App.test.tsx`, `sessionCache.ts`, `sessionCache.test.ts`
- `frontend/src/design-system/index.ts`, `runtimeExports.test.ts`
- `frontend/src/features/feed/FeedPage.tsx`, `feedModel.ts`, `feedModel.test.ts`, `feedPreference.ts`, `feedPreference.test.ts`, `useOptimisticItemState.ts`
- `frontend/src/features/workbench-live/**`
- `frontend/e2e/live-workbench.spec.ts`
- `.superpowers/sdd/task-2-report.md`
- `WORKLOG.md`

## Final verification

Fresh final frontend chain:

```text
npm run check:ui && npm run lint && npm run typecheck && npm test && npm run build
UI contract: passed
ESLint: 0 errors, 1 pre-existing Fast Refresh warning
TypeScript: passed
Vitest: 33 files / 138 tests passed
Vite production build and preview exclusion: passed
```

Fresh responsive browser acceptance:

```text
npx playwright test e2e/live-workbench.spec.ts
3 passed (desktop, tablet, mobile; Axe serious/critical zero)
```

Fresh repository gate and hygiene:

```text
git diff --check
python3 -m json.tool project-defaults.yaml
python3 scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 56.39s
```

## Self-review

- Confirmed formal workbench business code imports HeroUI only through `frontend/src/design-system` and does not introduce direct MUI/HeroUI imports.
- Confirmed no backend API, database, query-key, Remote MCP, authentication, or authorization contract changed.
- Confirmed the MUI production tree remains the default and neither MUI nor Emotion was removed.
- Confirmed Feed uses only `snapshot.items`; saved/history use their existing API results and the same card model/component.
- Confirmed Viewer restrictions and ActionGeneration rollback semantics are preserved.
- Confirmed Agent state is session-only and user-scoped, contains no online/chat/streaming behavior, and is cleared at the existing cache/logout boundary.
- Confirmed expanding cards never marks them read and that filter broadening cannot be misreported as new API content.
- Confirmed 200 items render no more than 40 cards, progress ticks are capped at 12, all tested layouts have no horizontal overflow, overlay Escape returns focus, and Axe reports no serious/critical violations.
- Confirmed `git diff --check` and the full repository gate pass.

## Concerns

- ESLint retains the pre-existing Fast Refresh warning in `frontend/src/app/ActionFeedback.tsx`; this task did not create it.
- Vite retains the existing JavaScript chunk-size warning above 500 kB; the build succeeds and production code splitting is outside Task 2.
- The live workbench is deliberately development-only until Task 4 performs the coordinated production switch; this is an acceptance surface, not a production rollout flag.
