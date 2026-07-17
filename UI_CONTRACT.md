# Inteliscope Service UI Contract

## 1. Authority and scope

This file is the single source of truth for the default React Service UI visual system, component ownership, responsive layout, interaction states, and visual verification gates. Product scope and API behavior remain owned by `PLAN.md` and `API_CONTRACT.md`.

The current production experience remains the Material UI light shell. A separately gated `next` experience is now the target for the shell, Feed, saved collection, history, and OpenClaw context handoff. Subscriptions and settings retain their current information architecture and receive only a visual bridge during this phase; login remains unchanged.

Mac Codex is a visual-language reference for the `next` experience, not a pixel-perfect target or the sole source of truth. Inteliscope owns its information architecture, Web behavior, responsive rules, accessibility, and interaction feedback. The `next` experience must pass a fixed-data visual prototype review before any real Feed or Agent data wiring becomes the default.

## 2. Legacy theme authority

All new shell, Feed, and subscription visual values must come from the Material UI theme. Raw color, shadow, or radius literals are allowed only in the theme definition.

### 2.1 Palette

| Role | Value |
|---|---|
| primary | `#386A4A` |
| on-primary | `#FFFFFF` |
| primary container | `#CCE8D2` |
| on-primary container | `#173824` |
| app background | `#F8FAF3` |
| surface | `#FFFFFF` |
| surface container | `#F0F4EC` |
| surface container high | `#E9EEE5` |
| outline | `#768477` |
| outline variant | `#DCE2D9` |
| warning | `#765A00` |
| warning container | `#FFDF99` |
| error | `#BA1A1A` |
| error container | `#FFDAD6` |

### 2.2 Typography and assets

- Use self-hosted `Noto Sans SC Variable` for all UI and reading text, with system sans-serif fallback.
- Load weights 400–700 through Fontsource. Do not request Google Fonts or another CDN.
- Use the Material UI typography scale; feature components may select a named variant but must not create arbitrary font sizes.

### 2.3 Shape, spacing, and motion

- Panel radius: 24 px.
- List/card radius: 16 px.
- Control/pill radius: 20 px.
- Small control radius: 10 px.
- Use theme spacing and transitions. Sidebar width transitions use the theme's shortest standard duration and honor reduced motion.
- Shadows are reserved for overlays, menus, temporary drawers, and task alerts. Static page panels use tonal separation and outlines.

### 2.4 Next workbench theme and visual gate

- The `next` theme is dark-only for this phase. It uses canvas `#151516`, paper `#1B1B1D`, high surface `#242429`, primary `#A99AF7`, primary container `#312C47`, primary text `#F2F2F4`, secondary text `#A3A3AA`, and low-contrast semantic outlines. Raw values remain theme-only.
- Next radii are 16 px panels, 14 px cards, 10 px controls, and 8 px small controls. Static cards use surface contrast plus a one-pixel outline, not glow or full-card accent borders.
- Motion is limited to 120–220 ms for card expansion, panel changes, progress feedback, and context insertion. Reduced Motion reduces these transitions to effectively zero.
- The dev-only `/__preview/workbench` route is deterministic, does not require authentication or call `/api/*`, and exists only as the visual approval surface.
- The dev-only `/__preview/workbench-heroui` route is the independent HeroUI v3 candidate. It uses the same sanitized stories, navigation, breakpoints, card actions, short rail, and OpenClaw handoff model as `/__preview/workbench`; differences are limited to the candidate component system and its dedicated graphite-purple theme.
- The HeroUI candidate uses HeroUI Card, Button, SearchField, Chip, TextArea, Tooltip, Avatar, ScrollShadow, and Separator with Tailwind v4. It preserves the library's focus ring, press feedback, rounded controls, and Reduced Motion behavior without adding glow or heavy shadow.
- Visual review evaluates hierarchy, density, reading comfort, operation reachability, focus, and state clarity. Pixel overlay parity with Mac Codex is explicitly not a gate.

## 3. Component boundary

`frontend/src/ui/**` owns the theme, provider, approved Material UI exports, and semantic wrappers. Feature code must import controlled inputs, buttons, icon actions, chips, tabs, surfaces, status presentation, empty states, and filter overlays from that layer.

Feature code may not:

1. Import Emotion directly.
2. Import controlled Material UI components directly when an internal wrapper/export exists.
3. Add raw palette, radius, or shadow literals.
4. Create a new page-level button, input, status badge, card, popover, or alert visual language.
5. Add new shell, Feed, or subscription CSS Modules.

