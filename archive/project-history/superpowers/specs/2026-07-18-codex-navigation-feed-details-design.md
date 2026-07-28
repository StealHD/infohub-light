# Inteliscope Codex-style navigation and Feed detail refinement

## Status

- Date: 2026-07-18
- Approved direction: A, “Codex 式信息工作台”
- Implementation mode: single-agent local implementation; no subagents
- Scope: production HeroUI Shell, `/feed`, and the existing OpenClaw handoff panel

## Goal

Make the current Quiet Studio workbench feel organized and intentional without copying Codex product semantics. The refinement must improve navigation hierarchy, Feed scanning, touch behavior, and OpenClaw handoff composition while preserving Inteliscope’s existing APIs, permissions, queries, data, and read-only Agent boundary.

## Non-goals

- Do not add a chat backend, stream Agent output, claim that OpenClaw is online, or execute a model from the Web UI.
- Do not add source/project trees, user-created folders, new database fields, new API parameters, or a second component framework.
- Do not redesign subscriptions, settings, login, saved cards, or history cards in this batch.
- Do not copy macOS window controls or Codex-specific task/project concepts.

## 1. Categorized left navigation

### Brand and expansion

- Replace the collapsed `I` with a restrained Inteliscope scope mark based on a scan/radar glyph. The mark communicates information discovery and remains distinct from the Codex logo.
- Expanded brand row shows the mark, `Inteliscope`, and the sidebar disclosure control. The mark is also the disclosure target in the collapsed state.
- At `>=1360px`, the saved `collapsed|expanded` preference continues to participate in layout with 72px and 232px columns.
- At `768–1359px`, the persistent column remains 72px. Activating the scope mark opens a 260px categorized overlay without changing the Feed column width or scroll position. Outside click and Escape close the overlay and restore focus to the mark.
- At `<=767px`, retain the existing bottom navigation; do not add a competing side drawer in this batch.

### Groups

The expanded sidebar uses three clear groups:

1. `浏览`: 信息流、收藏、历史。
2. `常用视图`: 未读、AI、朋友动态、产品机会。 This group is collapsible and contains at most four compact quick views.
3. `管理`: 订阅、助手连接、设置。

Collapsed mode keeps route icons with separators and tooltips. Quick views are hidden in the 72px column to prevent icon ambiguity.

### Quick-view behavior

- Quick views reuse the existing per-user Feed v2 preference; they do not introduce API or URL fields.
- Selecting `未读` enables `unreadFirst` and clears channel/topic/min-score overrides. Selecting a named channel sets that channel and clears the other quick-view overrides.
- The preference writer emits one same-tab event. An already-mounted Feed updates immediately; navigation from another route writes the preference before opening `/feed`.
- Manual changes in the Feed filter popover remain authoritative and update the quick-view selection state.

### Account menu

- Remove the standalone logout icon.
- The bottom account row is one button: avatar, display name, Chinese role, and disclosure indicator when expanded; avatar-only with Tooltip when collapsed.
- First activation opens a Popover to the right; second activation, outside click, or Escape closes it.
- The menu shows account identity, `设置`, and a separated `退出登录` action. Logout happens only after explicitly choosing that menu item.

## 2. Feed view bar and ordering

- Replace the full-width sparse strip with a centered view bar aligned to the Quiet Studio card column (`max-width: 820px`). It uses a low-contrast secondary surface, 12px radius, compact height, and no persistent shadow.
- The bar contains:
  - item count on the left;
  - an explicit order button labelled `最新优先` or `最旧优先`;
  - the existing filter button and active-filter count on the right.
- `/feed` defaults to `最新优先`. The choice persists per user in Feed v2 preferences. `/saved` and `/history` retain their current collection order and controls.
- Feed order is a view transformation after filtering. Items with valid timestamps sort stably; invalid timestamps retain their API-relative order at the trailing edge.
- Virtual navigation treats the newest edge as `start` in newest-first mode and `end` in oldest-first mode. First entry, new-content follow behavior, new-content affordance, deep links, and expansion anchors use that edge rather than assuming the bottom.
- Changing order keeps the selected item expanded and scrolls that item back into view; without a selected item it moves to the active newest edge.

