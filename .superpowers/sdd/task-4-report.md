# Task 4 Report: HeroUI production cutover

## Status

Completed. HeroUI is the sole production UI system. Feed, saved, history, subscriptions, Agent connections, settings, and login use the Hero implementation; the fixed-data Hero preview remains development-only. MUI, MUI Icons, Emotion, the legacy UI layer, MUI preview, and real-data preview routes are removed.

No backend, API, database, permission, query key, Remote MCP, history, VPS, Worker, scheduler, or deployment state changed.

## RED → GREEN evidence

- The initial cutover contract failed 7 focused assertions: MUI/Emotion dependencies remained, preview routes remained, `AppBootstrap` did not own the Hero provider, and production Feed/admin/later routes still resolved to legacy behavior. Production routing and provider ownership made 44/45 focused tests green; dependency removal closed the last assertion.
- The sidebar preference test first failed because no production toggle existed. The Hero shell now reads and writes `inteliscope.ui.sidebar.v1:<user_id>`, isolates accounts, toggles 72/232 px only at ≥1360 px, and remains 72 px from 1200–1359 px; 2/2 focused tests passed.
- The static UI checker first failed six intentional categories: direct business `@heroui/*`, MUI, Emotion, raw visual constants, deleted preview routes, and deleted comparison copy. The checker and 8 contract cases now pass, including a nested-provider rejection.
- `AppBootstrap` initially threw because `DesignSystemProvider` was outside `BrowserRouter`. A focused bootstrap test reproduced the Router dependency; provider order is now Query Client → BrowserRouter → DesignSystemProvider → routes.
- Production E2E exposed late virtual measurements and refresh-anchor ownership. Instrumentation proved failures captured the wrong request-boundary geometry rather than losing IDs: filtered item 143 existed at old/new indexes 47/21, while item 147 existed at 48/22. The shell now synchronously signals refresh before the request, the virtual feed captures ID plus relative offset at that boundary, and mutation/scroll corrections retain it.
- Explicit navigation regression tests first failed after refresh: the first rail jump stayed at scrollTop 3558 instead of moving below 1779, and “查看新内容” left 15845 px below the viewport instead of ≤96 px. Rail jumps, new-content navigation, auto-follow, and initial/deep-link navigation now release restoration ownership. The mobile slice passed 3/3 and the filtered anchor stress run passed 20/20 with 5 workers.

## Implementation

- Made `AppBootstrap` the only production UI-provider owner while preserving Query Client, authentication, `ServiceApi`, cache, and action-generation lifetimes.
- Mapped `/feed`, `/saved`, and `/history` to the Hero workbench; mapped `/subscriptions`, `/agents`, and `/settings` to full-width Hero administration pages without Agent; mapped `/login` to standalone Hero login.
- Replaced `/later` with `/saved`, preserving `item` and dropping `mode`. Removed the legacy UI-experience branch and deleted production/development routes for MUI and live-data previews.
- Preserved `/__preview/workbench-heroui` as a fixed-data, no-auth, no-API, DEV-only dynamic import and strengthened the production artifact exclusion scan.
- Removed `@mui/material`, `@mui/icons-material`, `@emotion/react`, and `@emotion/styled` from package manifests and lockfile; deleted `frontend/src/ui/**`, MUI pages, MUI CSS Modules, MUI prototype, obsolete visual snapshots, and superseded tests.
- Kept pure models, state/cache logic, permission behavior, query keys, optimistic updates, job orchestration, and API clients. Replaced global MUI Snackbar rendering with framework-neutral action feedback consumed by Hero pages.
- Tightened card density to meet the 1440×900 four-to-five-complete-card contract and retained bounded virtualization, deep links, filtered/unread-first anchors, bottom-follow, rail navigation, and Agent handoff.
- Rewrote `UI_CONTRACT.md` as the visual single source of truth. `PLAN.md` and D028 record status/decision and refer to it. Test-impact rules now use current Hero bootstrap, design-system, workbench, and checker paths; deleted MUI paths were removed from deterministic mapping tests.

## Final verification

```text
npm run check:ui
PASS

npm run lint
PASS, 0 errors / 0 warnings

npm run typecheck
PASS

npm test -- --reporter=dot
28 files / 154 tests passed

npm run build
PASS; production artifact scan passed
(Vite retains the informational >500 kB chunk warning.)

npm run e2e
36/36 passed across 1440×900, 1024×768, and 390×844
Includes production workbench/admin/login, fixed preview, design-system portals,
Reduced Motion, focus, overflow, bounded rendering, and Axe serious/critical zero.

npx playwright test e2e/production-workbench.spec.ts --project=mobile \
  --grep "filtered unread-first" --repeat-each=20 --workers=5
20/20 passed with strict same-ID and relative-offset ≤2 px assertions

.venv/bin/python -m pytest -q tests/test_api_service.py tests/test_react_service_ui.py
69 passed

.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 49.076s

docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.light.yml config --quiet
docker compose -f docker-compose.test-gate.yml config --quiet
PASS (also covered by full gate)

git diff --check
PASS
```

## Self-review

