# Feed Codex-inspired Header and Progress Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine only the production `/feed` page by removing its search and refresh controls, applying a macOS system-font stack, and replacing its compact right-side progress pill with a left-side animated Codex-inspired rail.

**Architecture:** Route ownership remains in `HeroWorkbenchShell` and `HeroWorkbenchPage`. The shell applies the feed-only header and typography scope, while `VirtualFeed` receives an explicit `progressRailStyle="codex"` presentation flag only for `kind === "feed"`; saved and history keep their current compact rail and header controls. Semantic typography and motion values remain owned by the design-system theme, and all behavior continues to use the existing virtualizer and scroll-navigation code.

**Tech Stack:** React 19, TypeScript 6, HeroUI v3 through `frontend/src/design-system`, Tailwind CSS v4, TanStack Virtual, Vitest/React Testing Library, Playwright.

## Global Constraints

- Change only the production `/feed` visual presentation; `/saved`, `/history`, administration pages, login, API behavior, query keys, permissions, and Remote MCP remain unchanged.
- `/feed` removes the top search field and `更新信息流` button but keeps the title and Agent panel toggle.
- `/feed` uses the macOS system stack: `-apple-system`, `BlinkMacSystemFont`, `SF Pro Text`, `SF Pro Display`, `Helvetica Neue`, `PingFang SC`, with the existing Noto Sans SC fallback.
- The Codex rail is left-aligned, has no background pill, is approximately 300 px high, samples at most 28 targets, and hides below 640 px.
- The active tick becomes longer and foreground-colored; adjacent ticks partially extend. Width, color, opacity, and transform animate using the design-system 160 ms motion token and stop under Reduced Motion.
- Existing keyboard jump labels, virtualized DOM bound, scroll anchoring, refresh anchoring, deep links, and new-item behavior must remain intact.

---

### Task 1: Record the approved feed-only visual contract

**Files:**
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`

**Interfaces:**
- Consumes: The approved `/feed` design in this plan.
- Produces: The authoritative UI rule used by source and browser tests.

- [ ] **Step 1: Update the Feed contract**

Add the following requirements to `UI_CONTRACT.md` without changing saved/history behavior:

```markdown
- `/feed` uses the macOS system UI font stack on Apple platforms, with `PingFang SC` and the self-hosted Noto Sans SC variable font as Chinese/cross-platform fallbacks. The scope does not change other routes.
- `/feed` keeps a quiet header containing the page title and Agent toggle; search and manual refresh are absent during this visual-confirmation phase. `/saved` and `/history` retain their current controls.
- The `/feed` progress rail sits in the left card gutter, has no enclosing surface, is approximately 300 px high, samples at most 28 positions, and is hidden below 640 px. Exactly one nearest tick is current; it lengthens and changes contrast while neighboring ticks partially extend using the standard motion token. Reduced Motion removes the transition.
```

- [ ] **Step 2: Record the durable reason**

Append a decision entry explaining that the change is deliberately isolated to `/feed` until the user accepts the visual direction, and that it does not authorize a global style propagation.

- [ ] **Step 3: Validate documentation**

Run: `git diff --check`

Expected: exit 0 with no whitespace errors.

### Task 2: Drive the feed-only header and typography with tests

**Files:**
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/design-system/theme.css`

**Interfaces:**
- Consumes: React Router `location.pathname` and existing design-system theme scope.
- Produces: `feedRoute: boolean`, the semantic `--inteliscope-font-feed` token, and feed-only header rendering.

- [ ] **Step 1: Write failing route-scope tests**

Extend the test renderer to accept a pathname, then add tests equivalent to:

```tsx
it('removes search and manual refresh only from the Feed header', () => {
  renderShell('/feed')
  expect(screen.queryByPlaceholderText('搜索标题、来源或主题')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '更新信息流' })).not.toBeInTheDocument()
  expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-feed-typography', 'mac-system')
})

it('keeps collection header controls and the default typography scope', () => {
  renderShell('/saved')
  expect(screen.getByPlaceholderText('搜索标题、来源或主题')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '更新信息流' })).toBeInTheDocument()
  expect(screen.getByTestId('live-workbench-shell')).not.toHaveAttribute('data-feed-typography')
})
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `cd frontend && npm test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx`

Expected: FAIL because `/feed` still renders the search/refresh controls and has no feed typography marker.

- [ ] **Step 3: Implement the minimal route scope**

In `HeroWorkbenchShell.tsx`, derive an exact feed route and use it to hide only the two annotated controls:

```tsx
const feedRoute = location.pathname === '/feed'
const collectionHeaderControls = contentRoute && !feedRoute

<div
  data-testid="live-workbench-shell"
  data-feed-typography={feedRoute ? 'mac-system' : undefined}
  className={`grid h-dvh min-h-0 grid-cols-1 grid-rows-[52px_minmax(0,1fr)] overflow-hidden bg-background text-foreground min-[768px]:grid-cols-[72px_minmax(0,1fr)] ${desktopGridColumns} ${feedRoute ? '[font-family:var(--inteliscope-font-feed)]' : ''}`}
>
  {collectionHeaderControls ? <SearchField aria-label="搜索信息流" value={props.query} onChange={props.onQueryChange} className="min-w-0 flex-1" fullWidth variant="secondary">
    <SearchField.Group>
      <SearchField.SearchIcon><Icons.Search size={16} /></SearchField.SearchIcon>
      <SearchField.Input placeholder="搜索标题、来源或主题" />
      <SearchField.ClearButton aria-label="清除搜索" />
    </SearchField.Group>
  </SearchField> : <span className="flex-1" />}
  {collectionHeaderControls && <Button size="sm" variant="ghost" aria-label="更新信息流" isDisabled={refreshing || !props.onRefresh} onPress={requestRefresh}>
    <Icons.RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
    <span className="hidden min-[560px]:inline">{props.refreshState === 'queued' ? '已排队' : refreshing ? '更新中' : '更新信息流'}</span>
  </Button>}
</div>
```

In `theme.css`, add the semantic stack once:

```css
--inteliscope-font-feed: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Helvetica Neue", "PingFang SC", "Noto Sans SC Variable", sans-serif;
```

- [ ] **Step 4: Run the focused test to verify GREEN**

Run: `cd frontend && npm test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx`

Expected: PASS.

### Task 3: Drive the animated left progress rail with tests

**Files:**
- Modify: `frontend/src/features/workbench-live/VirtualFeed.test.tsx`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx`

**Interfaces:**
- Consumes: `kind: WorkbenchKind`, existing `sampleTickIndexes(itemCount, limit)`, `activeIndex`, and `jumpTo(index)`.
- Produces: `progressRailStyle?: 'compact' | 'codex'`; `/feed` passes `codex`, other collections pass `compact`.

- [ ] **Step 1: Write failing rail presentation tests**

Add a focused test equivalent to:

```tsx
it('renders the Codex feed rail as a bounded animated left gutter', () => {
  const cards = Array.from({ length: 200 }, (_, index) => toWorkbenchCardModel(makeItem(index)))
  render(<VirtualFeed
    progressRailStyle="codex"
    cards={cards}
    contextIds={[]}
    onToggleExpanded={vi.fn()}
    onToggleSaved={vi.fn()}
    onToggleContext={vi.fn()}
    onItemAction={vi.fn()}
  />)

  const rail = screen.getByRole('navigation', { name: '信息流进度' })
  expect(rail).toHaveAttribute('data-progress-rail', 'codex')
  expect(within(rail).getAllByRole('button')).toHaveLength(28)
  expect(rail).toHaveClass('left-2')
  expect(rail).not.toHaveClass('bg-surface/80')
  const current = within(rail).getByRole('button', { current: true })
  expect(current).toHaveAttribute('data-emphasis', 'active')
  expect(current.className).toContain('transition-[width,background-color,opacity,transform]')
})
```

Keep the existing default test asserting 12 compact ticks so collection behavior remains covered.

- [ ] **Step 2: Run the tests to verify RED**

