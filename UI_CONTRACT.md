<!-- init-pro:control schema=2 profile=backend project=inteliscope-infohub-light file=UI_CONTRACT.md -->
# Inteliscope UI Contract

## 1. Authority

This file is the sole source of truth for production UI technology, visual language, responsive behavior, and browser acceptance. `PLAN.md` records delivery state, `DECISION_LOG.md` records durable choices, and `tests/test_impact_map.json` selects verification; they must reference this contract rather than restate its visual rules. API fields, authorization, query ownership, and error envelopes remain governed by `API_CONTRACT.md` and existing application tests.

## 2. Production UI system

- Production uses React 19, HeroUI v3, Tailwind CSS v4, Lucide icons, and the self-hosted Noto Sans SC variable font.
- `frontend/src/design-system/**` owns the semantic theme, approved component exports, icon exports, and React Router bridge. Production application and feature code import UI components through this boundary and do not import `@heroui/*` directly.
- `AppBootstrap` mounts exactly one `DesignSystemProvider`, inside `BrowserRouter` and outside production routes. It remains inside the existing `QueryClientProvider`; Query Client, authentication, `ServiceApi`, caches, permissions, and query keys retain their existing lifetimes.
- MUI, MUI Icons, and Emotion are not production dependencies or source technologies. `frontend/src/ui/**`, the MUI prototype, and page-level legacy visual CSS Modules do not exist.
- The sole direct-HeroUI feature exception is the fixed-data development preview at `frontend/src/features/workbench-heroui/**`.

## 3. Visual language

- Production is dark-only in this phase, using a graphite canvas, elevated neutral surfaces, restrained purple accents, semantic separators, and visible accessible focus rings. Raw palette values belong only in design-system theme assets.
- Radius scale: 16 px panels, 14 px cards, 10 px controls, and 8 px small controls. Static surfaces use contrast and a thin separator rather than glow or heavy shadow.
- Purposeful transitions run for 120–220 ms. Reduced Motion makes nonessential transitions effectively immediate while preserving loading indicators' understandable state.
- Feature code does not define raw colors, shadows, radii, transition durations, or new page-level CSS visual systems. Native layout values may be used only where the static contract explicitly permits them.
- Loading, empty, degraded, failure, retry, and read-only states use the shared design-system vocabulary and accessible live regions. Global action feedback is framework-neutral; pages render feedback locally through HeroUI surfaces.

## 4. Routes and page ownership

| Route | Production experience |
|---|---|
| `/feed` | Hero workbench, all items |
| `/saved` | Hero workbench, saved collection |
| `/history` | Hero workbench, history collection |
| `/subscriptions` | Full-width Hero administration page; no Agent panel |
| `/agents` | Full-width Hero assistant-connection page; no Agent panel |
| `/settings` | Full-width Hero settings page; no Agent panel |
| `/login` | Standalone Hero login page |

- `/later` permanently replaces to `/saved`, preserves only a valid `item` query value, and removes legacy `mode`.
- Authenticated unknown routes resolve coherently to the production Feed; unauthenticated protected routes resolve through the standalone login flow.
- `mode` is not part of the production Feed experience. Legacy `mode` query parameters are removed while preserving `item`.

## 5. Workbench shell and responsiveness

- Navigation contains 信息流、收藏、历史、订阅、助手连接和设置. 稍后读 is absent.
- Header height is 52 px. The Web application does not imitate macOS traffic lights, window chrome, drag regions, or desktop-only operating-system controls.
- `/feed` uses the macOS system UI font stack on Apple platforms, with `PingFang SC` and the self-hosted Noto Sans SC variable font as Chinese and cross-platform fallbacks. This typography scope does not change other routes.
- During the Feed visual-confirmation phase, `/feed` keeps a quiet header containing only the page title and Agent toggle; search and manual refresh are absent. `/saved` and `/history` retain their current collection header controls.
- At 1360 px and above, the user-isolated sidebar may toggle between 72 px and 232 px; the preference key is `inteliscope.ui.sidebar.v1:<user_id>`, accepted values are `collapsed` and `expanded`, and absent or invalid values resolve to collapsed. Accounts never share the preference.
- From 1200–1359 px, navigation remains 72 px and the three-column workbench remains visible. The preference toggle is not presented.
- From 768–1199 px, navigation remains 72 px and Agent is an on-demand right overlay.
- At 767 px and below, content is single-column, navigation moves to the bottom, and Agent is a bottom sheet ending at the viewport bottom.
- At 1440×900, the workbench shows the complete navigation, Feed, and 360 px Agent columns and four to five complete collapsed cards. At 1024×768, Agent overlays without resizing or scrolling the Feed. At 390×844, bottom navigation and Agent sheet remain reachable without horizontal page overflow.
- Navigation, Feed, and Agent have independent scroll regions. Opening or closing a panel preserves route, selected/expanded story, and Feed scroll anchor. Escape closes overlays and restores focus to their trigger.

