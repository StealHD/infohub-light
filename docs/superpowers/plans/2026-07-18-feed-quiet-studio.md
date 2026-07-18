# Feed Quiet Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已确认的 Quiet Studio 视觉与交互应用到生产 `/feed`，删除进度刻度，换成双栏 Agent 图标，并在不影响收藏、历史、数据语义和滚动稳定性的前提下改善卡片层级与动效。

**Architecture:** 通过 `HeroWorkbenchPage` 向共享 `VirtualFeed` 传递路由级 `visualVariant`，让 `/feed` 使用 `quiet-studio`，而 `/saved` 与 `/history` 继续使用 `collection`。Shell 只在 `/feed` 使用双栏 Agent 图标和 Quiet Studio 控件状态；卡片差异留在共享卡片的显式 variant 分支，颜色、圆角和动效继续由设计系统 token 管理。

**Tech Stack:** React 19、TypeScript、HeroUI 3、Tailwind CSS 4、Lucide、TanStack Query、TanStack Virtual、Vitest/RTL、Playwright/Axe、Vite。

## Global Constraints

- 范围仅限 `/feed`；收藏、历史、订阅、设置、登录和 Agent 内容设计不继承 Quiet Studio 视觉。
- 不恢复 `/feed` 搜索框或“更新信息流”按钮。
- 删除桌面、平板和移动端的 Feed 进度刻度及其预留空白；`/saved` 与 `/history` 保留当前紧凑右轨。
- 顶栏高度保持 52px；Agent 面板继续在 ≥1200px 参与布局、768–1199px 右侧覆盖、≤767px 使用 Bottom Sheet。
- Feed 使用 macOS 系统字体栈；中文回退为 `PingFang SC` 和本地 Noto Sans SC。
- 内容卡片使用语义表面、细边界、18px Feed 专用圆角和克制状态反馈；业务组件不得出现原始颜色值或页面级 CSS。
- 卡片展开控制在现有 120–220ms 动效上限内，并支持 Reduced Motion；不自动标记已读。
- 不修改后端 API、数据库、权限、Query Key、Worker、Remote MCP、历史数据或依赖版本。
- 200 条信息时 Feed 卡片 DOM 不超过 40；现有 ID+offset 锚点、新内容提示、深链和用户隔离语义保持不变。

---

### Task 1: Quiet Feed 顶栏、工具行与双栏 Agent 图标

**Files:**
- Rename: `frontend/src/design-system/icons.ts` → `frontend/src/design-system/icons.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx:84-106`
- Modify: `frontend/src/app/App.test.tsx:93-103`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx:274-297`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx:118-141`

**Interfaces:**
- Consumes: `feedRoute: boolean`、`agentOpen: boolean`、现有 `FeedPreference`。
- Produces: 内部 `Icons.SplitPanel` 图标、Feed-only `data-header-visual="quiet-studio"`、`data-agent-toggle-visual="quiet-studio"`、`N 条内容 · 最新在下` 工具行和可选筛选数量。

- [ ] **Step 1: 写出 Feed-only 顶栏和工具行失败测试**

在 `HeroWorkbenchShell.test.tsx` 的 `HeroWorkbenchShell Feed visual scope` 中扩充 Feed 用例：

```tsx
const toggle = screen.getByRole('button', { name: '收起 Agent 面板' })
expect(toggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
expect(toggle.querySelector('[data-split-panel-icon]')).not.toBeNull()
expect(toggle.querySelector('[data-panel-fill]')).toHaveAttribute('opacity', '0.16')
expect(toggle.querySelector('.lucide-panel-right-close')).toBeNull()
expect(toggle.querySelector('.lucide-panel-right-open')).toBeNull()
expect(screen.getByRole('banner')).toHaveAttribute('data-header-visual', 'quiet-studio')
```

在收藏用例中补充隔离断言：

```tsx
const collectionToggle = screen.getByRole('button', { name: '收起 Agent 面板' })
expect(collectionToggle).not.toHaveAttribute('data-agent-toggle-visual')
expect(screen.getByRole('banner')).not.toHaveAttribute('data-header-visual')
```

在 `App.test.tsx` 的 `renders the production feed with the authenticated HeroUI workbench` 中补充：

```tsx
expect(await screen.findByText('1 条内容 · 最新在下')).toBeInTheDocument()
expect(screen.queryByText('旧内容在上，最新内容在下 · 1 条')).not.toBeInTheDocument()
expect(screen.queryByText('全部', { exact: true })).not.toBeInTheDocument()
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
npm --prefix frontend run test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx src/app/App.test.tsx
```

Expected: FAIL；内部 `SplitPanel` 尚不存在，现有图标仍为 `PanelRightClose/Open`，Feed 顶栏没有 Quiet Studio 标记，工具行仍显示旧文案和“全部”。

- [ ] **Step 3: 增加受控的双栏图标**

将 `frontend/src/design-system/icons.ts` 重命名为 `icons.tsx`，保留 Lucide 统一出口并增加项目内部图标；业务组件仍只能从设计系统导入：

