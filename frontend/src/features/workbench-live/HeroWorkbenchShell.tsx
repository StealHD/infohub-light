import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
import { queryKeys } from '../../api/queryKeys'
import { readBootstrapShellRightRail, writeBootstrapShellRightRail } from '../../app/bootstrapShell'
import { readSidebarPreference, writeSidebarPreference } from '../../app/sidebarPreference'
import {
  FEED_PREFERENCE_CHANGED_EVENT,
  readFeedPreference,
  writeFeedPreference,
} from '../feed/feedPreference'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import {
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Button,
  CalmSkeleton,
  Card,
  Chip,
  Drawer,
  Icons,
  LoadingReveal,
  PageHeader,
  Popover,
  Separator,
  Skeleton,
  ThemeModeToggle,
} from '../../design-system'
import {
  readAgentContextDraft,
  updateAgentContextDraft,
  writeAgentContextDraft,
  type AgentContextDraftV3,
} from './agentContext'
import { OpenClawConversation } from '../openclaw/OpenClawConversation'
import { useOpenClawChat, type OpenClawConnectionStatus, type OpenClawToolsStatus } from '../openclaw/useOpenClawChat'
import { HandoffComposer } from './HandoffComposer'
import { FeedInsightsPanel } from './FeedInsightsPanel'
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

export type RightRailMode = 'closed' | 'agent'
export type InsightsSurfaceState = 'closed' | 'auto' | 'manual' | 'closing'

type RefreshState = 'idle' | 'pending' | 'queued' | 'running' | 'partial' | 'failed' | 'succeeded' | 'blocked'

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
const mobileNavigation = navigation.filter((item) => item.id !== 'users')

const roleLabel = {
  owner: '所有者',
  admin: '管理员',
  member: '成员',
  viewer: '只读成员',
} as const

