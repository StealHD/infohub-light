# Task 2 Report: HeroUI 核心工作台、信息流与 Agent

## Status

Completed. A formal authenticated HeroUI workbench now exists behind the development-only real-API acceptance route `/__preview/workbench-live`, with Feed, saved, and history variants. The existing MUI application remains the production default, the fixed-data `/__preview/workbench-heroui` prototype is unchanged, and Task 3 pages were not migrated.

## RED evidence

Implementation followed focused RED→GREEN loops before production code:

- Feed preference tests expected the v2 storage shape and v1 unread-only migration; RED returned the old `{mode,...}` preference object. GREEN: 3/3.
- Stable workbench sorting expected valid timestamps old-to-new with invalid timestamps retaining API order; RED returned API order. GREEN: 7/7 feed-model tests.
- Workbench and Agent-context tests initially failed module resolution because the new model modules did not exist. GREEN: 8/8.
- Virtual feed tests initially failed module resolution because the component did not exist. Subsequent runtime coverage caught direct icon star exports resolving `undefined`; the formal design-system runtime surface was corrected. GREEN: 5/5.
- Authenticated live-route coverage initially rendered the legacy MUI fallback. The final route, deep-link insertion/404 degradation, `/later` compatibility, and optimistic rollback suite is GREEN: 8/8.
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
- Added a development-only authenticated real-API route family for acceptance. Production routing and the fixed-data preview remain isolated; legacy `/later` remains its own page, and legacy `mode` is removed with replace while preserving `item`.

## Files changed

- `frontend/package.json`, `frontend/package-lock.json`
- `frontend/src/app/App.tsx`, `App.test.tsx`, `sessionCache.ts`, `sessionCache.test.ts`
- `frontend/src/design-system/index.ts`, `runtimeExports.test.ts`
- `frontend/src/features/feed/FeedPage.tsx`, `feedModel.ts`, `feedModel.test.ts`, `feedPreference.ts`, `feedPreference.test.ts`, `useOptimisticItemState.ts`
- `frontend/src/features/workbench-live/**`
- `frontend/e2e/live-workbench.spec.ts`
- `.superpowers/sdd/task-2-report.md`
- `WORKLOG.md`

## Historical initial verification (superseded)

Initial implementation frontend chain:

```text
npm run check:ui && npm run lint && npm run typecheck && npm test && npm run build
UI contract: passed
ESLint: 0 errors, 1 pre-existing Fast Refresh warning
TypeScript: passed
Vitest: 33 files / 138 tests passed
Vite production build and preview exclusion: passed
```

Initial responsive browser acceptance:

```text
npx playwright test e2e/live-workbench.spec.ts
3 passed (desktop, tablet, mobile; Axe serious/critical zero)
```

Initial repository gate and hygiene:

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

## Review-fix appendix (2026-07-17)

### RED commands and results

```text
npm test -- src/app/App.test.tsx
RED: 2/9 failed — `/later` was redirected and changing `?item=` remounted the authenticated tree.

npm test -- src/features/feed/feedModel.test.ts
RED: 1/8 failed — v2 presentation source/channel/topics/score did not control filtering.

npm test -- src/features/workbench-live/workbenchModel.test.ts
RED: 1/5 failed — an existing snapshot row discarded fetched v2 detail instead of merging it.

npm test -- src/app/App.test.tsx
RED after adding detail/filter regressions: 2/12 failed — selected snapshot detail was not fetched and a filtered dismissed deep link disappeared.

npm test -- src/features/workbench-live/VirtualFeed.test.tsx
RED: 3/7 failed — filter reveal was counted as new, fixed-length ID replacement was missed, and manual bottom return did not clear the badge.

npm test -- src/app/App.test.tsx -t 'neutral Agent|real modal dialog'
RED: 2/2 failed — delegation loading claimed `未配置` and the narrow surface was not a modal dialog.

npm run e2e -- e2e/live-workbench.spec.ts
RED iterations: 3/3 failed on exact inline scroll anchoring; the next run exposed mobile overlay scroll drift plus two missing rolling-window badges; the following run exposed 2/3 Axe portal foreground failures.

npm run e2e -- e2e/live-workbench.spec.ts --project=tablet
RED: 1/1 failed — portal-visible `body` foreground was rgb(27, 28, 25), not the leased design-system foreground oklch(0.94 0.005 286).
```