```tsx
import type { SVGProps } from 'react'

export * from 'lucide-react'

type SplitPanelProps = SVGProps<SVGSVGElement> & {
  open?: boolean
  size?: number | string
}

export function SplitPanel({ open = false, size = 18, ...props }: SplitPanelProps) {
  return <svg
    {...props}
    data-split-panel-icon
    width={size}
    height={size}
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <rect x="2.25" y="2.25" width="15.5" height="15.5" rx="3.25" />
    <path d="M11.75 2.75v14.5" />
    <rect
      data-panel-fill
      x="12"
      y="2.75"
      width="5.25"
      height="14.5"
      rx="2.5"
      fill="currentColor"
      stroke="none"
      opacity={open ? '0.16' : '0'}
    />
  </svg>
}
```

- [ ] **Step 4: 最小实现 Quiet Studio 顶栏材质与图标**

先只替换 `HeroWorkbenchShell.tsx` 的 `<header>` 开始标签，标题、collection 搜索与刷新子树不动：

```tsx
<header
  data-header-visual={feedRoute ? 'quiet-studio' : undefined}
  className={`col-start-1 row-start-1 flex h-[52px] items-center gap-2 border-b border-separator px-3 min-[768px]:col-start-2 min-[768px]:px-4 ${feedRoute ? 'bg-surface/95 supports-[backdrop-filter:blur(1px)]:backdrop-blur-lg' : 'bg-surface'}`}
>
```

再把 Agent 按钮改为 Feed-only 分支；收藏和历史保留当前图标：

```tsx
{contentRoute && <Button
  ref={agentToggleRef}
  size="sm"
  variant="ghost"
  isIconOnly
  data-agent-toggle-visual={feedRoute ? 'quiet-studio' : undefined}
  data-agent-open={agentOpen ? 'true' : 'false'}
  className={feedRoute
    ? 'h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 data-[agent-open=true]:bg-accent/15 data-[agent-open=true]:text-accent motion-reduce:transform-none'
    : undefined}
  aria-label={agentOpen ? '收起 Agent 面板' : '展开 Agent 面板'}
  aria-expanded={agentOpen}
  aria-controls="live-agent-panel"
  onPress={() => setAgentOpen((value) => !value)}
>
  {feedRoute
    ? <Icons.SplitPanel open={agentOpen} size={18} aria-hidden="true" />
    : agentOpen
      ? <Icons.PanelRightClose size={17} aria-hidden="true" />
      : <Icons.PanelRightOpen size={17} aria-hidden="true" />}
</Button>}
```

- [ ] **Step 5: 最小实现 Feed 工具行文案与筛选状态**

在 `HeroWorkbenchPage.tsx` 中计算激活筛选数量：

```tsx
const quietStudio = kind === 'feed'
const activeFilterCount = [
  preference.unreadFirst,
  preference.source,
  preference.channel,
  preference.topic,
  preference.minScore !== undefined,
].filter(Boolean).length
```

用以下分支替换工具行开头；Popover 内容和 collection 分支保持现状：

```tsx
<div className={`flex min-h-[48px] flex-wrap items-center gap-2 border-b border-separator px-3 py-2 sm:px-5 ${quietStudio ? 'bg-background/95 supports-[backdrop-filter:blur(1px)]:backdrop-blur-md' : ''}`}>
  <span className="text-xs text-muted">
    {quietStudio ? `${cards.length} 条内容 · 最新在下` : `旧内容在上，最新内容在下 · ${cards.length} 条`}
  </span>
  {!quietStudio && <Chip size="sm" color="accent" variant="soft"><Chip.Label>全部</Chip.Label></Chip>}
  {!quietStudio && preference.unreadFirst && <Chip size="sm" variant="soft"><Chip.Label>未读优先</Chip.Label></Chip>}
  <Popover>
    <Popover.Trigger
      aria-label="筛选信息流"
      className={`inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-sm text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus ${quietStudio ? 'ml-auto' : ''}`}
    >
      <Icons.SlidersHorizontal size={15} aria-hidden="true" />筛选
      {quietStudio && activeFilterCount > 0 && <span aria-label={`已启用 ${activeFilterCount} 项筛选`} className="rounded-md bg-accent/15 px-1.5 text-xs text-accent">{activeFilterCount}</span>}
    </Popover.Trigger>
```

`Popover.Content`、`Popover.Dialog` 和它们的关闭标签保持当前实现不变；本步骤只替换外层工具行、状态 Chip 和 `Popover.Trigger`。

- [ ] **Step 6: 运行 focused 测试并确认 GREEN**

Run:

```bash
npm --prefix frontend run test -- src/features/workbench-live/HeroWorkbenchShell.test.tsx src/app/App.test.tsx
```

Expected: PASS；Feed 使用双栏图标和简化工具行，收藏仍使用原 collection 控件。

- [ ] **Step 7: 提交 Task 1**

```bash
git add frontend/src/design-system/icons.ts frontend/src/design-system/icons.tsx frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx frontend/src/app/App.test.tsx frontend/src/features/workbench-live/HeroWorkbenchShell.tsx frontend/src/features/workbench-live/HeroWorkbenchPage.tsx
git commit -m "feat(ui): quiet the Feed controls"
```

---