- Confirmed package and production source scans contain no MUI or Emotion dependency/import.
- Confirmed production feature code has no direct HeroUI import and no nested `DesignSystemProvider`; the fixed preview is the only feature exception.
- Confirmed production output excludes both deleted previews and the retained fixed Hero preview markers.
- Confirmed Owner/Admin/member/viewer behavior remains covered where fixtures support it; server authorization remains unchanged.
- Confirmed sidebar and Feed preferences remain user-isolated and are not cleared or shared across accounts.
- Confirmed refresh restoration yields ownership to explicit user/programmatic navigation and therefore cannot snap rail/new-content navigation back to an old anchor.
- Confirmed no temporary debug attributes, console logging, test artifacts, or experimental source-change cleanup code remains.

## Remaining note

Vite reports one existing informational chunk-size warning for the HeroUI application chunk. It does not fail the artifact or full gate and is not a correctness or cutover blocker.

## Review follow-up: rendered anchors, ownership, gates, and route acceptance

All four Important review groups are closed.

- Rendered-order transitions now have their own `cardsSignature` boundary. It is the sole layout-restoration owner; raw `sourceSignature` remains limited to added-ID/new-content accounting and never creates a second observer. Live unread-first and source narrowing preserve the surviving rendered card ID and relative offset within 2 px. A single bounded stabilization loop allows at most 120 virtualizer measurement frames and requires six stable frames; later style mutations reuse the same observer. User/programmatic release invalidates the anchor identity immediately, so pending restoration frames become no-ops.
- `releaseNavigationOwnership` centrally clears the requested refresh anchor, active restoration anchor, inline numeric anchor, inline timer, and inline RAF. Refresh capture releases old ownership before recording the new request-boundary anchor. Initial/deep-link positioning, bottom auto-follow, progress-rail jumps, new-content jumps, inline expansion replacement, and pointer/wheel/touch/keyboard cancellation all use the central release path. Focused browser tests prove that a jump during an in-flight refresh does not snap back when data arrives and that a rail jump immediately after expansion is not reclaimed one second later.
- The UI source gate now scans business `.css` as well as TypeScript, rejects both default and side-effect CSS Module imports, and rejects raw business colors/shadows/radii/duration declarations outside the design-system/fixed-preview boundary. The production artifact gate now rejects the stable `inteliscope-fixed-preview-fixture-v1` module marker even if route/class/copy markers are changed, while MUI detection is narrowed to actual `Mui…-…` class markers and `@mui/` modules instead of an unrelated bare substring. Bypass regression tests cover each rule.
- `/saved`, `/history`, and legacy `/later?...item=...` now have explicit unit and production-browser acceptance. The tests prove saved/history use their own API collections, `/later` preserves `item`, removes obsolete `mode`, redirects to `/saved`, and renders the selected saved item.

Follow-up verification:

```text
npm run check:ui
PASS

npm run lint
PASS, 0 errors / 0 warnings

npm run typecheck
PASS

npm test -- --reporter=dot
28 files / 160 tests passed

npm run build
PASS; production artifact scan passed
(Vite retains the informational >500 kB chunk warning.)

npm run e2e
48/48 passed across desktop, tablet, and mobile

npx playwright test e2e/production-workbench.spec.ts --project=mobile \
  --grep "filtered unread-first" --repeat-each=20 --workers=5
20/20 passed

.venv/bin/python -m pytest -q tests/test_api_service.py tests/test_react_service_ui.py
69 passed

.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 65.117s

git diff --check
PASS
```

## Second review follow-up: release invalidation and executable negative gates

The final ownership and gate-bypass review is closed.

- `releaseNavigationOwnership` now invalidates the pre-release viewport fallback in addition to the requested refresh, active restoration, inline anchor, timers, RAFs, and pending navigation. Refresh capture reads the current request-boundary geometry first, then releases older ownership, then records only that newly captured request anchor.
- A rail action during an in-flight refresh owns the result even when the response is released from a microtask immediately after `element.click()`. The regression does not wait for a scroll event or landing before resolving the response. A pending navigation target replays against the committed card set, while the first-item boundary remains fixed during late virtual measurements and yields immediately to pointer, wheel, touch, or keyboard input.
- Source checks now reject dynamic CSS Module imports and raw `oklch()`, `oklab()`, `lab()`, `lch()`, and `color(display-p3 ...)` colors. Tests invoke the real checker process rather than inspecting checker source.
- Artifact checks accept an explicit build root and reject the real `.Mui-disabled` global-state class. The fixed preview story array carries a non-enumerable runtime marker, and an actual Vite production bundle that imports `workbenchPreviewStories` is rejected, so the marker cannot pass merely because an unrelated export was tree-shaken.

Second follow-up verification:

```text
npx vitest run src/design-system/uiContract.test.ts src/design-system/cutoverContract.test.ts
2 files / 21 tests passed

npx playwright test e2e/production-workbench.spec.ts \
  --grep "jump during an in-flight refresh" --workers=3
3/3 passed across desktop, tablet, and mobile

npm run check:ui
PASS

npm run lint
PASS, 0 errors / 0 warnings

npm run typecheck
PASS

npm test
28 files / 166 tests passed

npm run build
PASS; production artifact scan passed
(Vite retains the informational >500 kB chunk warning.)

npm run e2e
48/48 passed across desktop, tablet, and mobile

.venv/bin/python -m pytest -q tests/test_api_service.py tests/test_react_service_ui.py
69 passed

.venv/bin/python scripts/test_gate.py run --mode full
22/22 commands passed; mapping_miss=false; 50.462s

git diff --check
PASS
```