Run: `cd frontend && npm test -- src/features/workbench-live/VirtualFeed.test.tsx`

Expected: FAIL because `progressRailStyle` and the Codex rail structure do not exist.

- [ ] **Step 3: Implement the minimal rail variant**

Add the prop and compute the nearest sampled tick:

```tsx
type VirtualFeedProps = {
  progressRailStyle?: 'compact' | 'codex'
  cards: WorkbenchCardModel[]
  sourceItemIds?: string[]
  expandedId?: string
  navigationTargetId?: string
  contextIds: string[]
  readonly?: boolean
  onToggleExpanded: (id: string) => void
  onToggleSaved: (id: string, saved: boolean) => void
  onToggleContext: (id: string) => void
  onItemAction: (id: string, action: ItemStateAction, value: boolean) => void
}

const codexRail = props.progressRailStyle === 'codex'
const ticks = useMemo(
  () => sampleTickIndexes(props.cards.length, codexRail ? 28 : 12),
  [codexRail, props.cards.length],
)
const activeTickPosition = ticks.reduce((nearest, index, position) =>
  Math.abs(index - activeIndex) < Math.abs(ticks[nearest] - activeIndex) ? position : nearest,
0)

function codexTickEmphasis(position: number) {
  const distance = Math.abs(position - activeTickPosition)
  if (distance === 0) return 'active'
  if (distance === 1) return 'near'
  return position % 4 === 0 ? 'major' : 'idle'
}
```

Render the Codex variant on the left without a surface, with active/neighbor emphasis and token-owned transitions. Preserve the compact right variant exactly for other routes. Pass the variant from `HeroWorkbenchPage`:

```tsx
<VirtualFeed
  progressRailStyle={kind === 'feed' ? 'codex' : 'compact'}
  cards={cards}
  sourceItemIds={sourceItemIds}
  expandedId={selectedId}
  navigationTargetId={deepLinkNotice ? undefined : initialNavigationTargetId}
  contextIds={agent.draft.itemIds}
  readonly={user.role === 'viewer'}
  onToggleExpanded={toggleExpanded}
  onToggleSaved={(id, saved) => stateMutation.mutateItem(id, { is_saved: saved })}
  onToggleContext={agent.toggleItem}
  onItemAction={(id, action, value) => stateMutation.mutateItem(id, { [action]: value })}
/>
```

- [ ] **Step 4: Run the focused test to verify GREEN**

Run: `cd frontend && npm test -- src/features/workbench-live/VirtualFeed.test.tsx`

Expected: PASS, including the 200-item DOM bound and both 12/28 tick contracts.

### Task 4: Verify the approved slice and record the work

**Files:**
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: The completed route and rail behavior.
- Produces: Reproducible verification evidence and a concise task record.

- [ ] **Step 1: Run static and focused verification**

Run:

```bash
cd frontend
npm run check:ui
npm run lint
npm run typecheck
npm test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx src/features/workbench-live/VirtualFeed.test.tsx src/features/workbench-live/workbenchModel.test.ts
```

Expected: all commands exit 0 without lint warnings or test failures.

- [ ] **Step 2: Run production build and full repository gate**

Run:

```bash
cd frontend && npm run build
cd .. && python scripts/test_gate.py run --mode full
```

Expected: Vite build succeeds, the artifact scan finds no deleted UI technology, and the full gate reports all selectors passing with `mapping_miss=false`.

- [ ] **Step 3: Perform browser acceptance**

At `http://127.0.0.1:8080/feed`, verify at 833×762 and 1440×900 that search and refresh are absent, the Agent toggle remains, the rail is in the left gutter, its active/neighbor widths follow scrolling, cards do not shift horizontally during scroll, and no console errors appear. Verify `/saved` still presents its existing header controls and compact rail.

- [ ] **Step 4: Append the worklog entry**

Record the changed files, RED→GREEN evidence, full verification results, and that no backend/API/query/permission/global route behavior changed.

- [ ] **Step 5: Check the final diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and only the intentional plan, contract, test, source, decision, and worklog files are modified.