### Task 2: 删除 Feed 轨道并收回内容留白

**Files:**
- Modify: `frontend/src/features/workbench-live/VirtualFeed.test.tsx:21-76`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.tsx:20-32,160-193,439-490`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx:152-164`

**Interfaces:**
- Consumes: `kind: WorkbenchKind`。
- Produces: `visualVariant?: 'collection' | 'quiet-studio'`；默认值为 `collection`，Feed 显式传入 `quiet-studio`。

- [ ] **Step 1: 把 Codex 轨道测试替换为 Quiet Studio 无轨道测试**

保留默认 collection 的 12 刻度测试，删除两个 `progressRailStyle="codex"` 测试，并增加：

```tsx
it('removes the progress rail and its reserved gutter from the Quiet Studio Feed', async () => {
  const cards = Array.from({ length: 200 }, (_, index) => toWorkbenchCardModel(makeItem(index)))
  render(<VirtualFeed
    visualVariant="quiet-studio"
    cards={cards}
    contextIds={[]}
    onToggleExpanded={vi.fn()}
    onToggleSaved={vi.fn()}
    onToggleContext={vi.fn()}
    onItemAction={vi.fn()}
  />)

  expect((await screen.findAllByTestId('workbench-card')).length).toBeLessThanOrEqual(40)
  expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
  const scroll = screen.getByTestId('workbench-feed-scroll')
  expect(scroll).toHaveAttribute('data-feed-visual', 'quiet-studio')
  expect(scroll.className).not.toContain('pl-16')
})

it('keeps the compact progress rail for collection routes', () => {
  render(<VirtualFeed
    visualVariant="collection"
    cards={Array.from({ length: 20 }, (_, index) => toWorkbenchCardModel(makeItem(index)))}
    contextIds={[]}
    onToggleExpanded={vi.fn()}
    onToggleSaved={vi.fn()}
    onToggleContext={vi.fn()}
    onItemAction={vi.fn()}
  />)

  expect(screen.getAllByRole('button', { name: /跳转到第 .* 条信息/ })).toHaveLength(12)
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
npm --prefix frontend run test -- src/features/workbench-live/VirtualFeed.test.tsx
```

Expected: FAIL；`visualVariant` 尚不存在，Feed 仍渲染进度导航并保留左侧 padding。

- [ ] **Step 3: 引入明确的 route-scoped variant**

在 `VirtualFeed.tsx` 定义：

```tsx
type VirtualFeedVariant = 'collection' | 'quiet-studio'

type VirtualFeedProps = {
  visualVariant?: VirtualFeedVariant
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
```

在组件开始处替换 `codexRail`：

```tsx
const visualVariant = props.visualVariant ?? 'collection'
const quietStudio = visualVariant === 'quiet-studio'
const ticks = useMemo(
  () => quietStudio ? [] : sampleTickIndexes(props.cards.length, 12),
  [props.cards.length, quietStudio],
)
```

删除 `activeTickPosition` 和 Codex tick emphasis 分支。只在 collection 渲染现有紧凑轨道：

```tsx
{!quietStudio && <nav
  aria-label="信息流进度"
  data-progress-rail="compact"
  className="absolute right-2 top-1/2 z-10 flex h-28 -translate-y-1/2 flex-col justify-around rounded-lg bg-surface/80 px-1.5 py-2 backdrop-blur"
>
  {ticks.map((index) => <button
    key={index}
    type="button"
    aria-label={`跳转到第 ${index + 1} 条信息`}
    aria-current={Math.abs(activeIndex - index) <= Math.max(1, Math.ceil(props.cards.length / Math.max(1, ticks.length)) / 2) ? 'true' : undefined}
    className="h-0.5 w-3 rounded-lg bg-muted aria-current:w-5 aria-current:bg-accent"
    onClick={() => jumpTo(index)}
  />)}
</nav>}
```

给滚动容器加入 variant marker 并收回 Feed 轨道留白：

```tsx
<div
  ref={scrollRef}
  data-testid="workbench-feed-scroll"
  data-feed-visual={visualVariant}
  className={`min-h-0 flex-1 overflow-y-auto overscroll-contain py-4 [overflow-anchor:none] ${quietStudio ? 'px-3 sm:px-5' : 'px-3 pr-10 sm:px-5 sm:pr-12'}`}
  onScroll={updateScrollState}
  onWheel={cancelInlineAnchor}
  onTouchStart={cancelInlineAnchor}
  onPointerDown={cancelInlineAnchor}
  onKeyDown={cancelInlineAnchor}
>
```

同时把虚拟列表高度容器改为 Feed 约 820px 居中列，collection 保持现有宽度：

```tsx
<div
  className={`relative mx-auto w-full ${quietStudio ? 'max-w-[820px]' : 'max-w-3xl'}`}
  style={{ height: virtualizer.getTotalSize() }}
>
```

- [ ] **Step 4: 只让 `/feed` 请求 Quiet Studio variant**

在 `HeroWorkbenchPage.tsx` 替换旧 `progressRailStyle`：

