# Inteliscope Codex-style Navigation and Feed Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the production HeroUI workbench with a categorized Codex-inspired left navigation, newest-first Feed controls, non-repetitive card hierarchy, an explicit account menu, and a compact OpenClaw handoff composer.

**Architecture:** Keep the existing HeroUI production tree, API/query layer, permissions, and Remote MCP boundary. Add small pure state helpers first, then let the Shell, Feed, virtual list, and Agent panel consume them through existing internal design-system exports. The implementation is single-agent and incremental because the user explicitly declined subagents.

**Tech Stack:** React 19, TypeScript, HeroUI 3, Tailwind CSS 4, TanStack Query, TanStack Virtual, React Router, Vitest/RTL, Playwright, Docker Compose.

## Global Constraints

- Work only in `infohub-light/.worktrees/codex-inspired-workbench`.
- Do not change backend APIs, database schemas, Query Keys, role rules, Remote MCP, Worker/scheduler behavior, `.env`, VPS, or stored Feed data.
- Do not add another component framework or import `@heroui/*` from feature code.
- Use focused RED/GREEN tests per task. Run the full repository gate once after all four tasks.
- Build one revision-locked Docker image after the final implementation commit and replace only the local API/Worker used by `127.0.0.1:8080`.
- Do not spawn subagents.

---

## Task 1: Add compatible preference and handoff state

**Files:**

- Modify: `frontend/src/features/feed/feedPreference.ts`
- Modify: `frontend/src/features/feed/feedPreference.test.ts`
- Modify: `frontend/src/features/workbench-live/agentContext.ts`
- Modify: `frontend/src/features/workbench-live/agentContext.test.ts`
- Create: `frontend/src/features/workbench-live/workbenchQuickViews.ts`
- Create: `frontend/src/features/workbench-live/workbenchQuickViews.test.ts`

- [ ] **Step 1: Write failing Feed preference tests**

Add tests that prove:

```ts
expect(readFeedPreference(userId).order).toBe('newest')
expect(readFeedPreference(userId, legacyV1)).toMatchObject({ unreadFirst: true, order: 'newest' })
expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ detail: { userId } }))
```

Also prove that an invalid persisted order sanitizes to `newest` and `oldest` round-trips.

- [ ] **Step 2: Run the preference test and confirm RED**

Run:

```bash
cd frontend && npm test -- src/features/feed/feedPreference.test.ts
```

Expected: failures because `FeedPreference` has no `order` and no same-tab event.

- [ ] **Step 3: Implement Feed order and same-tab notification**

Add:

```ts
export type FeedOrder = 'newest' | 'oldest'
export const FEED_PREFERENCE_CHANGED_EVENT = 'inteliscope:feed-preference-changed'

export type FeedPreference = {
  unreadFirst: boolean
  source: string
  channel: string
  topic: string
  minScore?: number
  order: FeedOrder
}
```

Default and legacy migration use `newest`. `writeFeedPreference` stores the sanitized value and dispatches one `CustomEvent` whose detail contains only `userId`; the event must not expose filter contents.

- [ ] **Step 4: Write failing quick-view tests**

Cover these exact transformations:

```ts
applyQuickView(base, 'unread')
// unreadFirst true; source/channel/topic cleared; minScore undefined

applyQuickView(base, 'ai')
// unreadFirst false; channel 'AI'; other quick-view overrides cleared
```

Cover `朋友动态` and `产品机会`, active-view detection, and a manual mixed filter returning `null`.

- [ ] **Step 5: Implement pure quick-view helpers**

Create stable IDs and Chinese labels:

```ts
export type WorkbenchQuickViewId = 'unread' | 'ai' | 'friends' | 'product'
export const WORKBENCH_QUICK_VIEWS = [
  { id: 'unread', label: '未读' },
  { id: 'ai', label: 'AI' },
  { id: 'friends', label: '朋友动态' },
  { id: 'product', label: '产品机会' },
] as const
```

The helper mutates no input object and preserves `order`.

- [ ] **Step 6: Write failing Agent draft tests**

Prove legacy drafts become `modelPreference: 'auto'`, invalid values sanitize to `auto`, all three supported values persist, and the generated prompt contains a deterministic Chinese preference line.

- [ ] **Step 7: Implement compatible Agent preference metadata**

Add:

```ts
export type AgentModelPreference = 'auto' | 'fast' | 'deep'
```

Extend `AgentContextDraftV1` with `modelPreference`. Keep the storage key/version unchanged, sanitize old drafts, and add prompt guidance only; do not add a request or execution path.

- [ ] **Step 8: Run focused GREEN tests**

Run:

```bash
cd frontend && npm test -- \
  src/features/feed/feedPreference.test.ts \
  src/features/workbench-live/workbenchQuickViews.test.ts \
  src/features/workbench-live/agentContext.test.ts
```