Layout primitives remain allowed through the internal UI export layer. Existing CSS Modules outside the migrated shell, Feed, and subscription workspace are compatibility code and do not define the future visual system.

`frontend/src/design-system/**` is the formal HeroUI boundary for production migration. It owns the graphite-purple dark theme, local Noto Sans SC asset, approved HeroUI and Lucide exports, and the HeroUI `RouterProvider` bridge to React Router. Production feature code may use HeroUI only through this boundary; direct `@heroui/*` imports are rejected. The authenticated bootstrap installs only the navigation bridge at this stage, so the existing MUI provider, Query Client, authentication and `ServiceApi` lifetimes remain unchanged and legacy pages do not inherit the new theme before migration.

The fixed-data HeroUI candidate remains the sole feature-level direct-import exception at `frontend/src/features/workbench-heroui/**`. That boundary may import `@heroui/*` and its dedicated stylesheet, but it may not import MUI, Emotion, or `frontend/src/ui/**`. The application entry must load this prototype only behind `import.meta.env.DEV`; opening it must not initialize the authenticated application bootstrap, production global CSS, Query Client, or API client. The production build may contain the formal design-system package but must still exclude the prototype route, fixtures and dedicated prototype CSS markers.

## 4. Legacy shell contract

- App bar height is 64 px and retains brand, global search, and acquisition action.
- Desktop navigation is a permanent Material UI Drawer, collapsed to 72 px by default and expandable to 240 px.
- Sidebar state is stored as `collapsed` or `expanded` under `inteliscope.ui.sidebar.v1:<user_id>`. Invalid or absent values fall back to `collapsed`. The preference is browser-local and is not cleared on logout.
- At widths 1200 px and above, expansion participates in layout. From 900–1199 px, expansion uses a temporary overlay so the reader is not compressed. At 767 px and below, keep the existing mobile bottom navigation and master/detail behavior.
- The expand/collapse control is the first Drawer item and uses the same alignment and hit target as navigation items. It must not appear as a detached bottom control.
- Collapsed navigation requires labels, tooltips, visible focus, and an accessible expand control. Toggling must preserve route, selected item, and scroll state.
- Settings sits above one unified account card at the bottom of the Drawer. Expanded state shows avatar, name, Chinese role, and menu indicator; collapsed state shows the aligned avatar with a tooltip.
- “更新信息流” means fetching every enabled subscription, deduplicating results, and refreshing the Feed; it does not change subscription settings. Each request first refreshes Worker state and creates a job only when the Worker is `ready`.
- Queued/running progress is represented by the action button and run history, not by a permanent Snackbar. Success notifications close after 4 seconds; blocked, partial, and failed notifications close after at most 8 seconds. Every notification is manually closeable and a dismissed `job_id + status` event must not reopen during polling.

### 4.1 Next workbench shell contract

- Navigation contains 信息流、收藏、历史、订阅、助手连接和设置. 稍后读 is absent.
- At 1360 px and above the grid is `232 px navigation + minmax(640 px, 1fr) Feed + 360 px Agent`. From 1200–1359 px navigation is 72 px while all three columns remain visible. From 768–1199 px navigation stays 72 px and Agent becomes an on-demand overlay. At 767 px and below the Feed is single-column, navigation moves to the bottom, and Agent becomes a bottom sheet.
- The header is 52 px and uses browser-native Web behavior. It must not reproduce macOS traffic lights, window chrome, drag regions, or desktop-only navigation affordances.
- Navigation, Feed, and Agent use independent scroll regions. Toggling either side panel must preserve the active route, expanded story, and Feed scroll anchor.
- Both development prototypes expose an in-page MUI/HeroUI switch using independent URLs. At 1440×900 the HeroUI candidate shows four to five complete cards; the version switch, responsive panel changes, and card actions do not create API requests or reset the other prototype's source fixtures.
- The production rollout uses `VITE_UI_EXPERIENCE=next|legacy`; `next` does not become the default until the visual gate and automated verification pass. Legacy remains available for at least one release.

## 5. Legacy Feed workspace contract