```tsx
<VirtualFeed
  visualVariant={kind === 'feed' ? 'quiet-studio' : 'collection'}
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

- [ ] **Step 5: 运行 focused 测试并确认 GREEN**

Run:

```bash
npm --prefix frontend run test -- src/features/workbench-live/VirtualFeed.test.tsx src/app/App.test.tsx
```

Expected: PASS；Feed 无进度导航，collection 仍有 12 个紧凑刻度，200 条 DOM 上限不变。

- [ ] **Step 6: 提交 Task 2**

```bash
git add frontend/src/features/workbench-live/VirtualFeed.test.tsx frontend/src/features/workbench-live/VirtualFeed.tsx frontend/src/features/workbench-live/HeroWorkbenchPage.tsx
git commit -m "feat(ui): remove the Feed progress rail"
```

---

### Task 3: Quiet Studio 卡片层级与原位展开动效

**Files:**
- Modify: `frontend/src/design-system/theme.css:6-11,44-48,148-175`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.test.tsx:78-119`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.tsx:49-158,490-525`

**Interfaces:**
- Consumes: Task 2 的 `visualVariant` 和 `quietStudio`。
- Produces: `WorkbenchCard` 的 `visualVariant: VirtualFeedVariant`、`data-card-visual`、`data-card-expanded`、`data-context-state` 与可动画详情 wrapper。

- [ ] **Step 1: 写出 Quiet Studio 卡片状态失败测试**

在 `VirtualFeed.test.tsx` 增加：

```tsx
it('applies Quiet Studio card hierarchy without leaking it to collection cards', () => {
  const card = toWorkbenchCardModel(makeItem(1))
  const view = render(<VirtualFeed
    visualVariant="quiet-studio"
    cards={[card]}
    contextIds={[]}
    onToggleExpanded={vi.fn()}
    onToggleSaved={vi.fn()}
    onToggleContext={vi.fn()}
    onItemAction={vi.fn()}
  />)

  expect(screen.getByRole('article', { name: '信息 1' })).toHaveAttribute('data-card-visual', 'quiet-studio')
  expect(screen.getByTestId('card-details-item-1')).toHaveAttribute('data-state', 'collapsed')

  view.rerender(<VirtualFeed
    visualVariant="collection"
    cards={[card]}
    contextIds={[]}
    onToggleExpanded={vi.fn()}
    onToggleSaved={vi.fn()}
    onToggleContext={vi.fn()}
    onItemAction={vi.fn()}
  />)
  expect(screen.getByRole('article', { name: '信息 1' })).toHaveAttribute('data-card-visual', 'collection')
  expect(screen.queryByTestId('card-details-item-1')).not.toBeInTheDocument()
})