### GREEN commands and results

```text
npm test -- src/app/App.test.tsx src/features/feed/feedModel.test.ts src/features/workbench-live/workbenchModel.test.ts src/features/workbench-live/VirtualFeed.test.tsx
GREEN: 4 files / 34 tests passed.

npm run check:ui && npm run lint && npm run typecheck && npm test && npm run build
GREEN: UI contract passed; ESLint 0 errors with the pre-existing ActionFeedback Fast Refresh warning; TypeScript passed; Vitest 33 files / 148 tests passed; Vite build and preview exclusion passed.

npm run e2e -- e2e/design-system-contract.spec.ts --project=desktop -g 'real Modal and Tooltip portals'
GREEN: 1/1 passed.

npm run e2e -- e2e/live-workbench.spec.ts
GREEN: 3/3 passed across desktop/tablet/mobile, including controlled HeroUI Drawer semantics, exact scroll anchoring, fixed-window ID diff, focus/inert/Escape behavior, no overflow, and Axe serious/critical zero.

git diff --check && python3 -m json.tool project-defaults.yaml >/dev/null
GREEN: both hygiene checks passed.

python3 scripts/test_gate.py run --mode full
GREEN (accepted first re-review gate at that time): 22/22 commands passed; mapping_miss=false; 68.966s.
```

One immediately preceding full-gate attempt reached the frontend Vitest phase under host contention and timed out eight unrelated 5-second UI tests (29 files/140 tests passed). A standalone retry showed the same timeout pattern; no product assertion failed. The required unmodified full gate was rerun after contention subsided and produced the accepted 22/22 result above.

### Review-fix implementation notes

- Restored the production legacy `/later` page and keyed the route error boundary by pathname only, so inline search-parameter expansion preserves the authenticated shell and scroll state.
- Always fetches selected detail, structurally merges v2 presentation data into snapshot rows, keeps non-404 failures usable, and pins a successful selected target through persisted filters without disturbing the matching list order.
- Uses canonical v2 presentation fields for filters and source options, with legacy fallback only when canonical values are absent.
- Replaced count deltas with source-ID set diffs, retained the visible anchor during inline detail/layout settlement, and clears the new-content badge on manual return to the bottom zone.
- Replaced the narrow custom sliding surface with a controlled HeroUI Drawer/Backdrop/Content/Dialog; delegation status remains neutral `检查中` until the request resolves.
- Fixed portal foreground inheritance once in the design-system document-root contract; no business-layer theme-variable copy or raw backdrop color was introduced.

## Second review-fix appendix (2026-07-17)

### RED commands and results

```text
npm test -- src/app/App.test.tsx -t 'delegation loading|real modal dialog|filter-pinned|detail 404|proven-stale'
RED: 4/5 selected tests failed — loading exposed visible status text, filter pinning appended out of order, an early detail 404 cleared a still-valid snapshot, and a proven-stale initial target did not take the normal bottom-position path. The existing real modal test passed.

npm run e2e -- e2e/live-workbench.spec.ts --project=desktop
RED: desktop close retained one empty `OpenClaw 上下文` complementary panel instead of unmounting it.

npm run e2e -- e2e/live-workbench.spec.ts --project=tablet --grep 'preserves responsive'
RED: rolling-window replacement preserved the card ID but shifted its relative viewport offset by 186 px, exactly one collapsed row.
```

### GREEN commands and results

```text
npm test -- src/app/App.test.tsx -t 'delegation loading|real modal dialog|filter-pinned|detail 404|proven-stale'
GREEN: 5/5 selected tests passed.

npm test -- src/app/App.test.tsx src/features/workbench-live/VirtualFeed.test.tsx
GREEN: 2 files / 23 tests passed.

npm run check:ui && npm run lint && npm run typecheck && npm run build
GREEN: UI contract passed; ESLint 0 errors with the pre-existing ActionFeedback Fast Refresh warning; TypeScript passed; Vite build and preview exclusion passed.

npm test
GREEN: 33 files / 150 tests passed.

npm run e2e -- e2e/live-workbench.spec.ts
GREEN: 6/6 passed across desktop/tablet/mobile, covering strict top-card ID/relative-offset preservation (2 px maximum), desktop Agent two/three-column close/reopen, actual stale-deep-link near-bottom placement, no overflow, and Axe serious/critical zero.
```