## 3. Card information hierarchy

- Default card anatomy remains: source avatar/name and relative time, title, optional distinct summary, channel/topics, and the three primary actions plus overflow.
- Titles use at most two lines in the collapsed state. Expanded cards reveal the full title with the body.
- Normalize whitespace, Unicode punctuation, and case before comparing title and summary. If the normalized summary is equal to the title, or only repeats the title with surrounding punctuation, omit it entirely.
- A missing or duplicate summary does not render fallback filler. The card simply becomes more compact.
- A distinct summary uses at most two lines when collapsed and remains fully readable after expansion.
- This is display-only normalization; historical snapshots and API fields are not rewritten.

## 4. OpenClaw handoff composer

- Keep the panel’s existing context list and truthful connection statuses.
- Replace the separated textarea/helper/button block with one Codex-inspired composer surface:
  - border and elevated neutral surface;
  - auto-growing question area using the Feed/macOS system font;
  - footer toolbar containing context count, model preference, transient status, and one circular primary action.
- Model preference is prompt metadata, not a Web-executed model. Options are:
  - `自动 · OpenClaw 决定`;
  - `速度优先`;
  - `深度分析`.
- Extend the session draft compatibly with an optional `modelPreference`. Existing v1 drafts sanitize to `auto`. The generated handoff prompt includes the selected preference as guidance to OpenClaw.
- The circular ArrowUp action is labelled and tooled as `复制交接提示词`; it remains disabled with zero context items. It copies the deterministic handoff prompt and never sends a network request.
- Replace the persistent sentence “仅生成交接提示词，不在站内运行 Agent” with a compact `交接模式` indicator and Tooltip. Copy success/failure appears as a short live status inside the composer.

## 5. State, errors, and accessibility

- Preserve current account isolation for sidebar, Feed preferences, and Agent session drafts.
- Popovers, overlays, Select, and composer controls use HeroUI primitives through the internal design-system export layer.
- All collapsed navigation items, the brand mark, account button, model preference, order control, and copy action have stable accessible names and visible focus.
- Coarse-pointer targets remain at least 44px and fully visible. Fine-pointer-only softening may remain on card actions.
- Reduced Motion removes displacement/scale while preserving state changes.
- Clipboard failure retains the user’s question/context and exposes a live status; it does not clear the draft.

## 6. Test and acceptance strategy

Use focused TDD for each behavior and run the repository full gate once after the batch:

- Sidebar: grouped labels, tablet overlay geometry, Escape/focus return, preference isolation, account menu toggle, and explicit logout.
- Quick views: same-tab preference event, cross-route navigation, active state, and manual filter synchronization.
- Feed: newest-first default, order persistence/toggle, stable invalid timestamp order, fresh-edge behavior, deep-link/expanded anchor retention.
- Cards: duplicate summary suppression, distinct summary retention, two-line collapsed hierarchy, and expanded content.
- Composer: model preference sanitization/persistence, prompt metadata, zero-context disabled action, copy success/failure, and no network execution.
- Browser acceptance at 1440×900, 1024×768, and 390×844 checks overflow, independent scroll, grouped navigation, overlay focus, visible touch actions, Feed order, card density, and Agent composer geometry.
- Axe must report no serious/critical findings. Backend, permissions, Query Keys, database, Remote MCP, Worker, and scheduler tests are not expanded because those contracts do not change.

## 7. Delivery boundary

- Update `UI_CONTRACT.md`, D030 delivery notes, `PLAN.md`, and `WORKLOG.md` only after implementation behavior and evidence exist.
- Build one final revision-locked local Docker image, replace only local API/Worker on port 8080, and leave the visible `/feed` tab available for user review.
- Do not merge, push, touch VPS, alter `.env`, run paid sources, or mutate stored Feed data without separate authorization.