## Final review follow-up: clamped navigation ownership

- A refresh can replace 200 cards with 50 while a progress-rail action still refers to a former high index. The navigation target is now clamped once against the committed list and the clamped index is written back to `pendingNavigation`; arriving at the real final item can therefore clear ownership instead of retaining an unreachable pre-refresh index.
- Added a pure RED→GREEN regression for the navigation state transition and a production-browser scenario: request a refresh, jump to the former 182nd item in the same event loop, commit a 50-item response, then dismiss a top card. The later card update remains at the intended viewport rather than reclaiming the obsolete target.

Final follow-up verification:

```text
npm run check:ui / lint / typecheck
PASS

npm test -- --reporter=dot
29 files / 167 tests passed

npm run build
PASS; production artifact scan passed
(Vite retains the informational >500 kB chunk warning.)

npm run e2e
51 scheduled across desktop, tablet, and mobile; passed with the new desktop-only rail regression

.venv/bin/python -m pytest -q tests/test_api_service.py tests/test_react_service_ui.py
69 passed

.venv/bin/python scripts/test_gate.py run --mode full
PASS

docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.light.yml config --quiet
docker compose -f docker-compose.test-gate.yml config --quiet
PASS

git diff --check
PASS
```

## Fourth review follow-up: release before navigation frame

- The cards-commit navigation replay now stores its RAF handle. `releaseNavigationOwnership` cancels that handle, and the callback also verifies that it still owns the same pending-navigation object before writing state or scrolling. A wheel, pointer, touch, or keyboard release between React commit and the next animation frame therefore wins deterministically.
- The production regression pauses the browser RAF queue after a refresh commits a 50-item replacement, dispatches a real wheel release, then flushes the queued callbacks. It was RED before the fix (`scrollTop` was reclaimed to 7231px) and is GREEN after it. The shrink regression now causes a later list change through the Shell search field rather than a card action, so it no longer receives an implicit Feed pointer-release pass.

Fourth follow-up verification:

```text
npx playwright test e2e/production-workbench.spec.ts --project=desktop \
  --grep "clamped rail jump releases ownership|wheel release after cards commit"
2/2 passed

npm run check:ui / lint / typecheck
PASS

npm test -- --reporter=dot
29 files / 167 tests passed

npm run build
PASS; production artifact scan passed
(Vite retains the informational >500 kB chunk warning.)

npm run e2e
54 scheduled across desktop, tablet, and mobile; 50 passed, 4 intentional desktop-only skips

.venv/bin/python -m pytest -q tests/test_api_service.py tests/test_react_service_ui.py
69 passed

.venv/bin/python scripts/test_gate.py run --mode full
PASS

docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.light.yml config --quiet
docker compose -f docker-compose.test-gate.yml config --quiet
PASS

git diff --check
PASS
```

## Fifth review follow-up: committed-card timing assertion

- The shrinking-list external-search assertion no longer polls `scrollTop` immediately after filling the search field: that first poll could observe the pre-commit layout before the pending-navigation frame ran. It now waits for the computed `11 条` filtered-card count, performs stable multi-frame viewport sampling, and only then asserts the Feed remains at the intended top position.
- The dedicated wheel/RAF gate remains separate and continues to prove cancellation in the commit-to-next-frame window.

Fifth follow-up verification:

```text
npx playwright test e2e/production-workbench.spec.ts --project=desktop \
  --grep "clamped rail jump releases ownership|wheel release after cards commit"
2/2 passed

npm run check:ui / lint / typecheck
PASS

npm test -- --reporter=dot
29 files / 167 tests passed

npm run build
PASS; production artifact scan passed
(Vite retains the informational >500 kB chunk warning.)

npm run e2e
54 scheduled across desktop, tablet, and mobile; 50 passed, 4 intentional desktop-only skips

.venv/bin/python scripts/test_gate.py run --mode full
PASS

docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.light.yml config --quiet
docker compose -f docker-compose.test-gate.yml config --quiet
PASS

git diff --check
PASS
```
# 2026-07-18 终审修复补充

- 关闭 docs-only 优先级遮蔽显式 UI 契约映射的问题，并由 Python 回归锁定。
- executable checker 与 ESLint 现在都拒绝 `import(\`@heroui/*\`)`、MUI/Emotion 与 CSS Module 的静态模板导入。
- 移动导航保留六个目的地；筛选改用 HeroUI Popover/Select/NumberField，来源选项支持 required/help/error。
- `feedItem` 仅用于不在 source list 中的深链，既有卡片展开不再发送重复详情请求。
- 新增 release Playwright：`build + vite preview --port 4174`、`reuseExistingServer=false`，并排除 DEV-only preview 与 portal fixture；完整生产三视口 29 通过、4 个既定 desktop-only skip。