type CategorizedNavigationProps = {
  activeQuickView: WorkbenchQuickViewId | null
  quickViewsOpen: boolean
  onQuickViewsToggle: () => void
  onQuickView: (id: WorkbenchQuickViewId) => void
  onNavigate?: () => void
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
  if (href) return <NavLink
    to={href}
    end={end}
    aria-label={label}
    data-sidebar-nav-item={compact ? 'collapsed' : 'expanded'}
    onClick={onActivate}
    className={({ isActive }) => itemClass(isActive)}
  >{content}</NavLink>
  return <button
    type="button"
    aria-label={label}
    aria-pressed={selected}
    data-sidebar-nav-item={compact ? 'collapsed' : 'expanded'}
    className={itemClass(selected)}
    onClick={onActivate}
  >{content}</button>
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

function CategorizedNavigation({ activeQuickView, quickViewsOpen, onQuickViewsToggle, onQuickView, onNavigate }: CategorizedNavigationProps) {
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
    {managementNavigation.map((item) => <ExpandedRoute key={item.href} {...item} onNavigate={onNavigate} />)}
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

type RectBounds = Pick<DOMRectReadOnly, 'left' | 'right' | 'top' | 'bottom'>

export function rectanglesOverlap(first: RectBounds, second: RectBounds): boolean {
  return first.left < second.right
    && first.right > second.left
    && first.top < second.bottom
    && first.bottom > second.top
}

const gatewayStatusLabel: Record<OpenClawConnectionStatus, string> = {
  disabled: '对话未启用',
  idle: '未连接',
  connecting: '连接中',
  connected: '已连接',
  reconnecting: '重连中',
  error: '连接失败',
}

const toolsStatusLabel: Record<OpenClawToolsStatus, string> = {
  unknown: '工具检查中',
  available: '工具可用',
  missing: '工具未发现',
}

function AgentPanelContent({
  open,
  onClose,
  chat,
  configLoading,
  value,
  api,
  userId,
}: {
  open: boolean
  onClose: () => void
  chat: ReturnType<typeof useOpenClawChat>
  configLoading: boolean
  value: WorkbenchAgentContextValue
  api: ServiceApi
  userId: string
}) {
  const feedItems = value.draft.items.filter((item) => item.resourceType !== 'job')
  const itemQueries = useQueries({
    queries: feedItems.map((item) => ({
      queryKey: queryKeys.feedItem(userId, item.articleId),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.feedItem(item.articleId, signal),
      enabled: open && chat.status === 'disabled',
      retry: false,
    })),
  })
  const itemQueryById = new Map(feedItems.map((item, index) => [item.articleId, itemQueries[index]]))
  return <>
    <header className="flex h-[52px] min-w-0 items-center gap-2 overflow-hidden border-b border-separator px-4">
      <Icons.Sparkles className="shrink-0" size={17} aria-hidden="true" />
      <strong className="min-w-0 flex-1 truncate">OpenClaw 对话</strong>
      <LoadingReveal
        loading={configLoading}
        label="正在检查 Agent 连接"
        name="agent-status"
        className="h-5 w-16 shrink-0"
        skeleton={<CalmSkeleton className="h-5 w-16 rounded-lg" />}
      ><Chip size="sm" color={chat.status === 'connected' ? 'accent' : 'default'} variant="primary"><Chip.Label>{gatewayStatusLabel[chat.status]}</Chip.Label></Chip></LoadingReveal>
      {(chat.status === 'connected' || chat.status === 'reconnecting') && <Chip size="sm" color={chat.toolsStatus === 'available' ? 'success' : 'default'} variant="soft"><Chip.Label>{toolsStatusLabel[chat.toolsStatus]}</Chip.Label></Chip>}
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭 Agent 面板" isDisabled={chat.isRunning} onPress={onClose}>
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
                <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden whitespace-nowrap">
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
              <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden whitespace-nowrap">
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
  const [rightRailAnimated, setRightRailAnimated] = useState(false)
  const [closingFixedRail, setClosingFixedRail] = useState(false)
  const closingFixedRailTimer = useRef<number | undefined>(undefined)
  const insightsClosingTimer = useRef<number | undefined>(undefined)
  const [insightsSurface, setInsightsSurface] = useState<InsightsSurfaceState>('closed')
  const [insightsCanFloat, setInsightsCanFloat] = useState(false)
  const [insightsObstructsFeed, setInsightsObstructsFeed] = useState(false)
  const [resizingRail, setResizingRail] = useState(false)
  const [tabletNavOpen, setTabletNavOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [documentationMenuOpen, setDocumentationMenuOpen] = useState(false)
  const [quickViewsOpen, setQuickViewsOpen] = useState(true)
  const [sidebarState, setSidebarState] = useState(() => ({ userId: props.user.id, value: readSidebarPreference(props.user.id) }))
  const [rightRailWidthState, setRightRailWidthState] = useState(() => ({ userId: props.user.id, value: readRightRailWidth(props.user.id) }))
  const [feedPreferenceState, setFeedPreferenceState] = useState(() => ({ userId: props.user.id, value: readFeedPreference(props.user.id) }))
  const [draft, setDraft] = useState(() => readAgentContextDraft(props.user.id))
  const [dismissedNotice, setDismissedNotice] = useState('')
  const delegations = useQuery({ queryKey: queryKeys.agentDelegations(props.user.id), queryFn: ({ signal }) => props.api.agentDelegations(signal), retry: false, enabled: agentRoute })
  const insightsFeed = useQuery({
    queryKey: queryKeys.feed(props.user.id, { hideDismissed: false, unreadFirst: false }),
    queryFn: ({ signal }) => props.api.latestFeed(signal),
    enabled: feedRoute,
  })
  const openclawChat = useOpenClawChat({
    enabled: agentRoute && Boolean(delegations.data?.openclaw_chat?.enabled),
    userId: props.user.id,
    defaultGatewayUrl: delegations.data?.openclaw_chat?.default_gateway_url ?? 'ws://127.0.0.1:18789',
  })
  const refreshing = props.refreshState === 'pending' || props.refreshState === 'queued' || props.refreshState === 'running'
  const noticeKey = props.refreshEventKey || `${props.refreshState}:${props.refreshMessage ?? ''}`
  const noticeOpen = Boolean(props.refreshMessage) && !refreshing && dismissedNotice !== noticeKey
  const sidebarPreference = sidebarState.userId === props.user.id ? sidebarState.value : readSidebarPreference(props.user.id)
  const feedPreference = feedPreferenceState.userId === props.user.id ? feedPreferenceState.value : readFeedPreference(props.user.id)
  const activeQuickView = detectActiveQuickView(feedPreference)
  const sidebarExpanded = extraWideDesktop && sidebarPreference === 'expanded'
  const sidebarWidth = sidebarExpanded ? 232 : 72
  const desktopSidebarColumn = sidebarExpanded ? 'min-[1360px]:grid-cols-[232px_minmax(0,1fr)]' : 'min-[1360px]:grid-cols-[72px_minmax(0,1fr)]'
  const visibleRightRailMode: RightRailMode = !agentRoute
    ? 'closed'
    : openclawChat.isRunning
      ? 'agent'
      : rightRailMode
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

  const persistDraft = useCallback((next: AgentContextDraftV3) => {
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
    setInsightsSurface((current) => current === 'closing' ? 'closed' : current)
  }, [cancelInsightsClose])

  const dismissInsightsImmediately = useCallback(() => {
    cancelInsightsClose()
    setInsightsSurface('closed')
  }, [cancelInsightsClose])

  const closeInsights = useCallback((restoreFocus = true) => {
    if (insightsSurface === 'closed' || insightsSurface === 'closing') return
    suppressAutomaticInsights()
    cancelInsightsClose()
    setInsightsSurface('closing')
    insightsClosingTimer.current = window.setTimeout(completeInsightsClose, insightsExitMotionMs())
    if (restoreFocus) window.requestAnimationFrame(() => insightsToggleRef.current?.focus())
  }, [cancelInsightsClose, completeInsightsClose, insightsSurface, suppressAutomaticInsights])

  const openComposer = useCallback(() => {
    if (!dockCapable) {
      suppressAutomaticInsights()
      dismissInsightsImmediately()
    }
    cancelFixedRailClose()
    setRightRailAnimated(true)
    setRightRailMode('agent')
    writeBootstrapShellRightRail(props.user.id, 'agent', rightRailWidth)
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(
        '[aria-label="发送给 OpenClaw 的问题"], [aria-label="交给 OpenClaw 的问题"]',
      )?.focus()
    })
  }, [cancelFixedRailClose, dismissInsightsImmediately, dockCapable, props.user.id, rightRailWidth, suppressAutomaticInsights])

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
    if (openclawChat.isRunning) return
    setRightRailAnimated(true)
    finishFixedRailClose()
    setRightRailMode('closed')
    writeBootstrapShellRightRail(props.user.id, 'closed', rightRailWidth)
    window.requestAnimationFrame(() => agentToggleRef.current?.focus())
  }, [finishFixedRailClose, openclawChat.isRunning, props.user.id, rightRailWidth])

  const toggleAgentRail = useCallback(() => {
    if (openclawChat.isRunning) return
    if (visibleRightRailMode !== 'agent' && !dockCapable) {
      suppressAutomaticInsights()
      dismissInsightsImmediately()
    }
    const nextMode = visibleRightRailMode === 'agent' ? 'closed' : 'agent'
    setRightRailAnimated(true)
    if (nextMode === 'agent') cancelFixedRailClose()
    else finishFixedRailClose()
    setRightRailMode(nextMode)
    writeBootstrapShellRightRail(props.user.id, nextMode, rightRailWidth)
  }, [cancelFixedRailClose, dismissInsightsImmediately, dockCapable, finishFixedRailClose, openclawChat.isRunning, props.user.id, rightRailWidth, suppressAutomaticInsights, visibleRightRailMode])

  const toggleInsights = useCallback(() => {
    if (openclawChat.isRunning && !dockCapable) return
    if (insightsClosing) {
      cancelInsightsClose()
      setInsightsSurface('manual')
      return
    }
    if (insightsOpen) {
      closeInsights(false)
      return
    }
    if (!dockCapable) setRightRailMode('closed')
    setInsightsSurface('manual')
  }, [cancelInsightsClose, closeInsights, dockCapable, insightsClosing, insightsOpen, openclawChat.isRunning])

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
      return
    }
    const measure = () => {
      const reading = main.querySelector<HTMLElement>('[data-page-frame="reading"]')
      if (!reading) {
        setInsightsCanFloat(false)
        setInsightsObstructsFeed(false)
        return
      }
      setInsightsCanFloat(canFloatFeedInsights(
        main.getBoundingClientRect().right,
        reading.getBoundingClientRect().right,
      ))
      const insights = insightsRef.current
      setInsightsObstructsFeed(Boolean(insights && rectanglesOverlap(
        reading.getBoundingClientRect(),
        insights.getBoundingClientRect(),
      )))
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(main)
    const reading = main.querySelector<HTMLElement>('[data-page-frame="reading"]')
    if (reading) observer.observe(reading)
    if (insightsRef.current) observer.observe(insightsRef.current)
    return () => observer.disconnect()
  }, [feedRoute, fixedRightRail, insightsPresent, rightRailWidth, sidebarExpanded, viewportWidth])

  useEffect(() => {
    let closeFrame: number | undefined
    if (!feedRoute) {
      if (insightsSurface !== 'closed') closeFrame = window.requestAnimationFrame(dismissInsightsImmediately)
      return () => { if (closeFrame !== undefined) window.cancelAnimationFrame(closeFrame) }
    }
    if (insightsSurface === 'auto' && !insightsCanFloat) {
      const autoCloseFrame = window.requestAnimationFrame(dismissInsightsImmediately)
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
  }, [dismissInsightsImmediately, feedRoute, hasInsightsData, insightsCanFloat, insightsSurface, props.user.id])

  useEffect(() => {
    if ((visibleRightRailMode === 'closed' && !insightsOpen) || mobile || openclawChat.isRunning) return
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      if (insightsOpen) closeInsights()
      else closeRightRail()
    }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [closeInsights, closeRightRail, insightsOpen, mobile, openclawChat.isRunning, visibleRightRailMode])

  useEffect(() => {
    if (!noticeOpen) return
    const longNotice = props.refreshState === 'failed' || props.refreshState === 'partial' || props.refreshState === 'blocked'
    const timer = window.setTimeout(() => setDismissedNotice(noticeKey), longNotice ? 8000 : 4000)
    return () => window.clearTimeout(timer)
  }, [noticeKey, noticeOpen, props.refreshState])

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
            {managementNavigation.map(({ label, href, icon: Icon }) => <SidebarNavItem
              key={href}
              href={href}
              compact
              label={label}
              leading={<Icon size={18} aria-hidden="true" />}
            />)}
          </nav>}
          <div className="flex items-center gap-1 border-t border-separator p-2">
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
              <Popover.Content data-account-menu-surface placement="top start" offset={8} className="z-50 w-60 p-0">
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
              <Popover.Content data-documentation-menu-surface placement="top end" offset={8} className="z-50 w-56 p-0">
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
              isDisabled={openclawChat.isRunning && !dockCapable}
              onPress={toggleInsights}
            ><Icons.ChartNoAxesCombined size={18} aria-hidden="true" /></Button>}
            {agentRoute && <Button
              ref={agentToggleRef}
              size="sm"
              variant="ghost"
              isIconOnly
              data-agent-toggle-visual="quiet-studio"
              data-agent-open={visibleRightRailMode === 'agent' ? 'true' : 'false'}
              className="h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 data-[agent-open=true]:bg-accent/15 data-[agent-open=true]:text-accent motion-reduce:transform-none"
              aria-label={visibleRightRailMode === 'agent' ? '收起 Agent 面板' : '展开 Agent 面板'}
              aria-expanded={visibleRightRailMode === 'agent'}
              aria-controls="live-agent-panel"
              isDisabled={openclawChat.isRunning}
              onPress={toggleAgentRail}
            ><Icons.SplitPanel open={visibleRightRailMode === 'agent'} size={18} aria-hidden="true" /></Button>}
            <ThemeModeToggle />
          </div>}
        />

        <main ref={mainRef} className="relative col-start-1 row-start-2 min-h-0 min-w-0 overflow-hidden pb-16 min-[768px]:col-start-2 min-[768px]:pb-0">
          {noticeOpen && <div role={props.refreshState === 'failed' || props.refreshState === 'blocked' ? 'alert' : 'status'} className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted">
            <span className="flex-1">{props.refreshMessage}</span>{props.onRetry && <Button size="sm" variant="ghost" onPress={props.onRetry}>重试</Button>}
            <Button size="sm" variant="ghost" isIconOnly aria-label="关闭更新提示" onPress={() => setDismissedNotice(noticeKey)}><Icons.X size={15} /></Button>
          </div>}
          {props.children}
        </main>

        {fixedRailPresent && <aside
          id="live-agent-panel"
          role="complementary"
          aria-label="OpenClaw 上下文"
          aria-hidden={!fixedRightRail}
          inert={!fixedRightRail}
          data-rail-surface-state={fixedRightRail ? 'open' : 'closing'}
          className={`relative col-start-3 row-span-2 grid min-h-0 min-w-0 grid-rows-[52px_minmax(0,1fr)_auto] overflow-x-hidden border-l border-separator bg-surface transition-[opacity,transform] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none ${fixedRightRail ? 'translate-x-0 opacity-100' : 'pointer-events-none translate-x-2 opacity-0'}`}
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
          <AgentPanelContent open={fixedRailPresent} onClose={closeRightRail} chat={openclawChat} configLoading={delegations.isLoading} value={agentValue} api={props.api} userId={props.user.id} />
        </aside>}

        {feedRoute && insightsPresent && !mobile && <aside
          ref={insightsRef}
          id="feed-insights-surface"
          role="complementary"
          aria-label="信息概览"
          aria-hidden={insightsClosing}
          inert={insightsClosing}
          data-insights-surface={insightsSurface}
          className={`${insightsClosing ? 'quiet-surface-exit pointer-events-none' : 'quiet-surface-enter'} fixed top-[60px] z-30 flex max-h-[calc(100dvh-72px)] w-[min(352px,calc(100vw-24px))] flex-col overflow-hidden rounded-[var(--inteliscope-radius-panel)] border border-separator bg-surface shadow-[var(--overlay-shadow)]`}
          style={{ right: fixedRightRail ? rightRailWidth + 12 : 12 }}
          onAnimationEnd={insightsClosing ? (event) => {
            if (event.target === event.currentTarget) completeInsightsClose()
          } : undefined}
        ><FeedInsightsPanel open={insightsOpen} onClose={() => closeInsights()} api={props.api} userId={props.user.id} includePrivateSources={props.user.role === 'owner' || props.user.role === 'admin'} preference={feedPreference} query={props.query} /></aside>}

        {agentRoute && !fixedRightRail && (visibleRightRailMode === 'agent' || (mobile && insightsPresent)) && <Drawer isOpen={visibleRightRailMode === 'agent' || (mobile && insightsOpen)} onOpenChange={(open) => {
          if (open) return
          if (insightsPresent && visibleRightRailMode !== 'agent') closeInsights()
          else closeRightRail()
        }}>
          <Drawer.Trigger aria-hidden="true" className="hidden">打开右侧面板</Drawer.Trigger>
          <Drawer.Backdrop isDismissable={!openclawChat.isRunning} variant="blur" data-testid="right-rail-drawer-backdrop">
            <Drawer.Content placement={mobile ? 'bottom' : 'right'}>
              <Drawer.Dialog
                id={visibleRightRailMode === 'agent' ? 'live-agent-panel' : 'feed-insights-surface'}
                aria-label={visibleRightRailMode === 'agent' ? 'OpenClaw 上下文' : '信息概览'}
                className={`${rightRailAnimated ? 'quiet-surface-enter ' : ''}grid min-h-0 min-w-0 grid-rows-[52px_minmax(0,1fr)_auto] overflow-x-hidden border-separator bg-surface p-0 outline-none ${mobile ? 'h-[min(88dvh,720px)] max-h-[88dvh] w-full rounded-t-2xl border-t' : 'h-dvh w-[360px] max-w-[360px] rounded-l-2xl border-l'}`}
              >
                {visibleRightRailMode === 'agent'
                  ? <AgentPanelContent open onClose={closeRightRail} chat={openclawChat} configLoading={delegations.isLoading} value={agentValue} api={props.api} userId={props.user.id} />
                  : <FeedInsightsPanel open onClose={() => closeInsights()} api={props.api} userId={props.user.id} includePrivateSources={props.user.role === 'owner' || props.user.role === 'admin'} preference={feedPreference} query={props.query} />}
              </Drawer.Dialog>
            </Drawer.Content>
          </Drawer.Backdrop>
        </Drawer>}

        <nav aria-label="移动端主导航" className="fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-6 border-t border-separator bg-surface min-[768px]:hidden">
          {mobileNavigation.map(({ label, href, icon: Icon }) => <NavLink key={href} to={href} end={href === '/feed'} aria-label={label} className="type-micro flex min-h-11 min-w-11 flex-col items-center justify-center gap-1 text-muted aria-[current=page]:text-accent">
            <Icon size={17} aria-hidden="true" /><span>{label}</span>
          </NavLink>)}
        </nav>
      </div>
  </WorkbenchAgentContext.Provider>
}
