import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { readBootstrapShellRightRail, writeBootstrapShellRightRail } from '../../app/bootstrapShell'
import { readSidebarPreference, writeSidebarPreference } from '../../app/sidebarPreference'
import {
  FEED_PREFERENCE_CHANGED_EVENT,
  readFeedPreference,
  writeFeedPreference,
} from '../feed/feedPreference'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import {
  actionToast,
  anchoredTooltipProps,
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Button,
  CalmSkeleton,
  Card,
  Drawer,
  Icons,
  LoadingReveal,
  PageHeader,
  Popover,
  Separator,
  Skeleton,
  StatusIndicator,
  ThemeModeToggle,
  Tooltip,
  TooltipTriggerButton,
} from '../../design-system'
import {
  readAgentContextDraft,
  sanitizeSourceUrl,
  updateAgentContextDraft,
  writeAgentContextDraft,
  type AgentContextDraftV4,
} from './agentContext'
import { OpenClawConversation } from '../openclaw/OpenClawConversation'
import { useOpenClawChat } from '../openclaw/useOpenClawChat'
import { HandoffComposer } from './HandoffComposer'
import { FeedInsightsPanel, type FeedInsightsMetric } from './FeedInsightsPanel'
import { AgentPanelSkeleton } from './WorkbenchLoadingState'
import { WorkbenchAgentContext, type WorkbenchAgentContextValue } from './workbenchAgentContext'
import { relativeTime } from '../feed/feedModel'
import { toWorkbenchCardModel, workbenchSourceLabels } from './workbenchModel'
import {
  applyQuickView,
  detectActiveQuickView,
  WORKBENCH_QUICK_VIEWS,
  type WorkbenchQuickViewId,
} from './workbenchQuickViews'
import {
  RIGHT_RAIL_DEFAULT_WIDTH,
  RIGHT_RAIL_MIN_WIDTH,
  canDockRightRail,
  clampRightRailWidth,
  maximumRightRailWidth,
  readRightRailWidth,
  writeRightRailWidth,
} from './rightRailPreference'
import { settingsSectionsForRole } from '../admin-heroui/settingsSections'

export type RightRailMode = 'closed' | 'agent'
export type InsightsSurfaceState = 'closed' | 'auto' | 'manual' | 'closing'
type AgentAttentionState = 'none' | 'running' | 'completed' | 'failed' | 'stopped'

type RefreshState = 'idle' | 'pending' | 'queued' | 'running' | 'partial' | 'failed' | 'succeeded' | 'blocked' | 'reload_failed'

type HeroWorkbenchShellProps = {
  api: ServiceApi
  user: User
  query: string
  onQueryChange: (value: string) => void
  onRefresh?: () => void
  onRetry?: () => void
  onLogout: () => void
  refreshState: RefreshState
  refreshMessage?: string
  refreshEventKey?: string
  children: ReactNode
}

const browseNavigation = [
  { id: 'feed', label: '信息流', href: '/feed', icon: Icons.Radio },
  { id: 'saved', label: '收藏', href: '/saved', icon: Icons.Star },
  { id: 'history', label: '历史', href: '/history', icon: Icons.History },
] as const

const managementNavigation = [
  { id: 'subscriptions', label: '订阅', href: '/subscriptions', icon: Icons.Bell },
  { id: 'agents', label: '助手连接', href: '/agents', icon: Icons.Bot },
  { id: 'users', label: '账户与成员', href: '/users', icon: Icons.Users },
  { id: 'settings', label: '设置', href: '/settings', icon: Icons.Settings },
] as const

const navigation = [...browseNavigation, ...managementNavigation] as const
const mobilePrimaryNavigation = navigation.filter((item) => ['feed', 'saved', 'subscriptions', 'agents'].includes(item.id))

const roleLabel = {
  owner: '所有者',
  admin: '管理员',
  member: '成员',
  viewer: '只读成员',
} as const

const agentAttentionLabel: Record<Exclude<AgentAttentionState, 'none'>, string> = {
  running: 'OpenClaw 正在处理',
  completed: 'OpenClaw 已完成，结果待查看',
  failed: 'OpenClaw 执行失败，打开 Agent 查看详情',
  stopped: 'OpenClaw 已停止',
}

function AgentAttentionBadge({ state }: { state: Exclude<AgentAttentionState, 'none'> }) {
  const presentation = state === 'running'
    ? { className: 'bg-accent text-accent-foreground', icon: <Icons.LoaderCircle size={10} className="animate-spin motion-reduce:animate-none" /> }
    : state === 'completed'
      ? { className: 'bg-surface text-success ring-1 ring-success/40', icon: <Icons.Check size={10} /> }
      : state === 'failed'
        ? { className: 'bg-surface text-danger ring-1 ring-danger/40', icon: <Icons.TriangleAlert size={10} /> }
        : { className: 'bg-surface text-warning ring-1 ring-warning/40', icon: <Icons.Square size={8} fill="currentColor" /> }
  return <span
    data-agent-attention={state}
    className={`absolute -bottom-1 -right-1 grid size-4 place-items-center rounded-[5px] border border-surface shadow-sm ${presentation.className}`}
    aria-hidden="true"
  >{presentation.icon}</span>
}

type CategorizedNavigationProps = {
  activeQuickView: WorkbenchQuickViewId | null
  quickViewsOpen: boolean
  onQuickViewsToggle: () => void
  onQuickView: (id: WorkbenchQuickViewId) => void
  onNavigate?: () => void
  role: User['role']
  settingsDirectory?: boolean
}

const sidebarItemBase = 'type-control mb-0.5 flex w-full items-center rounded-xl text-muted transition-colors duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none'
const sidebarPanelToggleClass = (open: boolean) => `inline-flex size-10 shrink-0 items-center justify-center rounded-[var(--inteliscope-radius-card)] transition-colors duration-[var(--inteliscope-motion-standard)] focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none ${open ? 'bg-accent/15 text-accent hover:bg-accent/20 hover:text-accent' : 'text-muted hover:bg-default hover:text-foreground'}`

function SidebarNavItem({
  label,
  leading,
  href,
  end,
  selected = false,
  compact = false,
  onActivate,
}: {
  label: string
  leading: ReactNode
  href?: string
  end?: boolean
  selected?: boolean
  compact?: boolean
  onActivate?: () => void
}) {
  const itemClass = (active: boolean) => `${sidebarItemBase} ${compact ? 'min-h-11 justify-center px-0' : 'min-h-10 gap-3 px-3 text-left'}${active ? ' bg-default text-foreground' : ''}`
  const content = <>{leading}{!compact && <span>{label}</span>}</>
  if (href) {
    if (compact) return <Tooltip delay={450}>
      <Tooltip.Trigger<'a'>
        aria-label={label}
        render={(triggerProps) => <NavLink
          {...triggerProps}
          to={href}
          end={end}
          data-sidebar-nav-item="collapsed"
          onClick={onActivate}
          className={({ isActive }) => `${triggerProps.className ?? ''} ${itemClass(isActive)}`}
        >{content}</NavLink>}
      />
      <Tooltip.Content {...anchoredTooltipProps}>{label}</Tooltip.Content>
    </Tooltip>
    return <NavLink
      to={href}
      end={end}
      aria-label={label}
      data-sidebar-nav-item="expanded"
      onClick={onActivate}
      className={({ isActive }) => itemClass(isActive)}
    >{content}</NavLink>
  }
  const button = <button
    type="button"
    aria-label={label}
    aria-pressed={selected}
    data-sidebar-nav-item={compact ? 'collapsed' : 'expanded'}
    className={itemClass(selected)}
    onClick={onActivate}
  >{content}</button>
  if (!compact) return button
  return <Tooltip delay={450}>
    <Tooltip.Trigger render={(triggerProps) => <button {...triggerProps} type="button" aria-label={label} aria-pressed={selected} data-sidebar-nav-item="collapsed" className={`${triggerProps.className ?? ''} ${itemClass(selected)}`} onClick={onActivate}>{content}</button>} />
    <Tooltip.Content {...anchoredTooltipProps}>{label}</Tooltip.Content>
  </Tooltip>
}

