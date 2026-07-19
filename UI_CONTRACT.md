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
- The entire production application uses one system UI font stack: `-apple-system`, `BlinkMacSystemFont`, SF Pro where available, `PingFang SC` for Chinese on Apple platforms, then the self-hosted `Noto Sans SC Variable` and system sans-serif fallbacks. Routes and feature components may not define a competing font stack.
- Typography has exactly ten semantic roles. Their implementation lives in `frontend/src/design-system/theme.css`; business code selects a role and never recreates its size, weight, line height, or letter spacing.

| Role | Size / line | Weight | Intended use |
|---|---:|---:|---|
| `type-display` | 24 / 32 px | 600 | standalone authentication or dedicated display titles |
| `type-section-title` | 18 / 26 px | 600 | major page sections |
| `type-page-title` | 16 / 24 px | 600 | workbench headers, dialogs, card section headers |
| `type-card-title` | 16 / 23 px | 600 | Feed, saved, and history card titles |
| `type-body` | 14 / 22 px | 400 | summaries, descriptions, notices, ordinary content |
| `type-control` | 13 / 20 px | 500 | buttons, toolbar values, navigation and menu actions |
| `type-meta` | 12 / 18 px | 400 | source, time, counts and technical metadata |
| `type-label` | 11 / 16 px | 500 | navigation group labels and compact composer labels |
| `type-micro` | 10 / 14 px | 500 | chips and mobile navigation captions |
| `type-prose` | 14 / 26 px | 400 | expanded captured body text |

- Elements in one functional group use the same semantic role. In particular, the Feed view bar count, order control and filter control all use `type-control`; source and time share `type-meta`; channel/topic chips share `type-micro`.
- Production business code may not use Tailwind font-size, font-weight, line-height, or letter-spacing utilities (`text-xs`, `text-[…]`, `font-*`, `leading-*`, `tracking-*`). The executable UI contract rejects them. Alignment and semantic color utilities such as `text-left` and `text-muted` remain allowed.
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
| `/subscriptions` | Quiet Studio adaptive administration page; no Agent panel |
| `/agents` | Quiet Studio adaptive assistant-connection page; no Agent panel |
| `/settings` | Quiet Studio adaptive settings page; no Agent panel |
| `/login` | Standalone Quiet Studio login page |

- `/later` permanently replaces to `/saved`, preserves only a valid `item` query value, and removes legacy `mode`.
- Authenticated unknown routes resolve coherently to the production Feed; unauthenticated protected routes resolve through the standalone login flow.
- `mode` is not part of the production Feed experience. Legacy `mode` query parameters are removed while preserving `item`.

## 5. Workbench shell and responsiveness

- Expanded navigation is organized as 浏览（信息流、收藏、历史）、常用视图（未读、AI、朋友动态、产品机会）and 管理（订阅、助手连接、设置）. 稍后读 is absent. Quick views only transform the existing user-isolated Feed preference and introduce no API or URL state.
- The collapsed brand uses the Inteliscope scope mark rather than a text initial. The bottom account avatar/row is the only account trigger; its Popover contains identity, Chinese role, settings, and an explicit logout action. A standalone logout icon is not rendered.
- Header height is 52 px. The Web application does not imitate macOS traffic lights, window chrome, drag regions, or desktop-only operating-system controls.
- `/feed`, collection routes, administration pages and authentication all inherit the application font stack and semantic typography scale from the design system. A route must not switch typography independently.
- Every production route uses the shared Quiet Studio page patterns. A route has exactly one page title in `PageHeader`; content-route headers contain only that title and the Agent toggle, while count, search, order, filter, and refresh actions live in the aligned `ViewBar` below.
- `PageFrame` owns the three approved content widths: reading pages use approximately 820 px, administration pages approximately 1180 px, and authentication approximately 420 px. Business pages select `reading`, `admin`, or `auth` and may not recreate those widths.
- At 1360 px and above, the user-isolated sidebar may toggle between 72 px and 232 px; the preference key is `inteliscope.ui.sidebar.v1:<user_id>`, accepted values are `collapsed` and `expanded`, and absent or invalid values resolve to collapsed. Accounts never share the preference.
- From 1200–1359 px, navigation remains 72 px and the three-column workbench remains visible. The scope mark opens the categorized 260 px overlay without changing Feed width or scroll; the persisted width toggle is not presented.
- From 768–1199 px, navigation remains 72 px, the scope mark opens the same categorized overlay, and Agent is an on-demand right overlay.
- At 767 px and below, content is single-column, navigation moves to the bottom, and Agent is a bottom sheet ending at the viewport bottom.
- At 1440×900, the workbench shows the complete navigation, Feed, and 360 px Agent columns and four to five complete collapsed cards. At 1024×768, Agent overlays without resizing or scrolling the Feed. At 390×844, bottom navigation and Agent sheet remain reachable without horizontal page overflow.
- Navigation, Feed, and Agent have independent scroll regions. Opening or closing a panel preserves route, selected/expanded story, and Feed scroll anchor. Escape closes overlays and restores focus to their trigger.

## 6. Feed, virtualization, and OpenClaw conversation

