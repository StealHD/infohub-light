<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/ui/ -->
# Inteliscope UI Contract

## 0. 任务读取路由

先读本索引了解设计系统和路由所有权；按页面/能力读取对应模块，视觉验收再读 acceptance。


## 1. Authority

This directory, indexed by this file, is the sole source of truth for production UI technology, visual language, component parameters, responsive behavior, and browser acceptance. `PLAN.md` records delivery state, `docs/decisions/` records durable choices, and `tests/test_impact_map.json` selects verification; they must reference this contract rather than restate its visual rules. API fields, authorization, query ownership, and error envelopes remain governed by `docs/contracts/api/` and existing application tests.

## 2. Production UI system

- Production uses React 19, HeroUI v3, Tailwind CSS v4, Lucide icons, and the self-hosted Noto Sans SC variable font.
- HeroUI Pro Default pages are the reference for finished hierarchy, density and component composition. Production uses only HeroUI v3 OSS components and repository-owned code, tokens and patterns; it neither imports nor copies HeroUI Pro code or dependencies.
- `frontend/src/design-system/**` owns the semantic theme, approved component exports, icon exports, and React Router bridge. Production application and feature code import UI components through this boundary and do not import `@heroui/*` directly.
- `AppBootstrap` mounts exactly one `DesignSystemProvider`, inside `BrowserRouter` and outside production routes. It remains inside the existing `QueryClientProvider`; Query Client, authentication, `ServiceApi`, caches, permissions, and query keys retain their existing lifetimes.
- MUI, MUI Icons, and Emotion are not production dependencies or source technologies. `frontend/src/ui/**`, the MUI prototype, and page-level legacy visual CSS Modules do not exist.
- The sole direct-HeroUI feature exception is the fixed-data development preview at `frontend/src/features/workbench-heroui/**`.

## 3. Visual language

- When a task does not name a different style, every new or changed surface inherits the current Quiet Studio / graphite-purple component roles and parameters. A user-requested color or style change is local to the named surface by default; it becomes a global family change only when the user explicitly asks for the whole application to change. Any reusable new parameter is added once to the design system and the component-parameter contract rather than repeated in page code.
- Production exposes exactly two application color modes: dark and light. Dark is the compatibility default and preserves the current graphite appearance; a shared icon-only control at the top-right of authenticated headers and the login surface changes the browser-persisted choice. The HTML bootstrap sanitizes and restores the same `inteliscope.ui.theme.v1` preference before React starts, so refresh does not flash the other mode and later operating-system appearance changes do not override the explicit choice. Color mode remains separate from the `graphite-purple` theme-family identifier so a future family can be added without changing the two-mode control. Both modes use quiet neutral canvases, layered semantic surfaces, restrained purple accents, semantic separators, and visible accessible focus rings; raw palette values belong only in design-system theme assets.
- The entire production application uses one system UI font stack: `-apple-system`, `BlinkMacSystemFont`, SF Pro where available, `PingFang SC` for Chinese on Apple platforms, then the self-hosted `Noto Sans SC Variable` and system sans-serif fallbacks. Routes and feature components may not define a competing font stack.
- Typography has exactly eleven semantic roles. Their implementation lives in `frontend/src/design-system/theme.css`; business code selects a role and never recreates its size, weight, line height, or letter spacing.

| Role | Size / line | Weight | Intended use |
|---|---:|---:|---|
| `type-display` | 24 / 32 px | 600 | standalone authentication or dedicated display titles |
| `type-section-title` | 18 / 26 px | 600 | major page sections |
| `type-page-title` | 16 / 24 px | 600 | workbench headers, dialogs, card section headers |
| `type-card-title` | 16 / 23 px | 600 | Feed, saved, and history card titles |
| `type-body` | 14 / 22 px | 400 | summaries, descriptions, notices, ordinary content |
| `type-chat` | 13 / 20 px | 400 | compact OpenClaw user and assistant message bodies |
| `type-control` | 13 / 20 px | 500 | buttons, toolbar values, navigation and menu actions |
| `type-meta` | 12 / 18 px | 400 | source, time, counts and technical metadata |
| `type-label` | 11 / 16 px | 500 | navigation group labels and compact composer labels |
| `type-micro` | 10 / 14 px | 500 | count badges and mobile navigation captions |
| `type-prose` | 14 / 26 px | 400 | expanded captured body text |