function SettingsSidebarNavigationItem({
  compact,
  role,
  onNavigate,
}: {
  compact: boolean
  role: User['role']
  onNavigate?: () => void
}) {
  const location = useLocation()
  const triggerRef = useRef<HTMLAnchorElement>(null)
  const surfaceRef = useRef<HTMLDivElement>(null)
  const openTimerRef = useRef<number | null>(null)
  const closeTimerRef = useRef<number | null>(null)
  const suppressFocusOpenRef = useRef(false)
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 80, top: 12 })
  const sections = useMemo(() => settingsSectionsForRole(role), [role])

  const itemClass = `${sidebarItemBase} ${compact ? 'min-h-11 justify-center px-0' : 'min-h-10 gap-3 px-3 text-left'}${location.pathname === '/settings' ? ' bg-default text-foreground' : ''}`

  const clearTimers = useCallback(() => {
    if (openTimerRef.current !== null) window.clearTimeout(openTimerRef.current)
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    openTimerRef.current = null
    closeTimerRef.current = null
  }, [])

  function scheduleOpen() {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    closeTimerRef.current = null
    if (open || openTimerRef.current !== null) return
    openTimerRef.current = window.setTimeout(() => {
      openTimerRef.current = null
      setOpen(true)
    }, 150)
  }

  function openImmediately() {
    if (suppressFocusOpenRef.current) return
    clearTimers()
    setOpen(true)
  }

  function scheduleClose() {
    if (openTimerRef.current !== null) window.clearTimeout(openTimerRef.current)
    openTimerRef.current = null
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null
      setOpen(false)
    }, 150)
  }

  const closeDirectory = useCallback((returnFocus = false) => {
    clearTimers()
    setOpen(false)
    if (!returnFocus) return
    suppressFocusOpenRef.current = true
    window.requestAnimationFrame(() => {
      triggerRef.current?.focus()
      window.requestAnimationFrame(() => {
        suppressFocusOpenRef.current = false
      })
    })
  }, [clearTimers])

  useLayoutEffect(() => {
    if (!open) return
    const updatePosition = () => {
      const trigger = triggerRef.current
      if (!trigger) return
      const rect = trigger.getBoundingClientRect()
      const top = Math.min(Math.max(8, rect.top), Math.max(8, window.innerHeight - 300))
      setPosition({ left: rect.right + 8, top })
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null
      if (triggerRef.current?.contains(target) || surfaceRef.current?.contains(target)) return
      closeDirectory(true)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeDirectory(true)
    }
    document.addEventListener('pointerdown', handlePointerDown, true)
    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true)
      document.removeEventListener('keydown', handleKeyDown, true)
    }
  }, [closeDirectory, open])

  useEffect(() => () => clearTimers(), [clearTimers])

  const surface = open && typeof document !== 'undefined'
    ? createPortal(
      <div
        ref={surfaceRef}
        role="dialog"
        aria-label="设置目录"
        aria-modal="false"
        data-settings-directory
        style={{ left: position.left, top: position.top }}
        className="fixed z-[70] grid w-52 gap-0.5 rounded-2xl border border-separator bg-surface p-2 shadow-xl"
        onPointerEnter={clearTimers}
        onPointerLeave={scheduleClose}
        onFocus={clearTimers}
        onBlur={(event) => {
          const next = event.relatedTarget as Node | null
          if (triggerRef.current?.contains(next) || event.currentTarget.contains(next)) return
          scheduleClose()
        }}
      >
        <p className="type-label px-3 pb-1 pt-1 text-muted">设置目录</p>
        {sections.map((section) => <NavLink
          key={section.id}
          to={`/settings#${section.id}`}
          aria-current={location.hash === `#${section.id}` ? 'location' : undefined}
          className="type-control min-h-9 rounded-xl px-3 py-2 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus aria-[current=location]:bg-accent/10 aria-[current=location]:text-accent"
          onClick={() => {
            closeDirectory()
            onNavigate?.()
          }}
        >{section.label}</NavLink>)}
      </div>,
      document.body,
    )
    : null

  return <>
    <NavLink
      ref={triggerRef}
      to="/settings"
      aria-label="设置"
      aria-haspopup="dialog"
      aria-expanded={open}
      data-sidebar-nav-item={compact ? 'collapsed' : 'expanded'}
      className={itemClass}
      onPointerEnter={scheduleOpen}
      onPointerLeave={scheduleClose}
      onFocus={openImmediately}
      onBlur={(event) => {
        const next = event.relatedTarget as Node | null
        if (surfaceRef.current?.contains(next)) return
        scheduleClose()
      }}
      onClick={() => {
        closeDirectory()
        onNavigate?.()
      }}
    >
      <Icons.Settings size={compact ? 18 : 17} aria-hidden="true" />
      {!compact && <span>设置</span>}
    </NavLink>
    {surface}
  </>
}

function ExpandedRoute({ href, label, icon: Icon, onNavigate }: typeof navigation[number] & { onNavigate?: () => void }) {
  return <SidebarNavItem
    href={href}
    end={href === '/feed'}
    label={label}
    leading={<Icon size={17} aria-hidden="true" />}
    onActivate={onNavigate}
  />
}

function CategorizedNavigation({ activeQuickView, quickViewsOpen, onQuickViewsToggle, onQuickView, onNavigate, role, settingsDirectory = true }: CategorizedNavigationProps) {
  return <nav aria-label="分类导航内容" className="quiet-scroll-region min-h-0 overflow-x-hidden overflow-y-auto px-2 pb-3">
    <p className="type-label px-3 pb-1 pt-2 text-muted">浏览</p>
    {browseNavigation.map((item) => <ExpandedRoute key={item.href} {...item} onNavigate={onNavigate} />)}

    <Button
      size="sm"
      variant="ghost"
      className="type-label mt-3 w-full justify-between px-3 text-muted"
      aria-expanded={quickViewsOpen}
      onPress={onQuickViewsToggle}
    >常用视图<Icons.ChevronDown size={14} className={`transition-transform ${quickViewsOpen ? '' : '-rotate-90'}`} /></Button>
    {quickViewsOpen && <div className="grid gap-0.5">
      {WORKBENCH_QUICK_VIEWS.map((view) => <SidebarNavItem
        key={view.id}
        label={view.label}
        selected={activeQuickView === view.id}
        leading={<span className={`size-1.5 rounded-full ${activeQuickView === view.id ? 'bg-accent' : 'bg-muted/35'}`} aria-hidden="true" />}
        onActivate={() => onQuickView(view.id)}
      />)}
    </div>}

    <p className="type-label mt-3 px-3 pb-1 pt-2 text-muted">管理</p>
    {managementNavigation.map((item) => item.id === 'settings' && settingsDirectory
      ? <SettingsSidebarNavigationItem key={item.href} compact={false} role={role} onNavigate={onNavigate} />
      : <ExpandedRoute key={item.href} {...item} onNavigate={onNavigate} />)}
  </nav>
}

function initialMobile() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(max-width: 767px)').matches
    : false
}

function initialExtraWideDesktop() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(min-width: 1360px)').matches
    : false
}

function initialRightRailMode(userId: string): RightRailMode {
  if (typeof window === 'undefined') return 'closed'
  const sidebarWidth = initialExtraWideDesktop() && readSidebarPreference(userId) === 'expanded' ? 232 : 72
  return canDockRightRail(window.innerWidth, sidebarWidth)
    ? readBootstrapShellRightRail(userId)
    : 'closed'
}

const insightsDismissedKey = (userId: string) => `inteliscope.ui.insights-dismissed.v1:${userId}`
export const FLOATING_INSIGHTS_REQUIRED_GUTTER = 376
export const FLOATING_INSIGHTS_WIDTH = 352
export const FLOATING_INSIGHTS_INSET = 12
export const FLOATING_INSIGHTS_GAP = 12
const deliberateLayoutMotionMs = 220
const interactivePointerTarget = [
  'a',
  'button',
  'input',
  'textarea',
  'select',
  'label',
  'summary',
  'audio[controls]',
  'video[controls]',
  '[role="button"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="tab"]',
  '[role="checkbox"]',
  '[role="radio"]',
  '[role="switch"]',
  '[contenteditable]:not([contenteditable="false"])',
].join(',')

function insightsExitMotionMs(): number {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 1
    : deliberateLayoutMotionMs
}

export function canFloatFeedInsights(mainRight: number, readingRight: number): boolean {
  return Number.isFinite(mainRight)
    && Number.isFinite(readingRight)
    && mainRight - readingRight >= FLOATING_INSIGHTS_REQUIRED_GUTTER
}

type HorizontalBounds = Pick<DOMRectReadOnly, 'left' | 'right'>

export type FeedInsightsLayout = {
  panelLeft: number
  readingShift: number
  obstructsFeed: boolean
}

export function calculateFeedInsightsLayout(
  main: HorizontalBounds,
  reading: HorizontalBounds,
  shiftReading: boolean,
): FeedInsightsLayout {
  const values = [main.left, main.right, reading.left, reading.right]
  if (values.some((value) => !Number.isFinite(value)) || main.right <= main.left || reading.right <= reading.left) {
    return { panelLeft: 0, readingShift: 0, obstructsFeed: false }
  }

  const panelLeft = main.right - FLOATING_INSIGHTS_INSET - FLOATING_INSIGHTS_WIDTH
  const requiredShift = shiftReading
    ? Math.max(0, reading.right + FLOATING_INSIGHTS_GAP - panelLeft)
    : 0
  const availableLeftGutter = Math.max(0, reading.left - (main.left + FLOATING_INSIGHTS_INSET))
  const readingShift = requiredShift > 0 ? -Math.min(requiredShift, availableLeftGutter) : 0
  const shiftedReading = {
    left: reading.left + readingShift,
    right: reading.right + readingShift,
  }
  const obstructsFeed = shiftedReading.left < panelLeft + FLOATING_INSIGHTS_WIDTH
    && shiftedReading.right > panelLeft

  return { panelLeft, readingShift, obstructsFeed }
}

type RectBounds = Pick<DOMRectReadOnly, 'left' | 'right' | 'top' | 'bottom'>

export function rectanglesOverlap(first: RectBounds, second: RectBounds): boolean {
  return first.left < second.right
    && first.right > second.left
    && first.top < second.bottom
    && first.bottom > second.top
}

