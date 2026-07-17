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