Expected: all pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add frontend/src/features/feed frontend/src/features/workbench-live/agentContext* frontend/src/features/workbench-live/workbenchQuickViews*
git commit -m "feat(ui): add workbench view preferences"
```

---

## Task 2: Build categorized navigation and account menu

**Files:**

- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx`
- Modify: `frontend/src/design-system/icons.tsx`
- Optionally create if extraction keeps the Shell readable: `frontend/src/features/workbench-live/WorkbenchSidebar.tsx`

- [ ] **Step 1: Write failing Shell tests**

Add focused tests for:

- expanded labels `浏览`, `常用视图`, and `管理`;
- quick-view activation writes the per-user preference before navigating to `/feed`;
- collapsed brand has accessible name `展开导航` and contains no literal brand text `I`;
- at 1280px the mark opens an overlay without changing the persistent 72px rail;
- Escape closes the overlay and returns focus to the mark;
- the account row toggles a menu; logout is absent before opening and calls `onLogout` only after selecting `退出登录`;
- collapsed account mode remains avatar-only with an accessible label.

- [ ] **Step 2: Run the Shell test and confirm RED**

Run:

```bash
cd frontend && npm test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx
```

Expected: missing categories, overlay behavior, brand mark, quick views, and account popover.

- [ ] **Step 3: Add the Inteliscope mark**

Export a restrained scan/radar SVG component through `design-system/icons.tsx`. It must inherit `currentColor`, remain legible at 20–22px, and avoid copying Codex branding.

- [ ] **Step 4: Replace the flat navigation with groups**

Use these route groups:

```ts
浏览: 信息流, 收藏, 历史
常用视图: 未读, AI, 朋友动态, 产品机会
管理: 订阅, 助手连接, 设置
```

Keep collapsed route icons and tooltips; hide quick-view rows at 72px. Selecting a quick view calls `applyQuickView`, writes the preference, then navigates. Listen for the same-tab event so active styling updates after manual Feed changes.

- [ ] **Step 5: Add the tablet navigation overlay**

At 768–1359px keep the persistent 72px rail and open a 260px HeroUI Drawer/Popover-style overlay from the mark. Preserve the Feed scroll container. Support outside click, Escape, and focus return. At >=1360px retain the existing persisted 72/232px participating layout; at <=767px retain bottom navigation.

- [ ] **Step 6: Replace standalone logout with the account menu**

Make the full account row one trigger. The Popover contains identity, Chinese role, `设置`, a separator, and `退出登录`. Logout is a menu action, never a sibling icon. Reuse HeroUI primitives from the internal design system.

- [ ] **Step 7: Run focused Shell tests and typecheck**

Run:

```bash
cd frontend && npm test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx
npm run typecheck
```

Expected: pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add frontend/src/design-system/icons.tsx frontend/src/features/workbench-live/HeroWorkbenchShell*
git commit -m "feat(ui): organize workbench navigation"
```

---

## Task 3: Refine Feed ordering, view bar, and card hierarchy

**Files:**

- Modify: `frontend/src/features/workbench-live/workbenchModel.ts`
- Modify: `frontend/src/features/workbench-live/workbenchModel.test.ts`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.tsx`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.test.tsx`
- Modify: `frontend/src/features/feed/feedModel.ts`
- Modify tests only where current sort contracts require it: `frontend/src/features/feed/feedModel.test.ts`

- [ ] **Step 1: Write failing order and summary-model tests**

Prove:

- `newest` sorts valid timestamps descending;
- `oldest` sorts valid timestamps ascending;
- invalid timestamps retain API-relative order after valid items;
- duplicate title/summary with case, whitespace, or surrounding punctuation yields `summary: undefined`;
- a distinct summary remains present;
- a missing summary remains absent rather than rendering filler.

- [ ] **Step 2: Run model tests and confirm RED**

Run:

```bash
cd frontend && npm test -- \
  src/features/workbench-live/workbenchModel.test.ts \
  src/features/feed/feedModel.test.ts