function AgentPanelContent({
  open,
  onClose,
  closeDisabled,
  chat,
  configLoading,
  value,
  api,
  userId,
}: {
  open: boolean
  onClose: () => void
  closeDisabled: boolean
  chat: ReturnType<typeof useOpenClawChat>
  configLoading: boolean
  value: WorkbenchAgentContextValue
  api: ServiceApi
  userId: string
}) {
  const feedItems = useMemo(
    () => value.draft.items.filter((item) => item.resourceType !== 'job'),
    [value.draft.items],
  )
  const itemQueries = useQueries({
    queries: feedItems.map((item) => ({
      queryKey: queryKeys.feedItem(userId, item.articleId),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.feedItem(item.articleId, signal),
      enabled: open,
      retry: false,
    })),
  })
  const itemQueryById = useMemo(
    () => new Map(feedItems.map((item, index) => [item.articleId, itemQueries[index]])),
    [feedItems, itemQueries],
  )

  useEffect(() => {
    if (!open) return
    let changed = false
    const items = value.draft.items.map((item) => {
      if (item.resourceType === 'job') return item
      const query = itemQueryById.get(item.articleId)
      if (!query?.data) return item
      const card = toWorkbenchCardModel(query.data)
      const sourceUrl = item.sourceUrl || sanitizeSourceUrl(card.url)
      const title = item.title && item.title !== item.articleId ? item.title : card.primaryText
      const sourceName = item.sourceName || card.source
      if (sourceUrl === item.sourceUrl && title === item.title && sourceName === item.sourceName) return item
      changed = true
      return { ...item, sourceUrl, title, sourceName }
    })
    if (changed) value.restoreComposer(value.draft.question, items)
  }, [itemQueries, itemQueryById, open, value])
  const gatewayTone = chat.status === 'error'
    ? 'danger'
    : chat.isRunning || chat.status === 'connecting' || chat.status === 'reconnecting'
      ? 'accent'
      : chat.status === 'connected'
        ? 'success'
        : 'neutral'
  const headerStatusLabel = chat.isRunning
    ? '正在处理'
    : chat.status === 'reconnecting'
      ? `重连中${chat.reconnectAttempt > 0 ? ` ${chat.reconnectAttempt}` : ''}`
      : chat.status === 'connecting'
        ? '连接中'
        : chat.status === 'error'
          ? '连接失败'
          : chat.status === 'disabled'
            ? '未配置'
            : chat.status === 'idle'
              ? '未连接'
              : chat.toolsStatus === 'missing'
                ? '工具未发现'
                : chat.toolsStatus === 'unknown'
                  ? '检查工具'
                  : '已连接'
  const headerTone = chat.status === 'error' || chat.toolsStatus === 'missing'
    ? 'danger'
    : gatewayTone
  return <>
    <header className="flex h-[52px] min-w-0 items-center gap-2 overflow-hidden border-b border-separator px-4">
      <Icons.Sparkles className="shrink-0" size={17} aria-hidden="true" />
      <strong className="min-w-0 flex-1 truncate">OpenClaw 对话</strong>
      <div data-agent-header-status className="flex shrink-0 items-center gap-2 self-center">
        <LoadingReveal
          loading={configLoading}
          label="正在检查 Agent 连接"
          name="agent-status"
          className="h-6 min-w-14 shrink-0 [&_[data-content-layer]]:items-center [&_[data-content-layer]]:justify-center"
          skeleton={<CalmSkeleton className="h-5 w-14 rounded-lg" />}
        ><StatusIndicator
          className="self-center"
          label={headerStatusLabel}
          tone={headerTone}
          icon={chat.isRunning || chat.status === 'connecting' || chat.status === 'reconnecting'
            ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            : undefined}
        /></LoadingReveal>
      </div>
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭 Agent 面板" isDisabled={closeDisabled} onPress={onClose}>
        <Icons.X size={17} aria-hidden="true" />
      </Button>
    </header>
    {open && <LoadingReveal
      loading={configLoading}
      label="正在读取 Agent 面板"
      name="agent-panel"
      className="row-span-2 min-h-0"
      skeleton={<AgentPanelSkeleton />}
    >
    {chat.status === 'disabled' ? <>
      <div className="min-h-0 flex-1 overflow-hidden p-3" data-testid="agent-scroll-region">
        <div className="type-meta mb-2 flex justify-between text-muted"><span>已选上下文</span><span>{value.draft.items.length} / 8</span></div>
        {!value.draft.items.length && <Card variant="transparent" className="p-3">
          <Card.Description>从信息卡片加入内容，再生成交给本地 OpenClaw 的确定性提示词。</Card.Description>
        </Card>}
        <div className="grid gap-1">
          {value.draft.items.map((item) => {
            const id = item.articleId
            if (item.resourceType === 'job') {
              const label = item.sourceName ? `${item.sourceName} · ${item.title}` : item.title
              return <Card key={id} data-agent-context-item data-context-resource="job" variant="secondary" className="h-9 min-w-0 flex-row items-center gap-2 px-2 py-1">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-default text-accent"><Icons.ScrollText size={14} aria-hidden="true" /></span>
                <span className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden whitespace-nowrap">
                  <span className="type-meta shrink-0 text-muted">运行记录{item.statusLabel ? ` · ${item.statusLabel}` : ''}</span>
                  <span className="text-muted/60" aria-hidden="true">—</span>
                  <span className="type-control min-w-0 flex-1 truncate" title={item.detail || label}>{label}</span>
                </span>
                <Button size="sm" variant="ghost" isIconOnly className="size-7 shrink-0" aria-label={`移除 ${label}`} onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
              </Card>
            }
            const query = itemQueryById.get(id)
            const hasReadableDraft = Boolean(item.title && item.title !== id)
            if ((!query || query.isPending) && !hasReadableDraft) return <Card key={id} data-agent-context-item variant="secondary" className="h-9 min-w-0 flex-row items-center gap-2 px-2 py-1">
              <Skeleton className="size-6 shrink-0 rounded-full" />
              <span role="status" className="type-meta min-w-0 flex-1 text-muted">正在读取内容</span>
              <Button size="sm" variant="ghost" isIconOnly className="size-7 shrink-0" aria-label="移除正在加载的内容" onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
            </Card>
            if ((!query || query.isError || !query.data) && !hasReadableDraft) return <Card key={id} data-agent-context-item variant="secondary" className="h-9 min-w-0 flex-row items-center gap-2 px-2 py-1">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-default text-muted"><Icons.FileWarning size={14} aria-hidden="true" /></span>
              <span className="type-control min-w-0 flex-1 truncate">内容已失效</span>
              <Button size="sm" variant="ghost" isIconOnly className="size-7 shrink-0" aria-label="移除失效内容" onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
            </Card>
            const card = query?.data ? toWorkbenchCardModel(query.data) : undefined
            const sourceLabels = card ? workbenchSourceLabels(card, true) : item.sourceName ? [item.sourceName] : []
            const primaryText = card?.primaryText || item.title
            const publishedAt = card?.publishedAt || item.publishedAt
            const removeLabel = card?.authorLabel || card?.sourceLabel || item.sourceName || primaryText || '所选内容'
            const avatarLabel = card?.source || item.sourceName || primaryText
            return <Card key={id} data-agent-context-item variant="secondary" className="h-9 min-w-0 flex-row items-center gap-2 px-2 py-1">
              <AvatarRoot className="size-6 shrink-0">
                {card?.sourceAvatar && <AvatarImage src={card.sourceAvatar} alt={card.source} />}
                <AvatarFallback>{avatarLabel.slice(0, 1).toUpperCase()}</AvatarFallback>
              </AvatarRoot>
              <span className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden whitespace-nowrap">
                <span className="type-meta flex min-w-0 shrink-0 items-center gap-1.5 text-muted">
                  {sourceLabels.map((label, labelIndex) => <Fragment key={label}>
                    {labelIndex > 0 && <span aria-hidden="true">·</span>}
                    <span className="max-w-20 truncate">{label}</span>
                  </Fragment>)}
                  {publishedAt && <><span aria-hidden="true">·</span><span className="shrink-0">{relativeTime(publishedAt)}</span></>}
                </span>
                <span className="text-muted/60" aria-hidden="true">—</span>
                <span className="type-control min-w-0 flex-1 truncate">{primaryText}</span>
              </span>
              <Button size="sm" variant="ghost" isIconOnly className="size-7 shrink-0" aria-label={`移除 ${removeLabel}`} onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
            </Card>
          })}
        </div>
      </div>
      <HandoffComposer value={value} />
    </> : <OpenClawConversation chat={chat} value={value} />}
    </LoadingReveal>}
  </>
}