- At 1200 px and above, the list is 420–440 px wide and the reader consumes the remaining space. At 1440×900, 6–8 rows must be visible without horizontal overflow.
- Feed mode uses Tabs and remains represented by the `mode` URL parameter. Item selection remains represented by `item`.
- Drawer and mobile navigation include a dedicated `/saved` collection. Saved and later items remain readable after they leave the latest snapshot.
- Unread-first and active filters are visible as controls/chips. Source, channel, topic, and minimum score live in a keyboard-accessible filter overlay and apply immediately. Removing a chip clears that filter.
- Filter fields use controlled Material UI Select components with separate labels and values. Native Select rendering is not allowed in this overlay.
- List rows show source, author when available, relative time, canonical title, one-line summary, and signal label. Read state reduces emphasis without lowering text contrast below accessibility requirements.
- Selecting a row only opens it. Read state changes only through the explicit “标记已读/标记未读” action; optimistic updates patch Feed, history, saved, later, and detail caches together and roll all copies back on failure.
- Reader order is: source/author/exact published time and health, canonical title, one summary, signal strength/channel/type plus at most four native engagement facts, then the bounded plain-text body excerpt directly beneath the summary block. The React reader never renders `action_suggestion`.
- Feed lists prefer `presentation.version=1`; the selected reader requests and prefers `presentation.version=2`. Legacy flat fields are fallback-only. It must not display or search `reason`/“为什么值得关注”. Source-specific raw metadata must not leak into feature components.
- The reader shows captured `body_text` as bounded plain text and a same-origin image gallery. It is captured-source content, not a webpage full-text proxy. `excerpt_only` old data remains explicitly degraded. It has no redundant “来源摘录” heading; a truncated body shows `内容已截断，打开原文查看完整内容。`. When `canonical_url` and `source_url` differ, expose separate “打开原文”和“查看原帖” actions.
- Feed mode and unread-first are stored per user under `inteliscope.ui.feed.v1:<user_id>` and survive navigation/reload without crossing users.
- Direct actions are open original, read later, and save. More actions contain explicit mark read/unread, copy summary, and dismiss. Viewers may open and copy but may not mutate item state.
- Missing data must degrade explicitly: `未评分`, `未分类频道`, `未分类类型`, `暂无概括；请打开原文核对完整内容。`, and `该条内容未保存正文片段；重新获取来源后可显示。`.
- Loading uses Skeleton; fetch errors use Alert with retry; empty filtered results include a clear-filters action.

### 5.1 Next Feed and context contract

- Feed has one mode: 全部. 精选 and 日报 tabs, mode preference, and mode-specific copy are absent. Legacy `mode` query parameters are removed while preserving `item`.
- Older content is above newer content. Initial entry anchors to the bottom. New content follows only when the user is within 96 px of the bottom; otherwise it preserves position and presents an explicit `N 条新内容` action.
- Stories are slightly elevated cards showing source, time, title, one summary, channel/topics, and optional media. A user click expands bounded plain-text content in place without replacing the list or moving the scroll anchor.
- Direct actions are open original, save, and add/remove Agent context. Mark read/unread, copy summary, and dismiss remain in a compact overflow menu. There is no read-later action.
- A 100–115 px short tick rail represents relative Feed position. Its active tick is the only bright line; each tick is keyboard reachable and can jump to its content segment. It never becomes a full-height timeline.
- The OpenClaw panel holds at most eight ordered item IDs plus a user question. It generates a deterministic handoff prompt instructing OpenClaw to call `get_item`; it does not claim the Agent is online and does not implement site chat or streaming.
- Connection copy is limited to 已配置、未配置、检查失败. A credential record is never presented as online presence.
- The prototype uses fixed sanitized stories. After approval, `/feed` reads only `items`, while saved and history reuse the same card/scroll components. Long lists use virtualization and retain stable expansion keys.

## 6. Subscription and source workspace contract