- Feed has one mode, 全部. It defaults to `最新优先`, with newest content at the top; the explicit `最新优先`/`最旧优先` control persists per user. `/saved` and `/history` retain their collection ordering.
- `/feed` reads the canonical all-items response; `/saved` and `/history` reuse the same card, virtualization, filter, deep-link, and scroll behaviors.
- Long lists are virtualized with stable item IDs. A refresh captures the current rendered item ID and relative viewport offset synchronously at the request boundary. Measurement changes and source replacement retain that anchor; user scrolling cancels restoration ownership.
- New content auto-follows only when the viewport is within 96 px of the active fresh edge: top for newest-first and bottom for oldest-first. Otherwise the position remains stable and an explicit `N 条新内容` action appears at that edge.
- The centered content view bar aligns to the card column. Feed shows item count, order, filter, and active-filter count without recreating the removed search or manual-refresh controls. Saved and history place count, search, refresh, and filter in the same bar; mobile search expands from an explicit control. Filters include unread-first, source, channel, topic, and minimum score. Preferences remain user-isolated. Filtering, quick views, and unread-first reordering preserve rendered-ID anchors.
- Cards show source, time, title, an optional distinct summary, channel/topics, optional media, and bounded plain text on expansion. A summary that normalizes to the title is omitted rather than repeated or replaced with filler. Collapsed title and distinct summary are each limited to two lines; expansion is inline and does not replace the list or move the viewport anchor.
- Direct actions are open original, save, and add/remove Agent context. Mark read/unread, copy summary, and dismiss live in the compact overflow menu. There is no read-later action.
- `/feed`, `/saved`, and `/history` use the same Quiet Studio presentation: no progress rail or reserved rail gutter, a centered reading-width card column, an 18 px semantic content-card radius, standard graphite surfaces, thin semantic borders, and no persistent glow or heavy shadow.
- Quiet Studio card hover and press feedback uses the existing 120–220 ms motion tokens; inline expansion preserves the rendered ID-plus-offset anchor. Coarse-pointer actions remain fully visible and at least 44 px, and Reduced Motion makes displacement and expansion effectively immediate without hiding state.
- Content-card dimensions and reading width are owned by design-system tokens and presets. Feature code may compose layout, but it may not recreate approved page widths, typography, colors, shadows, radii, or motion values.
- The `/feed` Agent toggle uses a rounded split-panel glyph with neutral hover/press feedback and a restrained accent selected state. Its `aria-expanded`, focus restoration, responsive panel placement, and scroll preservation remain authoritative.
- Agent context contains at most eight ordered safe records per Inteliscope user and browser tab: `articleId/title/sourceName?/publishedAt?`, plus the question and model guidance (`auto`, `fast`, or `deep`). Adding an article only updates context and focuses the composer; it never sends a message or incurs model cost. The OpenClaw message contains the user question and article IDs, never article body, and instructs OpenClaw to read details through Remote MCP.
- With `HORIZON_OPENCLAW_CHAT_ENABLED=false`, desktop sidebar, tablet Drawer, and mobile Bottom Sheet render the existing deterministic copy handoff and create no WebSocket, local-address request, or MCP call. With the flag enabled, the same responsive containers render the browser-to-Gateway conversation: desktop fixed panel, tablet overlay, and mobile bottom/full-height sheet.
- Browser chat states are `未连接/连接中/已连接/重连中/工具未发现`. A tab owns at most one Gateway WebSocket and one dedicated `Inteliscope` session, supports history, streaming, stop, new conversation and reconnect, and bounds visible history to the newest 100 messages and 100,000 text characters. `auto/fast/deep` maps to default/low/high reasoning; every `chat.send` has a unique idempotency key and `deliver:false`.
- Gateway bootstrap token or dashboard address exists only in the connection form state and is cleared after a successful connection. The browser stores only a non-exportable Ed25519 private key, exact `operator.read + operator.write` device token, and session key in IndexedDB, isolated by Inteliscope user and normalized Gateway URL. Broader roles/scopes are rejected. Logout disconnects and clears page messages; “忘记此浏览器” also deletes the local pairing and shows server-side device revocation guidance.
- “OpenClaw 已连接” is derived only from Gateway WebSocket state. “Inteliscope 工具可用” is independently derived from `tools.effective`; credentials, an active delegation, or `last_used_at` never imply either online state. Origin repair guidance appends only the current Inteliscope origin to the user's existing allowlist and must never recommend `allowedOrigins:["*"]`.
- Viewers may navigate, open, search, copy, and assemble a handoff, but may not mutate Feed item state. Other role behavior follows the existing API/permission contract.

## 7. Administration and authentication pages

- Subscriptions, assistant connections, and settings use the shared `admin` PageFrame within the navigation shell and do not mount the Feed Agent panel. Their single route title lives in the Shell `PageHeader`; content uses `PageIntro`, `PageSection`, shared status states, and responsive grids instead of a duplicate display heading. `/agents` has two explicit regions: “Inteliscope 数据连接” for MCP URL/delegation scope/token lifecycle, and “OpenClaw 对话连接” for Gateway URL/browser pairing/reconnect/forget-device. MCP token and Gateway token are never named or presented as interchangeable credentials.
- Page information architecture, backend fields, role boundaries, write-only secret handling, job behavior, and Remote MCP safety remain unchanged by visual migration.
- Owner/Admin/member/viewer affordances must match existing authorization. Disabled or hidden controls are not substitutes for server enforcement.
- Login uses the shared `auth` PageFrame, brand mark, semantic typography, controls, and focus feedback without rendering the authenticated shell.
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

The static contract rejects MUI/Emotion imports, production feature-level direct HeroUI imports, nested `DesignSystemProvider` mounts, raw business-page colors, page-level visual constants, business-owned copies of the approved PageFrame widths, and deleted preview technology. Snapshot or expectation changes require an intentional contract change; they are not an automatic response to a failing visual test.