- Elements in one functional group use the same semantic role. In particular, the Feed view bar count and search use `type-control`, while its icon-only sort, reload, update and filter actions expose complete accessible names plus hover/focus explanations; source and time share `type-meta`; channel/topic metadata uses `type-meta` or `type-micro` according to density.
- Compact semantics are intentionally split instead of being expressed by one global Chip treatment. `StatusIndicator` represents running, connection, health, success, warning and failure with a distinct glyph and tone and never relies on color alone. Its default renders at least 12 px visible text; high-density source health, run records, global schedule and Agent connection/pairing placements may opt into `iconOnly`, which keeps the full accessible name and reveals the same text from an above-anchored Tooltip on hover or keyboard focus. The OpenClaw conversation header retains a compact visible state label. Notices, Toasts, dialogs, run traces and actionable recovery copy retain visible text. `MetaTag` represents channel, topic, format, scope and permission as neutral metadata; `CountBadge` represents only a count; `RemovableTag` is reserved for editable state, is keyboard focusable, has a remove target of at least 28 px and exposes pending/disabled state. Feature code does not globally resize every Chip or use a status pill for ordinary metadata.
- Production business code may not use Tailwind font-size, font-weight, line-height, or letter-spacing utilities (`text-xs`, `text-[…]`, `font-*`, `leading-*`, `tracking-*`). The executable UI contract rejects them. Alignment and semantic color utilities such as `text-left` and `text-muted` remain allowed.
- Radius scale: 16 px panels, 14 px cards, 10 px controls, and 8 px small controls. Static surfaces use contrast and a thin separator rather than glow or heavy shadow.
- Purposeful transitions run for 120–220 ms. Reduced Motion makes nonessential transitions effectively immediate while preserving loading indicators' understandable state.
- A hard refresh paints the graphite background and the last known navigation, header, Feed, and eligible docked Agent geometry directly from the HTML bootstrap shell. React removes that shell only after the authenticated route has committed; the root, shell, and page may not use an opacity entrance or replay a page-level entrance animation during takeover.
- Initial Feed and Agent reads use fixed-geometry design-system Skeletons that preserve the real column widths and closely approximate the loaded block heights. Loading motion is an opacity-only 1,400 ms restrained breath with no traveling shimmer. When data becomes available, only the local data layer transitions: Skeleton opacity exits in 120 ms and content reveals over 200 ms from `translateY(4px)` to rest. Reduced Motion makes all three effects immediate.
- Feature code does not define raw colors, shadows, radii, transition durations, or new page-level CSS visual systems. Native layout values may be used only where the static contract explicitly permits them.
- Loading, empty, degraded, failure, retry, and read-only states use the shared design-system vocabulary and accessible live regions. Persistent context, loading failures, disabled/degraded states, and errors that require correction remain local to their page, form, card, or dialog. Terminal global action feedback uses the design system's single top overlay Toast queue and never enters normal page flow.

## 4. Routes and page ownership

| Route | Production experience |
|---|---|
| `/feed` | Hero workbench, with time-flow and source-overview reading layouts |
| `/saved` | Hero workbench, saved collection |
| `/history` | Hero workbench, history collection |
| `/subscriptions` | Quiet Studio adaptive administration page with the same on-demand Agent rail/Drawer as Feed |
| `/agents` | Quiet Studio adaptive assistant-connection page; no Agent panel |
| `/settings` | Quiet Studio adaptive settings page; no Agent panel |
| `/manual` | Quiet Studio source-controlled operation manual with responsive section navigation and no Agent panel |
| `/changelog` | Quiet Studio product changelog with source-controlled Chinese entries, responsive month navigation, and no Agent panel |
| `/login` | Standalone Quiet Studio login page |

- `/later` permanently replaces to `/saved`, preserves only a valid `item` query value, and removes legacy `mode`.
- Authenticated unknown routes resolve coherently to the production Feed; unauthenticated protected routes resolve through the standalone login flow.
- `mode` is not a production Feed URL parameter. Legacy `mode` query parameters are removed while preserving `item`; `/feed` reading layout is instead a user-isolated browser preference.

## 模块索引

| 任务 | 模块 |
| --- | --- |
| 全站组件角色、尺寸、间距、图标和变体参数 | [组件参数](component-parameters.md) |
| Workbench shell、Feed、虚拟列表与 OpenClaw | [Workbench、Feed 与 OpenClaw](workbench-feed-openclaw.md) |
| Admin、Settings、认证与 ActorOps | [Admin、Settings、认证与 ActorOps](admin-settings-auth-actorops.md) |
| 设计系统/路由以外的可执行验收门禁 | [验收](acceptance.md) |