```

Expected: failures because sorting is ascending-only and summary is mandatory/filler-backed.

- [ ] **Step 3: Implement pure order and display normalization**

Keep canonical source selection stable, then apply `/feed` order as a view transformation. Normalize display comparison with Unicode normalization, collapsed whitespace, lowercase, and stripped surrounding punctuation. Change `WorkbenchCardModel.summary` to optional. Never rewrite API data.

- [ ] **Step 4: Write failing page and virtual-list behavior tests**

Cover:

- the compact centered bar renders `最新优先`, count, filter, and active-filter count;
- toggling renders `最旧优先`, persists it, and retains the expanded item;
- newest-first initial position is the start; oldest-first initial position is the end;
- follow-new-content and the new-content button target the active fresh edge;
- selected/deep-linked cards remain anchored after an order switch;
- collapsed title and distinct summary use two-line clamps; duplicate summary has no summary node.

- [ ] **Step 5: Implement the centered Feed view bar**

Align it to `max-w-[820px]`, use a compact secondary surface, and render count on the left with order/filter controls on the right. Remove the static `最新在下` text. Subscribe to the per-user preference event so quick views update the mounted Feed immediately.

- [ ] **Step 6: Make VirtualFeed edge-aware**

Add an explicit prop such as:

```ts
freshEdge: 'start' | 'end'
```

Use it for first-entry positioning, near-edge detection, automatic follow, new-content affordance placement/scrolling, and order changes. Do not change `/saved` or `/history` behavior.

- [ ] **Step 7: Refine collapsed card typography**

Clamp the title and distinct summary to two lines when collapsed; expanded cards show full text and body. Omitting a summary must remove its vertical gap. Preserve the existing primary and overflow actions.

- [ ] **Step 8: Run focused GREEN tests**

Run:

```bash
cd frontend && npm test -- \
  src/features/feed/feedPreference.test.ts \
  src/features/feed/feedModel.test.ts \
  src/features/workbench-live/workbenchModel.test.ts \
  src/features/workbench-live/VirtualFeed.test.tsx \
  src/features/workbench-live/HeroWorkbenchShell.test.tsx
```

Expected: pass.

- [ ] **Step 9: Commit Task 3**

```bash
git add frontend/src/features/feed frontend/src/features/workbench-live
git commit -m "feat(ui): refine feed order and card hierarchy"
```

---

## Task 4: Rebuild the OpenClaw handoff composer and deliver locally

**Files:**

- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx`
- Modify: `frontend/e2e/production-workbench.spec.ts`
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `PLAN.md`
- Modify: `WORKLOG.md`

- [ ] **Step 1: Write failing composer tests**

Cover:

- zero context disables `复制交接提示词`;
- model options are `自动 · OpenClaw 决定`, `速度优先`, and `深度分析`;
- changing the preference persists the draft and changes copied prompt metadata;
- the composer exposes `交接模式` instead of the persistent explanatory sentence;
- copy success and clipboard failure appear in a live status without clearing question/context;
- no fetch/API mutation occurs when copying.

- [ ] **Step 2: Run the Shell test and confirm RED**

Run:

```bash
cd frontend && npm test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx
```

- [ ] **Step 3: Implement the compact composer**

Use one elevated composer surface containing an auto-growing text area and footer toolbar. The footer shows context count, model preference, transient live status, and a circular ArrowUp copy action. Add Tooltip/accessibility labels and preserve session/account isolation. Do not execute or simulate Agent output.

- [ ] **Step 4: Update focused browser coverage**

Add assertions at 1440×900, 1024×768, and 390×844 for grouped navigation, tablet overlay, account menu, newest-first control, non-duplicated card text, visible touch actions, and composer geometry. Reuse existing fixtures and do not expand backend coverage.

- [ ] **Step 5: Run focused frontend validation**

Run:

```bash
cd frontend
npm test -- \
  src/features/feed/feedPreference.test.ts \
  src/features/workbench-live/workbenchQuickViews.test.ts \
  src/features/workbench-live/workbenchModel.test.ts \
  src/features/workbench-live/VirtualFeed.test.tsx \
  src/features/workbench-live/agentContext.test.ts \
  src/features/workbench-live/HeroWorkbenchShell.test.tsx
npm run lint
npm run typecheck
npm run build
```

Expected: pass.

- [ ] **Step 6: Update the visual control plane**

Record the implemented behavior in `UI_CONTRACT.md`, add a new decision after D030 without duplicating visual constants, update the active plan line, and append evidence to `WORKLOG.md` only after tests exist.

- [ ] **Step 7: Run one complete repository gate**

Use the repository’s existing full-gate command discovered from `AGENTS.md`/scripts, then run:

```bash
git diff --check
```

Expected: full gate passes. Fix only causal failures; do not broaden scope.

- [ ] **Step 8: Commit Task 4**

```bash
git add frontend UI_CONTRACT.md DECISION_LOG.md PLAN.md WORKLOG.md
git commit -m "feat(ui): polish OpenClaw handoff workspace"
```

- [ ] **Step 9: Build one revision-locked local image**

Derive the 12-character revision from the final commit, build the existing service image once with that revision, and replace only local API/Worker containers. Verify API health and Worker readiness before opening the page.

- [ ] **Step 10: Validate the live page**

Using the in-app browser, validate `http://127.0.0.1:8080/feed` at desktop/tablet/mobile widths:

- newest content is first and the order control switches correctly;
- no title/summary duplicate is visible;
- brand, grouped sidebar, account menu, and tablet overlay work;
- Feed scroll position survives opening/closing navigation and Agent panels;
- composer copy action, preference, and status work without a network execution;
- console errors are zero and Axe has no serious/critical findings.

Leave `/feed` open for user review.