### Second review-fix implementation notes

- A detail 404 can clear `item` only after the active Feed/saved/history query succeeds and proves the selected ID absent; a source snapshot that arrives later and contains the ID remains selected and expanded.
- A proven-stale initial target is suppressed through navigation state so the existing bottom-first Feed path runs; Playwright verifies the real viewport lands inside the Feed's 96 px bottom zone.
- Persisted filters pin a selected detail with `mergedItems.filter(matches || selected)`, preserving the stable oldest-to-newest merged order.
- Rolling fixed-window updates retain the top-visible item ID and relative offset through stable DOM item IDs and public DOM geometry. The fallback uses only public `scrollToIndex`; no TanStack private cache or state is read.
- Delegation loading exposes one skeleton-only `aria-busy` status. Terminal text appears once.
- Closing the desktop Agent unmounts the 360 px aside and switches the shell from three columns to two without losing the Feed position; reopening restores the third column.

## Third review-fix appendix (2026-07-17)

### RED commands and results

```text
npm test -- src/app/App.test.tsx -t 'cached-missing selection'
RED: 1/1 failed — a cached-success Feed with an active background refetch removed `?item=live-1` immediately after detail 404, before the refetch returned the target.

npm test -- src/app/App.test.tsx -t 'unread-first ordering'
RED: 1/1 failed — pinning returned raw chronology `[较旧已读条目, selected, 较新未读条目]` instead of preserving unread-first order.

npm run e2e -- e2e/live-workbench.spec.ts --project=desktop --grep 'filtered unread-first'
RED: 1/1 failed — after a filtered/unread-first 80-row rolling replacement moved the anchor beyond overscan, fallback jumped from `实时条目 147` to raw-source-index row `实时条目 277`.
```

### GREEN commands and results

```text
npm test -- src/app/App.test.tsx -t 'cached-missing selection|detail 404|proven-stale'
GREEN: 3/3 selected tests passed.

npm test -- src/app/App.test.tsx -t 'filter-pinned|unread-first ordering|persisted filters'
GREEN: 3/3 selected tests passed.

npm run e2e -- e2e/live-workbench.spec.ts --project=desktop --grep 'filtered unread-first'
GREEN: 1/1 passed with the same anchor ID and a strict 2 px maximum relative-offset delta.

npm run check:ui && npm run lint && npm run typecheck && npm test && npm run build
GREEN: UI contract passed; ESLint 0 errors with the pre-existing ActionFeedback Fast Refresh warning; TypeScript passed; Vitest 33 files / 152 tests passed; Vite build and preview exclusion passed.

npm run e2e -- e2e/live-workbench.spec.ts
GREEN: 9/9 passed across desktop/tablet/mobile, including the filtered unread-first fallback regression and Axe serious/critical zero.
```

### Third review-fix implementation notes

- A 404 source proof now requires the active query to be both successful and not fetching; cached success cannot clear a target while its background refetch is unresolved.
- The pin candidates still use `mergedItems.filter(matches || selected)`, then reapply only `filterFeedItems`' stable unread-first partition so exclusionary filters remain bypassed without discarding display order.
- An unmounted virtual anchor falls back through `props.cards.findIndex`, the exact count/order consumed by TanStack Virtual, rather than raw source IDs.

## Final verification

```text
npm run check:ui && npm run lint && npm run typecheck && npm test && npm run build
UI contract: passed
ESLint: 0 errors, 1 pre-existing Fast Refresh warning
TypeScript: passed
Vitest: 33 files / 152 tests passed
Vite production build and preview exclusion: passed

npm run e2e -- e2e/live-workbench.spec.ts
9/9 passed across desktop, tablet, and mobile; Axe serious/critical zero

npm run e2e -- e2e/design-system-contract.spec.ts --project=desktop -g 'real Modal and Tooltip portals'
1/1 passed; portal theme acquisition/release contract preserved

git diff --check
python3 -m json.tool project-defaults.yaml
Both hygiene checks passed

python3 scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 53.140s
```