- `/subscriptions` uses three tabs: “我的订阅”, “来源库”, and “运行记录”. It must not expose a continuous legacy form/card page or nested `<details>` editors.
- Subscriptions and source discovery are grouped by effective channel, following the channel order returned by `/api/config`; missing channels fall back to “其他”. Search expands matching groups automatically. Source type, scope, health, subscription state, next fetch time, and role are rendered as filters or Chinese card labels rather than first-level directories; internal enums are not user-facing text.
- Source and subscription forms use the backend channel list as a Select. Topic fields use a free-solo multi-select backed by the active topic library; referenced topics missing from that library remain visible as `已停用` until the user replaces them.
- Every mutable subscription card exposes “立即获取”. It refreshes Worker state first, creates or reuses the existing asynchronous `source_fetch` job only when Worker is ready, and refreshes Feed, health, counts, and run history on a terminal result.
- The Settings topic library uses add/search/delete chips with explicit Save and Undo. Removing a topic only removes it from future choices and AI preference vocabulary; it never rewrites source/subscription references or historical snapshots.
- Owner/Admin may edit shared public or team source definitions. Members may subscribe, unsubscribe, and edit only their own subscription parameters. Viewers are read-only. A private source definition is editable only by its creator, including when another user is an administrator.
- Members may create private sources only. Administrators may choose private, team, or public scope when creating a source.
- Source settings and subscription settings use responsive Dialogs. Empty groups consume no layout; no-source, no-subscription, and no-filter-results states have distinct actions and explanations.
- Run records translate task type and status into user-facing Chinese. Each row presents source, creation/completion time, result count, and failure reason when present. Raw job type, status, error code, and ID exist only inside administrator technical details.
- Terminal run records expose one collapsed “响应结构” control. It compares “上游原始结构” with “系统标准化结构” using field-path/type tables only; raw values never enter the DOM. `empty/cached/unavailable/truncated` must have explicit Chinese degradation copy, old Jobs explain that no structure was recorded, and both tables wrap without horizontal page overflow at 390px.
- When Worker state is stale, missing, or cannot be checked, “更新信息流” does not create a queued job and explains the block in human language.

### 6.1 Authenticated action feedback

- 认证布局使用单一 `ActionFeedbackProvider`，按 `user + action + entity` 保存 `pending/queued/running/succeeded/partial/failed/blocked`；用户切换或退出必须清空。
- 用户点击异步按钮后立即显示“提交中…/保存中…/获取中…”，只禁用对应实体。明显的乐观变化不额外弹成功提示；失败必须回滚并通过 live region 提示。
- Feed terminal job 是一次性事件：首次加载的历史 terminal job 静默标记已见；只有 `snapshot_created=true` 的成功任务显示“信息流已更新”。成功 no-op 静默，partial/failed 可以提示但无 snapshot 时不得声称“已更新”。轮询与跨路由不得重放同一 `job_id + status`。
- 详情页按顺序展示全部同源缓存图片。`captured` 显示来源正文；当 `excerpt_only` 与上方 AI 概括相同，只显示一次概括并明确说明来源全文尚不可用。

## 7. Assistant connection workspace contract

1. `/agents` 页面标题为“助手连接”，桌面侧栏入口在“订阅”之后；移动端不增加底部导航数量，只从设置页入口进入。
2. 页面只管理当前用户的 Remote MCP 连接凭证，支持列表、创建、重命名、吊销、复制配置和故障排查。不输入或保存本地 Gateway URL，不请求 `127.0.0.1:18789`，不连 WebSocket，不探测 OpenClaw 在线状态，不提供站内聊天。
3. 创建成功后，明文令牌只存在当前 Dialog 的 React local state。Dialog 不可背景点击或 Escape 关闭；用户必须点击“我已保存”，随后立即清除。令牌不得进入 Query cache、URL、日志、localStorage 或 sessionStorage，生成的 OpenClaw 配置只包含 `${INTELISCOPE_MCP_TOKEN}` 引用。
4. 页面不轮询；窗口聚焦和手动刷新时重读列表。active 且 `last_used_at=null` 固定显示“从未使用”，任何 `last_used_at` 都只能标记为“最近使用”，不得推断“在线”。viewer 与其他角色具有相同的连接管理能力。
5. 加载、空、错误重试、功能关闭、五连接上限、重命名和吊销状态复用现有 MUI 受控组件与 theme，不建立独立 CSS 或视觉体系。

## 8. Verification gates

Every shell, Feed, or subscription visual change must pass:

1. UI contract static checks and ESLint import restrictions.
2. TypeScript and Vitest.
3. Vite production build.
4. Playwright at 1440×900 collapsed, 1440×900 expanded, 1024×768 overlay, and 390×844 mobile regression.
5. Axe with no serious or critical violations.
6. Visual review using fixtures with at least eight mixed-state items, long Chinese text, missing optional fields, and multiple source-health states.

The `next` workbench additionally requires 1440 px three-column, 1024 px overlay, and 390 px mobile captures; card actions must remain reachable with Agent open, the short rail must stay bounded, and a 200-item fixture must keep the rendered card count bounded. The HeroUI candidate additionally requires four to five complete cards at 1440×900, actual HeroUI component slots, zero MUI DOM classes, zero `/api/*` requests, focus restoration after closing overlays, and a production-build exclusion check. The visual prototype review is a mandatory checkpoint before real-data wiring.

Snapshot updates require an intentional UI contract or approved design change; they are not an automatic fix for a failing visual test.