it('animates Quiet Studio details and exposes a confirmation state for Agent context', () => {
  render(<VirtualFeed
    visualVariant="quiet-studio"
    cards={[toWorkbenchCardModel(makeItem(1))]}
    expandedId="item-1"
    contextIds={['item-1']}
    onToggleExpanded={vi.fn()}
    onToggleSaved={vi.fn()}
    onToggleContext={vi.fn()}
    onItemAction={vi.fn()}
  />)

  const details = screen.getByTestId('card-details-item-1')
  expect(details).toHaveAttribute('data-state', 'expanded')
  expect(details.className).toContain('grid-rows-[1fr]')
  expect(screen.getByRole('button', { name: '将 信息 1 移出 Agent 上下文' })).toHaveAttribute('data-context-state', 'selected')
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
npm --prefix frontend run test -- src/features/workbench-live/VirtualFeed.test.tsx
```

Expected: FAIL；卡片没有 variant marker、动画 wrapper 或 confirmation state。

- [ ] **Step 3: 在设计系统增加 Feed 专用圆角 token**

在 `theme.css` 的圆角 token 区增加：

```css
--inteliscope-radius-feed-card: 18px;
```

现有 Reduced Motion 会把 standard/deliberate token 降为 1ms；不增加新的原始 duration 或业务颜色。

- [ ] **Step 4: 将 variant 显式传给 WorkbenchCard**

扩充 `WorkbenchCard` 参数：

```tsx
function WorkbenchCard({ visualVariant, card, expanded, inContext, contextFull, readonly, onToggleExpanded, onToggleSaved, onToggleContext, onItemAction }: {
  visualVariant: VirtualFeedVariant
  card: WorkbenchCardModel
  expanded: boolean
  inContext: boolean
  contextFull: boolean
  readonly?: boolean
  onToggleExpanded: () => void
  onToggleSaved: () => void
  onToggleContext: () => void
  onItemAction: (action: ItemStateAction, value: boolean) => void
}) {
  const quietStudio = visualVariant === 'quiet-studio'
  const externalUrl = safeExternalUrl(card.url)
  const copySummary = () => void navigator.clipboard?.writeText(card.summary || card.title)
}
```

在 virtual row 中传入 `visualVariant={visualVariant}`。

- [ ] **Step 5: 实现 route-scoped 卡片层级**

将 Card 外层改为：

```tsx
<Card
  data-testid="workbench-card"
  data-card-visual={visualVariant}
  data-card-expanded={expanded ? 'true' : 'false'}
  role="article"
  aria-label={card.title}
  variant="secondary"
  className={`group/card w-full gap-0 border p-0 shadow-none ${quietStudio
    ? 'rounded-[var(--inteliscope-radius-feed-card)] border-separator bg-surface-secondary transition-[background-color,border-color,transform,box-shadow] duration-[var(--inteliscope-motion-standard)] hover:-translate-y-px hover:border-border hover:bg-surface-tertiary focus-within:border-border motion-reduce:transform-none'
    : 'rounded-2xl border-separator bg-surface-secondary'}`}
>
```

标题/摘要按钮、来源行和 Footer 使用显式 variant classes：

```tsx
<button
  type="button"
  className={`w-full cursor-pointer text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${quietStudio ? 'px-[19px] pt-[18px]' : 'px-4 pt-4'}`}
  aria-label={`${expanded ? '收起' : '展开'} ${card.title}`}
  aria-expanded={expanded}
  onClick={onToggleExpanded}
>
  <span className={`mb-2 flex items-center gap-2 text-muted ${quietStudio ? 'text-[11px]' : 'text-xs'}`}>
    <AvatarRoot className={`${quietStudio ? 'size-[25px]' : 'size-7'} shrink-0`}>
      {card.sourceAvatar && <AvatarImage src={card.sourceAvatar} alt={card.source} />}
      <AvatarFallback>{card.source.slice(0, 1).toUpperCase()}</AvatarFallback>
    </AvatarRoot>
    <span className="truncate">{card.source}</span>
    <span aria-hidden="true">·</span>
    <span>{relativeTime(card.publishedAt)}</span>
  </span>
  <Card.Title className={quietStudio ? 'line-clamp-2 text-base font-semibold leading-[1.38]' : 'line-clamp-2 text-base leading-6'}>{card.title}</Card.Title>
  <Card.Description className={quietStudio ? 'mt-1.5 line-clamp-2 text-[13px] leading-5 text-muted' : 'mt-1 line-clamp-2 leading-5'}>{card.summary}</Card.Description>
</button>

<Card.Footer className={`flex flex-wrap items-center justify-between gap-2 ${quietStudio ? 'px-[19px] pb-[15px] pt-[10px]' : 'px-4 pb-4 pt-3'}`}>
```

Quiet Studio 的频道/主题 Chip 追加 `className="text-[10px]"`；collection 保留当前 classes。所有数字都是已批准的 Feed layout values，不创建页面 CSS。

- [ ] **Step 6: 实现可访问的原位展开过渡**

collection 继续条件渲染现有 `Card.Content`。Quiet Studio 始终渲染以下 wrapper：

```tsx
{quietStudio ? <div
  data-testid={`card-details-${card.id}`}
  data-state={expanded ? 'expanded' : 'collapsed'}
  aria-hidden={!expanded}
  className={`grid px-[19px] transition-[grid-template-rows,opacity] duration-[var(--inteliscope-motion-deliberate)] ease-out ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
>
  <div className="min-h-0 overflow-hidden">
    <div className="border-t border-separator pb-1 pt-3 text-sm leading-7 text-foreground whitespace-pre-wrap">
      {card.body || '该条内容未保存正文片段；重新获取来源后可显示。'}
    </div>
    {card.bodyTruncated && <p className="mt-2 text-xs text-muted">内容已截断，打开原文查看完整内容。</p>}
    {card.imageUrl && <img className="mt-3 max-h-80 w-full rounded-xl object-contain" src={card.imageUrl} alt={`${card.title} 内容图片`} loading="lazy" />}
  </div>
</div> : expanded && <Card.Content className="px-4 pt-3">
  <div className="border-t border-separator pt-3 text-sm leading-7 text-foreground whitespace-pre-wrap">
    {card.body || '该条内容未保存正文片段；重新获取来源后可显示。'}
  </div>
  {card.bodyTruncated && <p className="mt-2 text-xs text-muted">内容已截断，打开原文查看完整内容。</p>}
  {card.imageUrl && <img className="mt-3 max-h-80 w-full rounded-xl object-contain" src={card.imageUrl} alt={`${card.title} 内容图片`} loading="lazy" />}
</Card.Content>}
```

点击范围仍只覆盖标题/摘要按钮，Footer 操作不会冒泡到展开控制。

- [ ] **Step 7: 实现操作显隐、触控尺寸和上下文确认态**

给操作容器加 `data-card-actions`，使用移动可见、桌面悬停增强的 classes：

```tsx
<div
  data-card-actions
  className={`ml-auto flex items-center gap-1 transition-opacity duration-[var(--inteliscope-motion-standard)] ${quietStudio ? 'opacity-100 min-[768px]:opacity-60 min-[768px]:group-hover/card:opacity-100 min-[768px]:group-focus-within/card:opacity-100' : ''}`}
>
```

Quiet Studio 的原文链接、收藏/Agent 两个 HeroUI Button 与更多菜单 `summary` 均使用 `size-11 min-[768px]:size-8`，按压态为 `active:scale-95 motion-reduce:transform-none`；collection 使用现有 `size-8`。Agent 上下文按钮增加：

```tsx
data-context-state={inContext ? 'selected' : 'idle'}
className={quietStudio ? 'data-[context-state=selected]:bg-accent/15 data-[context-state=selected]:text-accent' : undefined}
```

图标分支为：

```tsx
{inContext
  ? quietStudio
    ? <Icons.Check size={15} aria-hidden="true" />
    : <Icons.X size={15} aria-hidden="true" />
  : <Icons.Sparkles size={15} aria-hidden="true" />}
```

- [ ] **Step 8: 运行 focused 测试并确认 GREEN**

Run:

```bash
npm --prefix frontend run test -- src/features/workbench-live/VirtualFeed.test.tsx src/features/workbench-live/HeroWorkbenchShell.test.tsx src/app/App.test.tsx
npm --prefix frontend run check:ui
npm --prefix frontend run typecheck
```

Expected: 全部 PASS；UI checker 不报告业务原始颜色、圆角或直接 HeroUI 导入。

- [ ] **Step 9: 提交 Task 3**

```bash
git add frontend/src/design-system/theme.css frontend/src/features/workbench-live/VirtualFeed.test.tsx frontend/src/features/workbench-live/VirtualFeed.tsx
git commit -m "feat(ui): add Quiet Studio Feed cards"
```

---

### Task 4: 三视口浏览器交互与回归门禁

**Files:**
- Modify: `frontend/e2e/production-workbench.spec.ts:1-620`

**Interfaces:**
- Consumes: `data-feed-visual`、`data-card-visual`、`data-agent-toggle-visual` 和现有 Agent/virtualization APIs。
- Produces: 1440×900、1024×768、390×844 的 Quiet Studio 生产验收，以及 collection rail 隔离回归。

- [ ] **Step 1: 写出生产 Feed 视觉边界失败断言**

在主生产工作台测试的 `/feed` 进入后增加：

```ts
await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
await expect(page.getByText('200 条内容 · 最新在下')).toBeVisible()
await expect(page.getByText('全部', { exact: true })).toHaveCount(0)
await expect(page.getByRole('button', { name: '更新信息流' })).toHaveCount(0)
const agentToggle = page.getByRole('banner').getByRole('button', { name: /^(收起|展开) Agent 面板$/ })
await expect(agentToggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
await expect(agentToggle.locator('[data-split-panel-icon]')).toHaveCount(1)
await expect(page.getByRole('banner')).toHaveAttribute('data-header-visual', 'quiet-studio')
await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
```

桌面项目增加卡片 token 与居中宽度断言：

```ts
const quietCard = page.locator('[data-card-visual="quiet-studio"]').first()
expect(await quietCard.evaluate((element) => getComputedStyle(element).borderRadius)).toBe('18px')
expect((await quietCard.boundingBox())?.width ?? 0).toBeLessThanOrEqual(820)
```

- [ ] **Step 2: 用后台任务完成模拟替代已删除的手动刷新按钮**

生产 Query Client 明确关闭了 `refetchOnWindowFocus`，所以测试不得用 `focus` 或 `visibilitychange` 假装刷新。在 `beforeEach` 的 API fixture 中把刷新建模为一个初始 `queued` 的后台任务，并通过 Playwright 暴露函数使它进入 `succeeded`；现有 `useFeedActivity` 轮询随后会按生产路径失效 Feed Query：

删除原来的 `refreshCreated` 变量和 `POST /api/jobs/user-feed-refresh` fixture 分支；以下变量放在 `beforeEach` 顶部，两个 `else if` 分支替换同路径的旧分支：

```ts
let backgroundRefreshComplete = false
await page.exposeFunction('completeBackgroundRefresh', () => {
  backgroundRefreshComplete = true
})

else if (url.pathname === '/api/feed/latest') {
  const batchMode = new URL(page.url()).searchParams.has('batch')
  data = { schema_version: 2, items: backgroundRefreshComplete
    ? batchMode ? [...items.slice(80), ...batchRollingItems] : [...items.slice(1), rollingItem]
    : items }
} else if (url.pathname === '/api/jobs') {
  data = { jobs: [{
    id: 'refresh-1',
    user_id: 'e2e-user',
    job_type: 'user_feed_refresh',
    status: backgroundRefreshComplete ? 'succeeded' : 'queued',
    created_at: '2026-07-17T04:00:00Z',
    finished_at: backgroundRefreshComplete ? '2026-07-17T04:00:02Z' : null,
    result: {},
  }] }
}

async function requestBackgroundRefresh(page: Page) {
  await page.evaluate(async () => {
    window.dispatchEvent(new Event('inteliscope:workbench-refresh-request'))
    await (window as typeof window & {
      completeBackgroundRefresh: () => Promise<void>
    }).completeBackgroundRefresh()
  })
}
```

把主工作台和 unread-first 锚点用例中的两处已删除按钮调用改为 `requestBackgroundRefresh(page)`。需要同步采样锚点的 unread-first 用例，在单个 `feedScroll.evaluate` 中先读取顶部卡片，再完成后台任务：

```ts
const anchorBefore = await feedScroll.evaluate(async (scroll) => {
  const bounds = scroll.getBoundingClientRect()
  const top = Array.from(scroll.querySelectorAll<HTMLElement>('[data-testid="workbench-card"]'))
    .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const anchor = { name: top?.getAttribute('aria-label') ?? '', offset: top ? top.getBoundingClientRect().top - bounds.top : 0 }
  window.dispatchEvent(new Event('inteliscope:workbench-refresh-request'))
  await (window as typeof window & {
    completeBackgroundRefresh: () => Promise<void>
  }).completeBackgroundRefresh()
  return anchor
})
```

删除主用例中的 Feed rail jump 段落，以及三个只验证 Feed rail 导航所有权的测试：`a jump during an in-flight refresh releases the captured refresh anchor`、`a clamped rail jump releases ownership before a later external search update`、`a wheel release after cards commit cancels the pending navigation RAF`。collection rail 继续由 Vitest 覆盖。

- [ ] **Step 3: 增加展开、Agent 和 Reduced Motion 验收**

在主测试已展开卡片后，直接使用卡片所在 virtual row 的稳定 `data-item-id`，不要从可见标题推导 ID：

```ts
await expect(card).toHaveAttribute('data-card-expanded', 'true')
const expandedId = await card.locator('xpath=..').getAttribute('data-item-id')
expect(expandedId).not.toBeNull()
await expect(page.getByTestId(`card-details-${expandedId}`)).toHaveAttribute('data-state', 'expanded')
```

新增独立 Reduced Motion 测试：

```ts
test('Quiet Studio honors Reduced Motion without losing state', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/feed')
  const card = page.locator('[data-card-visual="quiet-studio"]').last()
  await card.getByRole('button', { name: /展开/ }).click()
  const id = await card.locator('xpath=..').getAttribute('data-item-id')
  const details = page.getByTestId(`card-details-${id}`)
  await expect(details).toHaveAttribute('data-state', 'expanded')
  const durations = await details.evaluate((element) => getComputedStyle(element).transitionDuration
    .split(',')
    .map((value) => Number.parseFloat(value)))
  expect(durations.every((seconds) => seconds <= 0.001)).toBe(true)
})
```

新增键盘与触摸目标测试：

```ts
test('Quiet Studio keeps keyboard expansion and mobile action targets accessible', async ({ page }, testInfo) => {
  await page.goto('/feed')
  const card = page.getByRole('article', { name: '实时条目 200' })
  const expand = card.getByRole('button', { name: '展开 实时条目 200' })
  await expand.focus()
  await page.keyboard.press('Enter')
  await expect(expand).toHaveAttribute('aria-expanded', 'true')

  if (testInfo.project.name === 'mobile') {
    const openOriginal = card.getByRole('link', { name: '打开 实时条目 200 原文' })
    const box = await openOriginal.boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44)
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
})
```

在现有收藏/历史路由段落补充隔离断言，确保 Quiet Studio 未扩散：

```ts
await page.goto('/saved')
await expect(page.getByRole('navigation', { name: '信息流进度' })).toBeVisible()
await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'collection')
await expect(page.locator('[data-card-visual="collection"]')).toHaveCount(1)
await expect(page.getByRole('banner')).not.toHaveAttribute('data-header-visual')
await expect(page.getByRole('button', { name: '更新信息流' })).toBeVisible()

await page.goto('/history')
await expect(page.getByRole('navigation', { name: '信息流进度' })).toBeVisible()
await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'collection')
await expect(page.locator('[data-card-visual="collection"]')).toHaveCount(1)
```

- [ ] **Step 4: 运行 release Playwright 并确认 GREEN**

Run:

```bash
npm --prefix frontend run build
npm --prefix frontend run e2e:release -- production-workbench.spec.ts
```

Expected: desktop、tablet、mobile 项目全部通过；Axe 无 serious/critical，页面无横向溢出，Agent 开关不改变 Feed scrollTop。

- [ ] **Step 5: 提交 Task 4**

```bash
git add frontend/e2e/production-workbench.spec.ts
git commit -m "test(ui): cover Quiet Studio Feed interactions"
```

---

### Task 5: 视觉合同、决策记录、完整门禁与 Docker 预览

**Files:**
- Modify: `UI_CONTRACT.md:16-21,40-65,81-91`
- Modify: `DECISION_LOG.md`
- Modify: `PLAN.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: Tasks 1–4 的最终行为与验证证据。
- Produces: D030 Quiet Studio 决策、更新后的唯一视觉真源、可追溯工作日志和 revision-locked Docker 预览。

- [ ] **Step 1: 更新 UI 唯一真源**

将 `UI_CONTRACT.md` 的 Feed 轨道条款替换为以下语义：

```markdown
- `/feed` uses the Quiet Studio variant: no progress rail or reserved rail gutter, an approximately 820 px centered card column, an 18 px semantic Feed-card radius, standard graphite content surfaces, thin semantic borders, and no persistent glow or heavy shadow. `/saved` and `/history` retain the compact right rail and collection cards.
- Quiet Studio card hover and press feedback uses the existing 120–220 ms motion tokens; inline expansion preserves the rendered ID-plus-offset anchor. Coarse-pointer actions remain fully visible and at least 44 px, and Reduced Motion makes displacement and expansion effectively immediate without hiding state.
- The `/feed` Agent toggle uses a rounded split-panel glyph with neutral hover/press feedback and a restrained accent selected state. Its `aria-expanded`, focus restoration, responsive panel placement, and scroll preservation remain authoritative.
```

在允许的 Feed layout values 中登记 820px 内容列、18px 圆角、34×32px Agent 控件、25px 头像和 19px 卡片内边距；规则只授权语义 token 或 Tailwind layout values，不授权业务原始颜色。

- [ ] **Step 2: 记录 D030 和交付状态**

在 `DECISION_LOG.md` 增加 D030：

```markdown
### D030 — Feed adopts the approved Quiet Studio variant
- Decision: Remove the Feed progress rail and its gutter; use the split-panel Agent glyph, centered Quiet Studio cards, route-scoped motion, and inline expansion. Keep collection routes unchanged.
- Rationale: User approved visual direction A and its interaction prototype; the result follows Apple-inspired hierarchy and restraint without copying platform chrome or applying glass to content.
- Compatibility: No API, query, permission, Worker, Remote MCP, data, or dependency changes.
```

在 `PLAN.md` 只更新交付状态并引用 `UI_CONTRACT.md` 和本设计规格，不复制视觉规则。

- [ ] **Step 3: 写入 WORKLOG**

追加一条包含以下证据的记录：TDD RED→GREEN、focused test 数量、release Playwright 三视口、Axe、build、完整 gate、Docker revision、浏览器控制台错误数和未修改的后端边界。

- [ ] **Step 4: 运行最终完整门禁**

Run:

```bash
./.venv/bin/python scripts/test_gate.py run --mode full
git diff --check
git status --short
```

Expected: full gate 22/22 PASS、`mapping_miss=false`、`git diff --check` 无输出；只有本任务预期文件处于修改状态。

- [ ] **Step 5: 提交合同与收尾记录**

```bash
git add UI_CONTRACT.md DECISION_LOG.md PLAN.md WORKLOG.md
git commit -m "docs(ui): adopt the Quiet Studio Feed contract"
git status --short
```

Expected: commit 成功，工作树无输出。

- [ ] **Step 6: 构建 revision-locked Docker 镜像**

在工作树根目录执行：

```bash
REVISION="$(git rev-parse --short=12 HEAD)"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker build -t "inteliscope-service:feed-quiet-${REVISION}" --build-arg INTELISCOPE_VERSION=1.6.0 --build-arg INTELISCOPE_BUILD_REVISION="${REVISION}" --build-arg INTELISCOPE_BUILT_AT="${BUILT_AT}" .
```

Expected: frontend build 与 production artifact check PASS，镜像标签包含当前提交号。

- [ ] **Step 7: 在主仓库挂载下替换 8080 API/Worker**

先记录上一步输出的 `REVISION` 和 `BUILT_AT`，然后在 `/Users/stealmac/Documents/Inteliscope/infohub-light` 使用同一值执行：

```bash
env INTELISCOPE_IMAGE="inteliscope-service:feed-quiet-${REVISION}" INTELISCOPE_BUILD_REVISION="${REVISION}" INTELISCOPE_BUILT_AT="${BUILT_AT}" HORIZON_WEB_PORT=8080 docker compose -f docker-compose.light.yml up -d --no-build --force-recreate --remove-orphans horizon-api horizon-worker
```

不得运行工作树的默认 light stack，也不得改变主仓库数据、`.env`、端口或 volume。

- [ ] **Step 8: 验证运行版本并人工检查**

Run:

```bash
curl -fsS http://127.0.0.1:8080/api/health/live
curl -fsS http://127.0.0.1:8080/api/health/ready
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/feed
docker inspect --format '{{.Name}}\t{{.Config.Image}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' horizon-light-api horizon-light-worker
```

Expected: live revision 等于当前 12 字符提交号；ready 的 database/worker 均为 ready；`/feed` 为 200；两个容器 healthy 且使用同一 `feed-quiet` 镜像。

在真实浏览器检查 `/feed`：无轨道与预留空白、双栏图标正确、卡片 3–5 张可舒适扫读、悬停/展开/Agent 开关可用、控制台 error 为 0。再检查 `/saved` 与 `/history`：搜索、更新按钮、collection 卡片和紧凑右轨仍存在。

---

## Final Verification Checklist

- [ ] `/feed` 顶栏仅有标题和 Quiet Studio Agent 开关。
- [ ] `/feed` 工具行显示 `N 条内容 · 最新在下`，不显示“全部” Chip。
- [ ] `/feed` 无进度轨和轨道留白；`/saved`、`/history` 仍有紧凑右轨。
- [ ] Quiet Studio 卡片、悬停、按压、原位展开和上下文确认态只影响 `/feed`。
- [ ] Agent 面板在 1440、1024、390 三视口保持原响应式语义和滚动位置。
- [ ] Reduced Motion、键盘焦点、触摸目标、Axe 和虚拟列表上限通过。
- [ ] UI contract、ESLint、TypeScript、Vitest、Vite build/artifact、release Playwright、Python/Compose/full gate 全部通过。
- [ ] Docker API/Worker 使用相同 revision-locked 镜像且 8080 `/feed` 可访问。