export function HeroWorkbenchShell(props: HeroWorkbenchShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const contentRoute = ['/feed', '/saved', '/history'].includes(location.pathname)
  const feedRoute = location.pathname === '/feed'
  const agentRoute = contentRoute || location.pathname === '/subscriptions'
  const pageTitle = location.pathname.endsWith('/subscriptions') ? '订阅与来源' : location.pathname.endsWith('/agents') ? '助手连接' : location.pathname.endsWith('/users') ? '账户与成员' : location.pathname.endsWith('/settings') ? '设置' : location.pathname.endsWith('/manual') ? '操作手册' : location.pathname.endsWith('/changelog') ? '更新日志' : location.pathname.endsWith('/saved') ? '收藏' : location.pathname.endsWith('/history') ? '历史' : '信息流'
  const shellRef = useRef<HTMLDivElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const insightsRef = useRef<HTMLElement>(null)
  const agentToggleRef = useRef<HTMLButtonElement>(null)
  const insightsToggleRef = useRef<HTMLButtonElement>(null)
  const tabletNavToggleRef = useRef<HTMLDivElement>(null)
  const [extraWideDesktop, setExtraWideDesktop] = useState(initialExtraWideDesktop)
  const [mobile, setMobile] = useState(initialMobile)
  const [viewportWidth, setViewportWidth] = useState(() => typeof window === 'undefined' ? 1440 : window.innerWidth)
  const [rightRailMode, setRightRailMode] = useState<RightRailMode>(() => initialRightRailMode(props.user.id))
  const [agentAttention, setAgentAttention] = useState<AgentAttentionState>('none')
  const notifiedAgentRunRef = useRef<string | null>(null)
  const [rightRailAnimated, setRightRailAnimated] = useState(false)
  const [closingFixedRail, setClosingFixedRail] = useState(false)
  const closingFixedRailTimer = useRef<number | undefined>(undefined)
  const insightsClosingTimer = useRef<number | undefined>(undefined)
  const insightsOpenedAlongsideAgentRef = useRef(false)
  const [insightsSurface, setInsightsSurface] = useState<InsightsSurfaceState>('closed')
  const [insightsCanFloat, setInsightsCanFloat] = useState(false)
  const [insightsObstructsFeed, setInsightsObstructsFeed] = useState(false)
  const [feedInsightsLayout, setFeedInsightsLayout] = useState<FeedInsightsLayout | null>(null)
  const [resizingRail, setResizingRail] = useState(false)
  const [tabletNavOpen, setTabletNavOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [documentationMenuOpen, setDocumentationMenuOpen] = useState(false)
  const [mobileMoreRoute, setMobileMoreRoute] = useState<string | null>(null)
  const mobileMoreOpen = mobileMoreRoute === location.pathname
  const setMobileMoreOpen = useCallback((open: boolean) => {
    setMobileMoreRoute(open ? location.pathname : null)
  }, [location.pathname])
  const [quickViewsOpen, setQuickViewsOpen] = useState(true)
  const [sidebarState, setSidebarState] = useState(() => ({ userId: props.user.id, value: readSidebarPreference(props.user.id) }))
  const [rightRailWidthState, setRightRailWidthState] = useState(() => ({ userId: props.user.id, value: readRightRailWidth(props.user.id) }))
  const [feedPreferenceState, setFeedPreferenceState] = useState(() => ({ userId: props.user.id, value: readFeedPreference(props.user.id) }))
  const [draft, setDraft] = useState(() => readAgentContextDraft(props.user.id))
  const shownRefreshEvents = useRef(new Set<string>())
  const delegations = useQuery({ queryKey: queryKeys.agentDelegations(props.user.id), queryFn: ({ signal }) => props.api.agentDelegations(signal), retry: false, enabled: agentRoute })
  const insightsFeed = useQuery({
    queryKey: queryKeys.feed(props.user.id, { hideDismissed: false, unreadFirst: false }),
    queryFn: ({ signal }) => props.api.latestFeed(signal),
    enabled: feedRoute,
    staleTime: queryStaleTime.feed,
  })
  const openclawChat = useOpenClawChat({
    enabled: agentRoute && Boolean(delegations.data?.openclaw_chat?.enabled),
    userId: props.user.id,
    defaultGatewayUrl: delegations.data?.openclaw_chat?.default_gateway_url ?? 'ws://127.0.0.1:18789',
  })
  const refreshing = props.refreshState === 'pending' || props.refreshState === 'queued' || props.refreshState === 'running'
  const sidebarPreference = sidebarState.userId === props.user.id ? sidebarState.value : readSidebarPreference(props.user.id)
  const feedPreference = feedPreferenceState.userId === props.user.id ? feedPreferenceState.value : readFeedPreference(props.user.id)
  const activeQuickView = detectActiveQuickView(feedPreference)
  const sidebarExpanded = extraWideDesktop && sidebarPreference === 'expanded'
  const sidebarWidth = sidebarExpanded ? 232 : 72
  const desktopSidebarColumn = sidebarExpanded ? 'min-[1360px]:grid-cols-[232px_minmax(0,1fr)]' : 'min-[1360px]:grid-cols-[72px_minmax(0,1fr)]'
  const visibleRightRailMode: RightRailMode = agentRoute ? rightRailMode : 'closed'
  const visibleAgentAttention: AgentAttentionState = visibleRightRailMode === 'closed' && openclawChat.isRunning
    ? 'running'
    : agentAttention
  const dockCapable = agentRoute && canDockRightRail(viewportWidth, sidebarWidth)
  const fixedRightRail = dockCapable && visibleRightRailMode === 'agent'
  const fixedRailPresent = dockCapable && (fixedRightRail || closingFixedRail)
  const insightsOpen = feedRoute && (insightsSurface === 'auto' || insightsSurface === 'manual')
  const insightsPresent = feedRoute && insightsSurface !== 'closed'
  const insightsClosing = insightsSurface === 'closing'
  const hasInsightsData = Boolean(insightsFeed.data?.items.length)
  const storedRightRailWidth = rightRailWidthState.userId === props.user.id ? rightRailWidthState.value : readRightRailWidth(props.user.id)
  const rightRailWidth = clampRightRailWidth(storedRightRailWidth, viewportWidth, sidebarWidth)
  const rightRailWidthRef = useRef(rightRailWidth)
  const desktopGridColumns = `min-[1200px]:grid-cols-[72px_minmax(0,1fr)] ${desktopSidebarColumn}`
  const desktopGridStyle = viewportWidth >= 768
    ? {
        gridTemplateColumns: fixedRailPresent
          ? `${sidebarWidth}px minmax(640px, 1fr) ${fixedRightRail ? rightRailWidth : 0}px`
          : dockCapable
            ? `${sidebarWidth}px minmax(640px, 1fr) 0px`
          : `${sidebarWidth}px minmax(0, 1fr)`,
      } as CSSProperties
    : undefined

  function toggleSidebar() {
    const value = sidebarExpanded ? 'collapsed' : 'expanded'
    setRightRailAnimated(true)
    writeSidebarPreference(props.user.id, value)
    setSidebarState({ userId: props.user.id, value })
  }

  function selectQuickView(id: WorkbenchQuickViewId) {
    const next = applyQuickView(feedPreference, id)
    writeFeedPreference(props.user.id, next)
    setFeedPreferenceState({ userId: props.user.id, value: next })
    setTabletNavOpen(false)
    navigate('/feed')
  }

  function handleInsightsMetric(metric: FeedInsightsMetric) {
    if (metric === 'subscriptions' || metric === 'sources' || metric === 'recent_runs') {
      const tab = metric === 'sources' ? 'library' : metric === 'recent_runs' ? 'jobs' : 'subscriptions'
      navigate(`/subscriptions?tab=${tab}`)
      return
    }
    if (metric === 'saved') {
      navigate('/saved')
      return
    }
    if (metric === 'unhealthy') {
      navigate('/subscriptions')
      return
    }
    if (metric === 'today') {
      selectQuickView('today')
      return
    }
    const next = { ...feedPreference, unreadFirst: true }
    writeFeedPreference(props.user.id, next)
    setFeedPreferenceState({ userId: props.user.id, value: next })
    navigate('/feed')
  }

  function handleInsightsChannel(channel: string) {
    const next = { ...feedPreference, channel }
    writeFeedPreference(props.user.id, next)
    setFeedPreferenceState({ userId: props.user.id, value: next })
    navigate('/feed')
  }

  const persistDraft = useCallback((next: AgentContextDraftV4) => {
    setDraft(writeAgentContextDraft(props.user.id, next))
  }, [props.user.id])

  const suppressAutomaticInsights = useCallback(() => {
    try { window.sessionStorage.setItem(insightsDismissedKey(props.user.id), '1') } catch { /* Session preference is best-effort. */ }
  }, [props.user.id])

  const cancelFixedRailClose = useCallback(() => {
    window.clearTimeout(closingFixedRailTimer.current)
    closingFixedRailTimer.current = undefined
    setClosingFixedRail(false)
  }, [])

  const finishFixedRailClose = useCallback(() => {
    window.clearTimeout(closingFixedRailTimer.current)
    if (!dockCapable) {
      setClosingFixedRail(false)
      return
    }
    setClosingFixedRail(true)
    closingFixedRailTimer.current = window.setTimeout(() => {
      closingFixedRailTimer.current = undefined
      setClosingFixedRail(false)
    }, deliberateLayoutMotionMs)
  }, [dockCapable])

  const cancelInsightsClose = useCallback(() => {
    window.clearTimeout(insightsClosingTimer.current)
    insightsClosingTimer.current = undefined
  }, [])

  const completeInsightsClose = useCallback(() => {
    cancelInsightsClose()
    insightsOpenedAlongsideAgentRef.current = false
    setInsightsSurface((current) => current === 'closing' ? 'closed' : current)
  }, [cancelInsightsClose])

  const dismissInsightsImmediately = useCallback(() => {
    cancelInsightsClose()
    insightsOpenedAlongsideAgentRef.current = false
    setInsightsSurface('closed')
  }, [cancelInsightsClose])

  const closeInsights = useCallback((restoreFocus = true) => {
    if (insightsSurface === 'closed' || insightsSurface === 'closing') return
    suppressAutomaticInsights()
    cancelInsightsClose()
    insightsOpenedAlongsideAgentRef.current = false
    setInsightsSurface('closing')
    insightsClosingTimer.current = window.setTimeout(completeInsightsClose, insightsExitMotionMs())
    if (restoreFocus) window.requestAnimationFrame(() => insightsToggleRef.current?.focus())
  }, [cancelInsightsClose, completeInsightsClose, insightsSurface, suppressAutomaticInsights])

  const openComposer = useCallback(() => {
    if (!dockCapable) {
      closeInsights(false)
    }
    insightsOpenedAlongsideAgentRef.current = false
    cancelFixedRailClose()
    setRightRailAnimated(true)
    setAgentAttention('none')
    setRightRailMode('agent')
    writeBootstrapShellRightRail(props.user.id, 'agent', rightRailWidth)
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(
        '[aria-label="发送给 OpenClaw 的问题"], [aria-label="交给 OpenClaw 的问题"]',
      )?.focus()
    })
  }, [cancelFixedRailClose, closeInsights, dockCapable, props.user.id, rightRailWidth])

  const agentValue = useMemo<WorkbenchAgentContextValue>(() => ({
    draft,
    toggleItem: (item) => persistDraft(updateAgentContextDraft(draft, item)),
    removeItem: (id) => persistDraft({ ...draft, items: draft.items.filter((value) => value.articleId !== id) }),
    openComposer,
    setQuestion: (question) => persistDraft({ ...draft, question }),
    clearComposer: () => persistDraft({ ...draft, question: '', items: [] }),
    restoreComposer: (question, items) => persistDraft({ ...draft, question, items }),
  }), [draft, openComposer, persistDraft])

  const closeRightRail = useCallback(() => {
    if (mobile && openclawChat.isRunning) return
    setRightRailAnimated(true)
    finishFixedRailClose()
    setRightRailMode('closed')
    writeBootstrapShellRightRail(props.user.id, 'closed', rightRailWidth)
    window.requestAnimationFrame(() => agentToggleRef.current?.focus())
  }, [finishFixedRailClose, mobile, openclawChat.isRunning, props.user.id, rightRailWidth])

  const toggleAgentRail = useCallback(() => {
    if (mobile && openclawChat.isRunning) return
    if (visibleRightRailMode !== 'agent' && !dockCapable) {
      closeInsights(false)
    }
    const nextMode = visibleRightRailMode === 'agent' ? 'closed' : 'agent'
    setRightRailAnimated(true)
    if (nextMode === 'agent') {
      insightsOpenedAlongsideAgentRef.current = false
      cancelFixedRailClose()
      setAgentAttention('none')
    }
    else finishFixedRailClose()
    setRightRailMode(nextMode)
    writeBootstrapShellRightRail(props.user.id, nextMode, rightRailWidth)
  }, [cancelFixedRailClose, closeInsights, dockCapable, finishFixedRailClose, mobile, openclawChat.isRunning, props.user.id, rightRailWidth, visibleRightRailMode])

  const toggleInsights = useCallback(() => {
    if (mobile && openclawChat.isRunning) return
    if (insightsClosing) {
      cancelInsightsClose()
      insightsOpenedAlongsideAgentRef.current = visibleRightRailMode === 'agent' && dockCapable
      setInsightsSurface('manual')
      return
    }
    if (insightsOpen) {
      closeInsights(false)
      return
    }
    if (!dockCapable) setRightRailMode('closed')
    insightsOpenedAlongsideAgentRef.current = visibleRightRailMode === 'agent' && dockCapable
    setInsightsSurface('manual')
  }, [cancelInsightsClose, closeInsights, dockCapable, insightsClosing, insightsOpen, mobile, openclawChat.isRunning, visibleRightRailMode])

  const handleIneffectivePrimaryPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!feedRoute || !insightsOpen || !insightsObstructsFeed || event.button !== 0 || event.defaultPrevented) return
    const target = event.target
    if (!(target instanceof Element) || insightsRef.current?.contains(target)) return
    if (target.closest(interactivePointerTarget)) return
    closeInsights(false)
  }, [closeInsights, feedRoute, insightsObstructsFeed, insightsOpen])

  const changeTabletNavigation = useCallback((open: boolean) => {
    setTabletNavOpen(open)
    if (!open) window.requestAnimationFrame(() => tabletNavToggleRef.current?.focus())
  }, [])

  useEffect(() => {
    const syncPreference = (event: Event) => {
      const detail = (event as CustomEvent<{ userId?: string }>).detail
      if (detail?.userId !== props.user.id) return
      setFeedPreferenceState({ userId: props.user.id, value: readFeedPreference(props.user.id) })
    }
    window.addEventListener(FEED_PREFERENCE_CHANGED_EVENT, syncPreference)
    return () => window.removeEventListener(FEED_PREFERENCE_CHANGED_EVENT, syncPreference)
  }, [props.user.id])

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const extraWideMedia = window.matchMedia('(min-width: 1360px)')
    const mobileMedia = window.matchMedia('(max-width: 767px)')
    const changeExtraWide = (event: MediaQueryListEvent) => {
      setRightRailAnimated(false)
      setExtraWideDesktop(event.matches)
      if (event.matches) setTabletNavOpen(false)
    }
    const changeMobile = (event: MediaQueryListEvent) => {
      setRightRailAnimated(false)
      setMobile(event.matches)
    }
    const changeViewport = () => {
      setRightRailAnimated(false)
      setViewportWidth(window.innerWidth)
    }
    extraWideMedia.addEventListener('change', changeExtraWide)
    mobileMedia.addEventListener('change', changeMobile)
    window.addEventListener('resize', changeViewport)
    return () => {
      extraWideMedia.removeEventListener('change', changeExtraWide)
      mobileMedia.removeEventListener('change', changeMobile)
      window.removeEventListener('resize', changeViewport)
    }
  }, [])

  useEffect(() => { rightRailWidthRef.current = rightRailWidth }, [rightRailWidth])
  useEffect(() => () => {
    window.clearTimeout(closingFixedRailTimer.current)
    window.clearTimeout(insightsClosingTimer.current)
  }, [])

  useEffect(() => {
    const main = mainRef.current
    if (!feedRoute || !main) {
      setInsightsCanFloat(false)
      setInsightsObstructsFeed(false)
      setFeedInsightsLayout(null)
      return
    }
    const measure = () => {
      const reading = main.querySelector<HTMLElement>('[data-page-frame="reading"]')
      if (!reading) {
        setInsightsCanFloat(false)
        setInsightsObstructsFeed(false)
        setFeedInsightsLayout(null)
        return
      }
      const mainBounds = main.getBoundingClientRect()
      const shiftedReadingBounds = reading.getBoundingClientRect()
      const readingWidth = shiftedReadingBounds.width || shiftedReadingBounds.right - shiftedReadingBounds.left
      const centeredReadingLeft = mainBounds.left + (mainBounds.right - mainBounds.left - readingWidth) / 2
      const readingBounds = {
        left: centeredReadingLeft,
        right: centeredReadingLeft + readingWidth,
      }
      setInsightsCanFloat(canFloatFeedInsights(
        mainBounds.right,
        readingBounds.right,
      ))
      const layout = calculateFeedInsightsLayout(
        mainBounds,
        readingBounds,
        insightsSurface === 'manual',
      )
      setFeedInsightsLayout((current) => current
        && current.panelLeft === layout.panelLeft
        && current.readingShift === layout.readingShift
        && current.obstructsFeed === layout.obstructsFeed
        ? current
        : layout)
      setInsightsObstructsFeed(insightsSurface === 'manual' && layout.obstructsFeed)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(main)
    const reading = main.querySelector<HTMLElement>('[data-page-frame="reading"]')
    if (reading) observer.observe(reading)
    return () => observer.disconnect()
  }, [feedRoute, fixedRightRail, insightsSurface, rightRailWidth, sidebarExpanded, viewportWidth])

  useEffect(() => {
    if (visibleRightRailMode !== 'agent' || !insightsOpen || !dockCapable) return
    const timer = window.setTimeout(() => {
      const main = mainRef.current
      const insights = insightsRef.current
      const reading = main?.querySelector<HTMLElement>('[data-page-frame="reading"]')
      if (!main || !reading || !insights) return
      const readingBounds = reading.getBoundingClientRect()
      const insightsBounds = insights.getBoundingClientRect()
      const obstructsFeed = readingBounds.left < insightsBounds.right
        && readingBounds.right > insightsBounds.left
      setInsightsObstructsFeed(insightsSurface === 'manual' && obstructsFeed)
      if (obstructsFeed && !insightsOpenedAlongsideAgentRef.current) closeInsights(false)
    }, rightRailAnimated ? deliberateLayoutMotionMs + 20 : 0)
    return () => window.clearTimeout(timer)
  }, [closeInsights, dockCapable, insightsOpen, insightsSurface, rightRailAnimated, rightRailWidth, sidebarExpanded, viewportWidth, visibleRightRailMode])

  useEffect(() => {
    if (openclawChat.isRunning) return
    const trace = openclawChat.runTrace
    if (!trace || trace.status === 'running') return
    const runKey = `${trace.runId ?? 'local'}:${trace.startedAt}:${trace.status}`
    if (notifiedAgentRunRef.current === runKey) return
    if (visibleRightRailMode !== 'closed') {
      notifiedAgentRunRef.current = runKey
      return
    }
    const terminalState: AgentAttentionState = trace.status === 'completed'
      ? 'completed'
      : trace.status === 'failed'
        ? 'failed'
        : 'stopped'
    const timer = window.setTimeout(() => {
      notifiedAgentRunRef.current = runKey
      setAgentAttention(terminalState)
      if (terminalState === 'completed') {
        actionToast.success('OpenClaw 已完成', { description: '结果已准备好，打开 Agent 查看。' })
      } else if (terminalState === 'failed') {
        actionToast.danger('OpenClaw 执行失败', { description: '打开 Agent 查看详情或重试。' })
      } else {
        actionToast.info('OpenClaw 已停止', { description: '打开 Agent 查看已保留的内容。' })
      }
    }, 0)
    return () => window.clearTimeout(timer)
  }, [openclawChat.isRunning, openclawChat.runTrace, visibleRightRailMode])

  useEffect(() => {
    let closeFrame: number | undefined
    if (!feedRoute) {
      if (insightsSurface !== 'closed') closeFrame = window.requestAnimationFrame(dismissInsightsImmediately)
      return () => { if (closeFrame !== undefined) window.cancelAnimationFrame(closeFrame) }
    }
    if (insightsSurface === 'auto' && !insightsCanFloat) {
      const autoCloseFrame = window.requestAnimationFrame(
        visibleRightRailMode === 'agent' ? () => closeInsights(false) : dismissInsightsImmediately,
      )
      return () => window.cancelAnimationFrame(autoCloseFrame)
    }
    if (!insightsCanFloat || !hasInsightsData || insightsSurface !== 'closed') return
    const autoFrame = window.requestAnimationFrame(() => {
      try {
        const key = insightsDismissedKey(props.user.id)
        if (window.sessionStorage.getItem(key)) return
        window.sessionStorage.setItem(key, 'shown')
      } catch { /* Automatic display remains best-effort when storage is unavailable. */ }
      setInsightsSurface('auto')
    })
    return () => window.cancelAnimationFrame(autoFrame)
  }, [closeInsights, dismissInsightsImmediately, feedRoute, hasInsightsData, insightsCanFloat, insightsSurface, props.user.id, visibleRightRailMode])

  useEffect(() => {
    if (visibleRightRailMode !== 'agent' || !insightsOpen || dockCapable) return
    const closeFrame = window.requestAnimationFrame(() => closeInsights(false))
    return () => window.cancelAnimationFrame(closeFrame)
  }, [closeInsights, dockCapable, insightsOpen, visibleRightRailMode])

  useEffect(() => {
    if ((visibleRightRailMode === 'closed' && !insightsOpen) || mobile) return
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      if (insightsOpen) closeInsights()
      else closeRightRail()
    }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [closeInsights, closeRightRail, insightsOpen, mobile, visibleRightRailMode])

  useEffect(() => {
    if (!props.refreshMessage || refreshing) return
    const eventKey = `${props.user.id}:${props.refreshEventKey || `${props.refreshState}:${props.refreshMessage}`}`
    if (shownRefreshEvents.current.has(eventKey)) return
    shownRefreshEvents.current.add(eventKey)
    const options = {
      description: props.refreshMessage,
      onRetry: props.onRetry,
    }
    if (props.refreshState === 'succeeded') {
      actionToast.success('信息流已更新', options)
    } else if (props.refreshState === 'partial') {
      actionToast.warning('信息流部分更新', options)
    } else if (props.refreshState === 'reload_failed') {
      actionToast.danger('信息流加载失败', options)
    } else if (props.refreshState === 'blocked') {
      actionToast.danger('信息流更新未开始', options)
    } else if (props.refreshState === 'failed') {
      actionToast.danger('信息流更新失败', options)
    } else {
      actionToast.info('信息流更新状态', options)
    }
  }, [props.onRetry, props.refreshEventKey, props.refreshMessage, props.refreshState, props.user.id, refreshing])

  const updateRailWidthFromPointer = useCallback((clientX: number) => {
    const shellRight = shellRef.current?.getBoundingClientRect().right ?? viewportWidth
    const width = clampRightRailWidth(shellRight - clientX, viewportWidth, sidebarWidth)
    rightRailWidthRef.current = width
    setRightRailWidthState({ userId: props.user.id, value: width })
  }, [props.user.id, sidebarWidth, viewportWidth])

  const finishRailResize = useCallback(() => {
    setResizingRail(false)
    const preference = writeRightRailWidth(props.user.id, rightRailWidthRef.current)
    setRightRailWidthState({ userId: props.user.id, value: preference.width })
  }, [props.user.id])

  const handleRailPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setResizingRail(true)
    updateRailWidthFromPointer(event.clientX)
  }, [updateRailWidthFromPointer])

  const handleRailPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizingRail) return
    if (event.currentTarget.hasPointerCapture && !event.currentTarget.hasPointerCapture(event.pointerId)) return
    updateRailWidthFromPointer(event.clientX)
  }, [resizingRail, updateRailWidthFromPointer])

  const handleRailKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    const maximum = maximumRightRailWidth(viewportWidth, sidebarWidth)
    const step = event.shiftKey ? 64 : 24
    let width = rightRailWidthRef.current
    if (event.key === 'ArrowLeft') width += step
    else if (event.key === 'ArrowRight') width -= step
    else if (event.key === 'Home') width = RIGHT_RAIL_MIN_WIDTH
    else if (event.key === 'End') width = maximum
    else return
    event.preventDefault()
    const next = clampRightRailWidth(width, viewportWidth, sidebarWidth)
    rightRailWidthRef.current = next
    const preference = writeRightRailWidth(props.user.id, next)
    setRightRailWidthState({ userId: props.user.id, value: preference.width })
  }, [props.user.id, sidebarWidth, viewportWidth])

  const resetRailWidth = useCallback(() => {
    const next = clampRightRailWidth(RIGHT_RAIL_DEFAULT_WIDTH, viewportWidth, sidebarWidth)
    rightRailWidthRef.current = next
    const preference = writeRightRailWidth(props.user.id, next)
    setRightRailWidthState({ userId: props.user.id, value: preference.width })
  }, [props.user.id, sidebarWidth, viewportWidth])

  const agentPanelToggleLabel = visibleRightRailMode === 'agent' ? '收起 Agent 面板' : '展开 Agent 面板'
  const agentToggleHelp = visibleAgentAttention === 'none'
    ? agentPanelToggleLabel
    : agentAttentionLabel[visibleAgentAttention]
  const agentToggleAriaLabel = visibleAgentAttention === 'none'
    ? agentPanelToggleLabel
    : `${agentPanelToggleLabel}，${agentAttentionLabel[visibleAgentAttention]}`

  return <WorkbenchAgentContext.Provider value={agentValue}>
      <div
        ref={shellRef}
        data-testid="live-workbench-shell"
        data-ui-typography="system"
        data-fixed-agent-rail={fixedRightRail ? 'true' : 'false'}
        data-fixed-agent-rail-phase={fixedRightRail ? 'open' : fixedRailPresent ? 'closing' : 'absent'}
        data-insights-obstructs-feed={insightsObstructsFeed ? 'true' : 'false'}
        data-rail-resizing={resizingRail ? 'true' : 'false'}
        data-layout-motion={rightRailAnimated && !resizingRail ? 'deliberate' : 'immediate'}
        onPointerDown={handleIneffectivePrimaryPointerDown}
        style={desktopGridStyle}
        className={`grid h-dvh min-h-0 grid-cols-1 grid-rows-[52px_minmax(0,1fr)] overflow-hidden bg-background text-foreground min-[768px]:grid-cols-[72px_minmax(0,1fr)] ${desktopGridColumns} ${rightRailAnimated && !resizingRail ? 'transition-[grid-template-columns] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none' : 'transition-none'}`}
      >
        <aside className="hidden min-h-0 flex-col overflow-x-hidden border-r border-separator bg-surface min-[768px]:col-start-1 min-[768px]:row-span-2 min-[768px]:flex" aria-label="桌面导航">
          <div className={`type-page-title flex h-[52px] shrink-0 items-center gap-2 px-3 ${sidebarExpanded ? 'justify-start' : 'justify-center'}`}>
            {extraWideDesktop ? sidebarExpanded ? <>
              <Icons.InteliscopeMark size={20} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">Inteliscope</span>
              <button
                type="button"
                data-sidebar-panel-toggle
                className={sidebarPanelToggleClass(true)}
                aria-label="收起侧栏"
                aria-expanded="true"
                onClick={toggleSidebar}
              ><Icons.SplitPanel open size={18} aria-hidden="true" /></button>
            </> : <button
              type="button"
              data-sidebar-panel-toggle
              data-inteliscope-mark-trigger
              className={sidebarPanelToggleClass(false)}
              aria-label="展开侧栏"
              aria-expanded="false"
              onClick={toggleSidebar}
            ><Icons.SplitPanel size={18} aria-hidden="true" /></button> : <Popover isOpen={tabletNavOpen} onOpenChange={changeTabletNavigation}>
              <Popover.Trigger
                ref={tabletNavToggleRef}
                data-sidebar-panel-toggle
                data-inteliscope-mark-trigger
                aria-label="展开导航"
                aria-expanded={tabletNavOpen}
                className={sidebarPanelToggleClass(tabletNavOpen)}
              ><Icons.SplitPanel open={tabletNavOpen} size={18} aria-hidden="true" /></Popover.Trigger>
              <Popover.Content placement="right top" offset={8} className="z-50 w-[260px] p-0">
                <Popover.Dialog aria-label="分类导航" className="max-h-[calc(100dvh-24px)] overflow-hidden rounded-2xl border border-separator bg-surface p-0 shadow-xl">
                  <div className="flex h-[52px] items-center gap-2 border-b border-separator px-4">
                    <Icons.InteliscopeMark size={20} aria-hidden="true" />
                    <strong className="min-w-0 flex-1 truncate">Inteliscope</strong>
                  </div>
                  <CategorizedNavigation
                    activeQuickView={activeQuickView}
                    quickViewsOpen={quickViewsOpen}
                    onQuickViewsToggle={() => setQuickViewsOpen((value) => !value)}
                    onQuickView={selectQuickView}
                    onNavigate={() => changeTabletNavigation(false)}
                    role={props.user.role}
                    settingsDirectory={false}
                  />
                </Popover.Dialog>
              </Popover.Content>
            </Popover>}
          </div>
          {sidebarExpanded ? <div className={`${rightRailAnimated ? 'quiet-surface-enter ' : ''}min-h-0 flex-1 overflow-hidden`}>
            <CategorizedNavigation
              activeQuickView={activeQuickView}
              quickViewsOpen={quickViewsOpen}
              onQuickViewsToggle={() => setQuickViewsOpen((value) => !value)}
              onQuickView={selectQuickView}
              role={props.user.role}
            />
          </div> : <nav aria-label="工作台导航" className="quiet-scroll-region min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-2 py-2">
            {browseNavigation.map(({ label, href, icon: Icon }) => <SidebarNavItem
              key={href}
              href={href}
              end={href === '/feed'}
              compact
              label={label}
              leading={<Icon size={18} aria-hidden="true" />}
            />)}
            <Separator className="my-2" />
            {managementNavigation.map(({ id, label, href, icon: Icon }) => id === 'settings'
              ? <SettingsSidebarNavigationItem key={href} compact role={props.user.role} />
              : <SidebarNavItem
                key={href}
                href={href}
                compact
                label={label}
                leading={<Icon size={18} aria-hidden="true" />}
              />)}
          </nav>}
          <div
            data-sidebar-account-strip
            className="flex items-center gap-1 border-t border-separator p-2"
          >
            <Popover isOpen={accountMenuOpen} onOpenChange={setAccountMenuOpen}>
              <Popover.Trigger
                aria-label="打开账户菜单"
                title={sidebarExpanded ? undefined : '账户'}
                className={`flex min-h-11 min-w-0 items-center gap-2 rounded-xl p-1.5 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus ${sidebarExpanded ? 'flex-1 justify-start' : 'w-full justify-center'}`}
              >
                <AvatarRoot className="size-8 shrink-0"><AvatarFallback>{(props.user.display_name || props.user.username).slice(0, 1).toUpperCase()}</AvatarFallback></AvatarRoot>
                {sidebarExpanded && <>
                  <span className="min-w-0 flex-1"><span className="type-control block truncate">{props.user.display_name || props.user.username}</span><span className="type-label block text-muted">{roleLabel[props.user.role]}</span></span>
                </>}
              </Popover.Trigger>
              <Popover.Content
                data-account-menu-surface
                data-sidebar-menu-direction="up"
                placement="top start"
                offset={8}
                containerPadding={12}
                className="z-50 w-52 p-0"
              >
                <Popover.Dialog aria-label="账户菜单" className="p-2">
                  <div className="px-2 py-2">
                    <strong className="type-control block truncate">{props.user.display_name || props.user.username}</strong>
                    <span className="type-meta text-muted">{props.user.username} · {roleLabel[props.user.role]}</span>
                  </div>
                  <Separator className="my-1" />
                  <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/users') }}><Icons.Users size={16} aria-hidden="true" />账户与成员</Button>
                  <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/settings') }}><Icons.Settings size={16} aria-hidden="true" />设置</Button>
                  <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/manual') }}><Icons.BookOpen size={16} aria-hidden="true" />操作手册</Button>
                  <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/changelog') }}><Icons.ScrollText size={16} aria-hidden="true" />更新日志</Button>
                  <a
                    href={PRODUCT_RELEASES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="type-control flex min-h-9 w-full items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
                    onClick={() => setAccountMenuOpen(false)}
                  ><Icons.Rocket size={16} aria-hidden="true" />Release 发布页<Icons.ExternalLink className="ml-auto" size={13} aria-hidden="true" /></a>
                  <Separator className="my-1" />
                  <Button variant="ghost" className="w-full justify-start text-danger" aria-label="退出登录" onPress={() => { openclawChat.clearTranscript(); openclawChat.disconnect(); props.onLogout() }}><Icons.LogOut size={16} aria-hidden="true" />退出登录</Button>
                </Popover.Dialog>
              </Popover.Content>
            </Popover>
            {sidebarExpanded && <Popover isOpen={documentationMenuOpen} onOpenChange={setDocumentationMenuOpen}>
              <Popover.Trigger
                aria-label="打开文档与发布菜单"
                title="文档与发布"
                className="flex size-9 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
              ><Icons.BookMarked size={16} aria-hidden="true" /></Popover.Trigger>
              <Popover.Content
                data-documentation-menu-surface
                data-sidebar-menu-direction="up"
                placement="top end"
                offset={8}
                crossOffset={-3}
                containerPadding={12}
                className="z-50 w-52 p-0"
              >
                <Popover.Dialog aria-label="文档与发布菜单" className="p-2">
                  <Button variant="ghost" className="w-full justify-start" onPress={() => { setDocumentationMenuOpen(false); navigate('/manual') }}><Icons.BookOpen size={16} aria-hidden="true" />操作手册</Button>
                  <Button variant="ghost" className="w-full justify-start" onPress={() => { setDocumentationMenuOpen(false); navigate('/changelog') }}><Icons.ScrollText size={16} aria-hidden="true" />更新日志</Button>
                  <a
                    href={PRODUCT_RELEASES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="type-control flex min-h-9 w-full items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
                    onClick={() => setDocumentationMenuOpen(false)}
                  ><Icons.Rocket size={16} aria-hidden="true" />Release 发布页<Icons.ExternalLink className="ml-auto" size={13} aria-hidden="true" /></a>
                </Popover.Dialog>
              </Popover.Content>
            </Popover>}
          </div>
        </aside>

        <PageHeader
          title={pageTitle}
          className="col-start-1 row-start-1 min-[768px]:col-start-2"
          actions={<div className="flex items-center gap-1">
            <ThemeModeToggle />
            {feedRoute && <Button
              ref={insightsToggleRef}
              size="sm"
              variant="ghost"
              isIconOnly
              data-right-rail-toggle="insights"
              className={`h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none ${insightsOpen ? 'bg-accent/15 text-accent' : 'text-muted'}`}
              aria-label={insightsOpen ? '收起信息概览' : '展开信息概览'}
              aria-expanded={insightsOpen}
              aria-controls="feed-insights-surface"
              isDisabled={mobile && openclawChat.isRunning}
              onPress={toggleInsights}
            ><Icons.ChartNoAxesCombined size={18} aria-hidden="true" /></Button>}
            {agentRoute && <Tooltip delay={250}>
              <TooltipTriggerButton
                ref={agentToggleRef}
                data-agent-toggle-visual="quiet-studio"
                data-agent-open={visibleRightRailMode === 'agent' ? 'true' : 'false'}
                className="relative grid h-8 w-[34px] place-items-center rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 data-[agent-open=true]:bg-accent/15 data-[agent-open=true]:text-accent motion-reduce:transform-none"
                aria-label={agentToggleAriaLabel}
                aria-expanded={visibleRightRailMode === 'agent'}
                aria-controls="live-agent-panel"
                disabled={mobile && openclawChat.isRunning}
                onClick={toggleAgentRail}
              >
                <Icons.SplitPanel open={visibleRightRailMode === 'agent'} size={18} aria-hidden="true" />
                {visibleAgentAttention !== 'none' && <AgentAttentionBadge state={visibleAgentAttention} />}
              </TooltipTriggerButton>
              <Tooltip.Content {...anchoredTooltipProps}>{agentToggleHelp}</Tooltip.Content>
            </Tooltip>}
          </div>}
        />

        <main
          ref={mainRef}
          data-feed-reading-layout={feedRoute ? 'true' : undefined}
          data-feed-layout-motion={resizingRail ? 'immediate' : 'deliberate'}
          className="relative col-start-1 row-start-2 min-h-0 min-w-0 overflow-hidden pb-[calc(64px+env(safe-area-inset-bottom))] min-[768px]:col-start-2 min-[768px]:pb-0"
          style={feedRoute ? {
            '--inteliscope-feed-reading-shift': `${feedInsightsLayout?.readingShift ?? 0}px`,
          } as CSSProperties : undefined}
        >
          {props.children}
        </main>

        {fixedRailPresent && <aside
          id="live-agent-panel"
          role="complementary"
          aria-label="OpenClaw 上下文"
          aria-hidden={!fixedRightRail}
          inert={!fixedRightRail}
          data-rail-surface-state={fixedRightRail ? 'open' : 'closing'}
          className={`relative col-start-3 row-span-2 grid min-h-0 min-w-0 grid-rows-[52px_minmax(0,1fr)_auto] overflow-hidden overscroll-none border-l border-separator bg-surface transition-[opacity,transform] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none ${fixedRightRail ? 'translate-x-0 opacity-100' : 'pointer-events-none translate-x-2 opacity-0'}`}
        >
          <div
            role="separator"
            tabIndex={0}
            aria-label="调整信息流和 Agent 面板宽度"
            aria-orientation="vertical"
            aria-valuemin={RIGHT_RAIL_MIN_WIDTH}
            aria-valuemax={maximumRightRailWidth(viewportWidth, sidebarWidth)}
            aria-valuenow={rightRailWidth}
            data-testid="right-rail-resizer"
            title="拖动调整宽度；双击恢复默认"
            className="group absolute inset-y-0 -left-[5px] z-20 w-[10px] cursor-col-resize touch-none focus-visible:outline-none"
            onPointerDown={handleRailPointerDown}
            onPointerMove={handleRailPointerMove}
            onPointerUp={(event) => {
              if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture?.(event.pointerId)
              finishRailResize()
            }}
            onPointerCancel={finishRailResize}
            onKeyDown={handleRailKeyDown}
            onDoubleClick={resetRailWidth}
          ><span className={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors motion-reduce:transition-none ${resizingRail ? 'bg-accent' : 'bg-separator group-hover:bg-muted group-focus-visible:bg-accent'}`} /></div>
          <AgentPanelContent open={fixedRailPresent} onClose={closeRightRail} closeDisabled={mobile && openclawChat.isRunning} chat={openclawChat} configLoading={delegations.isLoading} value={agentValue} api={props.api} userId={props.user.id} />
        </aside>}

        {feedRoute && insightsPresent && !mobile && <aside
          ref={insightsRef}
          id="feed-insights-surface"
          role="complementary"
          aria-label="信息概览"
          aria-hidden={insightsClosing}
          inert={insightsClosing}
          data-insights-surface={insightsSurface}
          className={`${insightsClosing ? 'quiet-surface-exit pointer-events-none' : 'quiet-surface-enter'} ${resizingRail ? 'transition-none' : 'transition-[left] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none'} fixed top-[60px] z-30 flex max-h-[calc(100dvh-72px)] w-[min(352px,calc(100vw-24px))] flex-col overflow-hidden rounded-[var(--inteliscope-radius-panel)] border border-separator bg-surface shadow-[var(--overlay-shadow)]`}
          style={feedInsightsLayout
            ? { left: feedInsightsLayout.panelLeft }
            : { right: fixedRightRail ? rightRailWidth + FLOATING_INSIGHTS_INSET : FLOATING_INSIGHTS_INSET }}
          onAnimationEnd={insightsClosing ? (event) => {
            if (event.target === event.currentTarget) completeInsightsClose()
          } : undefined}
        ><FeedInsightsPanel open={insightsOpen} onClose={() => closeInsights()} api={props.api} userId={props.user.id} includeDisabledSources={props.user.role === 'owner' || props.user.role === 'admin'} preference={feedPreference} query={props.query} onMetricAction={handleInsightsMetric} onChannelAction={handleInsightsChannel} /></aside>}

        {agentRoute && !fixedRightRail && (visibleRightRailMode === 'agent' || (mobile && insightsPresent)) && <Drawer isOpen={visibleRightRailMode === 'agent' || (mobile && insightsOpen)} onOpenChange={(open) => {
          if (open) return
          if (insightsPresent && visibleRightRailMode !== 'agent') closeInsights()
          else closeRightRail()
        }}>
          <Drawer.Trigger aria-hidden="true" className="hidden">打开右侧面板</Drawer.Trigger>
          <Drawer.Backdrop isDismissable={!mobile || !openclawChat.isRunning} variant="blur" data-testid="right-rail-drawer-backdrop">
            <Drawer.Content placement={mobile ? 'bottom' : 'right'}>
              <Drawer.Dialog
                id={visibleRightRailMode === 'agent' ? 'live-agent-panel' : 'feed-insights-surface'}
                aria-label={visibleRightRailMode === 'agent' ? 'OpenClaw 上下文' : '信息概览'}
                className={`${rightRailAnimated ? 'quiet-surface-enter ' : ''}grid min-h-0 min-w-0 grid-rows-[52px_minmax(0,1fr)_auto] overflow-hidden overscroll-none border-separator bg-surface p-0 outline-none ${mobile ? 'h-[min(88dvh,720px)] max-h-[88dvh] w-full rounded-t-2xl border-t' : 'h-dvh w-[min(400px,calc(100vw-24px))] max-w-[400px] rounded-l-2xl border-l'}`}
              >
                {visibleRightRailMode === 'agent'
                  ? <AgentPanelContent open onClose={closeRightRail} closeDisabled={mobile && openclawChat.isRunning} chat={openclawChat} configLoading={delegations.isLoading} value={agentValue} api={props.api} userId={props.user.id} />
                  : <FeedInsightsPanel open onClose={() => closeInsights()} api={props.api} userId={props.user.id} includeDisabledSources={props.user.role === 'owner' || props.user.role === 'admin'} preference={feedPreference} query={props.query} onMetricAction={handleInsightsMetric} onChannelAction={handleInsightsChannel} />}
              </Drawer.Dialog>
            </Drawer.Content>
          </Drawer.Backdrop>
        </Drawer>}

        <Drawer isOpen={mobileMoreOpen} onOpenChange={setMobileMoreOpen}>
          <Drawer.Trigger aria-hidden="true" className="hidden">打开更多与账户</Drawer.Trigger>
          <Drawer.Backdrop variant="blur" className="min-[768px]:hidden">
            <Drawer.Content placement="bottom">
              <Drawer.Dialog aria-label="更多与账户" className="max-h-[min(82dvh,680px)] w-full overflow-y-auto rounded-t-2xl bg-surface p-0 pb-[env(safe-area-inset-bottom)] outline-none">
                <Drawer.Header className="border-b border-separator px-5 py-4">
                  <Drawer.Heading>更多与账户</Drawer.Heading>
                </Drawer.Header>
                <Drawer.Body className="grid gap-1 p-3">
                  <div className="mb-2 flex items-center gap-3 rounded-xl bg-default/70 p-3">
                    <AvatarRoot className="size-9 shrink-0"><AvatarFallback>{(props.user.display_name || props.user.username).slice(0, 1).toUpperCase()}</AvatarFallback></AvatarRoot>
                    <span className="min-w-0"><strong className="type-control block truncate">{props.user.display_name || props.user.username}</strong><span className="type-meta text-muted">{props.user.username} · {roleLabel[props.user.role]}</span></span>
                  </div>
                  {[
                    { label: '历史', href: '/history', icon: Icons.History },
                    { label: '账户与成员', href: '/users', icon: Icons.Users },
                    { label: '设置', href: '/settings', icon: Icons.Settings },
                    { label: '操作手册', href: '/manual', icon: Icons.BookOpen },
                    { label: '更新日志', href: '/changelog', icon: Icons.ScrollText },
                  ].map(({ label, href, icon: Icon }) => <Button
                    key={href}
                    variant="ghost"
                    className="min-h-11 w-full justify-start"
                    onPress={() => {
                      setMobileMoreOpen(false)
                      navigate(href)
                    }}
                  ><Icon size={17} aria-hidden="true" />{label}</Button>)}
                  <a
                    href={PRODUCT_RELEASES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="type-control flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
                    onClick={() => setMobileMoreOpen(false)}
                  ><Icons.Rocket size={17} aria-hidden="true" />Release 发布页<Icons.ExternalLink className="ml-auto" size={13} aria-hidden="true" /></a>
                  <Separator className="my-2" />
                  <Button variant="ghost" className="min-h-11 w-full justify-start text-danger" aria-label="退出登录" onPress={() => {
                    setMobileMoreOpen(false)
                    openclawChat.clearTranscript()
                    openclawChat.disconnect()
                    props.onLogout()
                  }}><Icons.LogOut size={17} aria-hidden="true" />退出登录</Button>
                </Drawer.Body>
              </Drawer.Dialog>
            </Drawer.Content>
          </Drawer.Backdrop>
        </Drawer>

        <nav aria-label="移动端主导航" className="fixed inset-x-0 bottom-0 z-30 grid min-h-16 grid-cols-5 border-t border-separator bg-surface pb-[env(safe-area-inset-bottom)] min-[768px]:hidden">
          {mobilePrimaryNavigation.map(({ label, href, icon: Icon }) => <NavLink key={href} to={href} end={href === '/feed'} aria-label={label} className="type-micro flex min-h-16 min-w-11 flex-col items-center justify-center gap-1 text-muted aria-[current=page]:text-accent">
            <Icon size={17} aria-hidden="true" /><span>{label}</span>
          </NavLink>)}
          <button
            type="button"
            aria-label="更多与账户"
            aria-expanded={mobileMoreOpen}
            className={`type-micro flex min-h-16 min-w-11 flex-col items-center justify-center gap-1 ${mobileMoreOpen || ['/history', '/users', '/settings', '/manual', '/changelog'].includes(location.pathname) ? 'text-accent' : 'text-muted'}`}
            onClick={() => setMobileMoreOpen(true)}
          >
            <Icons.Menu size={17} aria-hidden="true" /><span>更多</span>
          </button>
        </nav>
      </div>
  </WorkbenchAgentContext.Provider>
}