## 6. Feed, virtualization, and Agent handoff

- Feed has one mode, 全部, ordered older content above newer content. Initial entry anchors to the newest content at the bottom.
- `/feed` reads the canonical all-items response; `/saved` and `/history` reuse the same card, virtualization, filter, deep-link, and scroll behaviors.
- Long lists are virtualized with stable item IDs. A refresh captures the current rendered item ID and relative viewport offset synchronously at the request boundary. Measurement changes and source replacement retain that anchor; user scrolling cancels restoration ownership.
- New content auto-follows only when the viewport is within 96 px of the bottom. Otherwise the position remains stable and an explicit `N 条新内容` action appears.
- Filters include search, unread-first, source, channel, topic, and minimum score. Preferences remain user-isolated. Filtering and unread-first reordering preserve rendered-ID anchors.
- Cards show source, time, title, one summary, channel/topics, optional media, and bounded plain text on expansion. Expansion is inline and does not replace the list or move the viewport anchor.
- Direct actions are open original, save, and add/remove Agent context. Mark read/unread, copy summary, and dismiss live in the compact overflow menu. There is no read-later action.
- The `/feed` progress rail sits in the left card gutter without an enclosing surface, is approximately 300 px high, samples at most 28 positions, and is hidden below 640 px. Exactly one nearest tick is current; it lengthens and changes contrast while neighboring ticks partially extend using the standard motion token. Reduced Motion removes the transition. `/saved` and `/history` retain the compact rail. Every rail remains bounded, represents relative position, exposes keyboard-reachable jumps, and never becomes a full-height timeline.
- Agent context contains at most eight ordered item IDs and a question. Handoff text deterministically instructs OpenClaw to call `get_item`; the site does not run an Agent, chat, streaming session, local Gateway probe, or online-presence inference.
- Connection state copy is limited to configured, not configured, or check failed semantics. Credentials never imply online presence.
- Viewers may navigate, open, search, copy, and assemble a handoff, but may not mutate Feed item state. Other role behavior follows the existing API/permission contract.

## 7. Administration and authentication pages

- Subscriptions, assistant connections, and settings use full-width Hero pages within the shared navigation shell and do not mount the Feed Agent panel.
- Page information architecture, backend fields, role boundaries, write-only secret handling, job behavior, and Remote MCP safety remain unchanged by visual migration.
- Owner/Admin/member/viewer affordances must match existing authorization. Disabled or hidden controls are not substitutes for server enforcement.
- Login is a standalone dark Hero page and does not render the authenticated shell.
- Action failures are reversible where optimistic state is used, explain recovery in a live region, and never replay across users. Logout or account replacement clears user-scoped transient feedback and cache according to existing session rules.

## 8. Development preview isolation

- `/__preview/workbench-heroui` is the only visual preview route. It uses sanitized fixed data, requires no authentication, creates no Query Client or `ServiceApi`, and makes no `/api/*` request.
- The application entry dynamically imports it only behind `import.meta.env.DEV`. Production output excludes its route, fixtures, dedicated stylesheet markers, and preview copy.
- The deleted `/__preview/workbench` and `/__preview/workbench-live` routes, MUI comparison copy, and UI-experience switch do not return.

## 9. Enforcement and acceptance

Every production UI change must pass, in order:

1. Static UI contract checks and ESLint import restrictions.
2. TypeScript and Vitest.
3. Vite production build and artifact scan proving no MUI/Emotion modules, `Mui` class markers, deleted preview routes, or deleted comparison copy.
4. Playwright at 1440×900, 1024×768, and 390×844, including Axe with zero serious or critical findings.
5. Reduced Motion, focus restoration, independent scrolling, stable ID-plus-offset anchors, bounded virtualization, and no horizontal overflow checks.

The static contract rejects MUI/Emotion imports, production feature-level direct HeroUI imports, nested `DesignSystemProvider` mounts, raw business-page colors, page-level visual constants, and deleted preview technology. Snapshot or expectation changes require an intentional contract change; they are not an automatic response to a failing visual test.
