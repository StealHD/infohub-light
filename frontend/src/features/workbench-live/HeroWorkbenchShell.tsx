import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
import { queryKeys } from '../../api/queryKeys'
import { readSidebarPreference, writeSidebarPreference } from '../../app/sidebarPreference'
import {
  FEED_PREFERENCE_CHANGED_EVENT,
  readFeedPreference,
  writeFeedPreference,
} from '../feed/feedPreference'
import {
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Button,
  Card,
  Chip,
  Drawer,
  Icons,
  PageHeader,
  Popover,
  Separator,
  Skeleton,
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
import { WorkbenchAgentContext, type WorkbenchAgentContextValue } from './workbenchAgentContext'
import { relativeTime } from '../feed/feedModel'
import { toWorkbenchCardModel, workbenchSourceLabels } from './workbenchModel'
import {
  applyQuickView,
  detectActiveQuickView,
  WORKBENCH_QUICK_VIEWS,
  type WorkbenchQuickViewId,
} from './workbenchQuickViews'

export type RightRailMode = 'closed' | 'insights' | 'agent'

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
  { id: 'settings', label: '设置', href: '/settings', icon: Icons.Settings },
] as const

const navigation = [...browseNavigation, ...managementNavigation] as const

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
  return <nav aria-label="分类导航内容" className="min-h-0 overflow-y-auto px-2 pb-3">
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

function initialRailDesktop() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(min-width: 1440px)').matches
    : false
}

function initialRightRailMode(pathname: string): RightRailMode {
  return pathname === '/feed' && initialRailDesktop() ? 'insights' : 'closed'
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
  const itemQueries = useQueries({
    queries: value.draft.items.map((item) => ({
      queryKey: queryKeys.feedItem(userId, item.articleId),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.feedItem(item.articleId, signal),
      enabled: open && chat.status === 'disabled',
      retry: false,
    })),
  })
  return <>
    <header className="flex h-[52px] min-w-0 items-center gap-2 overflow-hidden border-b border-separator px-4">
      <Icons.Sparkles className="shrink-0" size={17} aria-hidden="true" />
      <strong className="min-w-0 flex-1 truncate">OpenClaw 对话</strong>
      {configLoading
        ? <span role="status" aria-busy="true" aria-label="正在检查 Agent 连接"><Skeleton className="h-5 w-16 rounded-lg" /></span>
        : <Chip size="sm" color={chat.status === 'connected' ? 'accent' : 'default'} variant="primary"><Chip.Label>{gatewayStatusLabel[chat.status]}</Chip.Label></Chip>}
      {(chat.status === 'connected' || chat.status === 'reconnecting') && <Chip size="sm" color={chat.toolsStatus === 'available' ? 'success' : 'default'} variant="soft"><Chip.Label>{toolsStatusLabel[chat.toolsStatus]}</Chip.Label></Chip>}
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭 Agent 面板" isDisabled={chat.isRunning} onPress={onClose}>
        <Icons.X size={17} aria-hidden="true" />
      </Button>
    </header>
    {open && configLoading && <div className="grid gap-3 p-4"><Skeleton className="h-24 rounded-xl" /><Skeleton className="h-24 rounded-xl" /></div>}
    {open && !configLoading && chat.status === 'disabled' && <>
      <div className="min-h-0 overflow-hidden p-3" data-testid="agent-scroll-region">
        <div className="type-meta mb-2 flex justify-between text-muted"><span>已选上下文</span><span>{value.draft.items.length} / 8</span></div>
        {!value.draft.items.length && <Card variant="transparent" className="p-3">
          <Card.Description>从信息卡片加入内容，再生成交给本地 OpenClaw 的确定性提示词。</Card.Description>
        </Card>}
        <div className="grid gap-1">
          {value.draft.items.map((item, index) => {
            const id = item.articleId
            const query = itemQueries[index]
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
    </>}
    {open && !configLoading && chat.status !== 'disabled' && <OpenClawConversation chat={chat} value={value} />}
  </>
}

export function HeroWorkbenchShell(props: HeroWorkbenchShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const contentRoute = ['/feed', '/saved', '/history'].includes(location.pathname)
  const feedRoute = location.pathname === '/feed'
  const pageTitle = location.pathname.endsWith('/subscriptions') ? '订阅与来源' : location.pathname.endsWith('/agents') ? '助手连接' : location.pathname.endsWith('/settings') ? '设置' : location.pathname.endsWith('/saved') ? '收藏' : location.pathname.endsWith('/history') ? '历史' : '信息流'
  const agentToggleRef = useRef<HTMLButtonElement>(null)
  const insightsToggleRef = useRef<HTMLButtonElement>(null)
  const [railManuallySelected, setRailManuallySelected] = useState(false)
  const tabletNavToggleRef = useRef<HTMLDivElement>(null)
  const [extraWideDesktop, setExtraWideDesktop] = useState(initialExtraWideDesktop)
  const [railDesktop, setRailDesktop] = useState(initialRailDesktop)
  const [mobile, setMobile] = useState(initialMobile)
  const [rightRailMode, setRightRailMode] = useState<RightRailMode>(() => initialRightRailMode(location.pathname))
  const [tabletNavOpen, setTabletNavOpen] = useState(false)
  const [quickViewsOpen, setQuickViewsOpen] = useState(true)
  const [sidebarState, setSidebarState] = useState(() => ({ userId: props.user.id, value: readSidebarPreference(props.user.id) }))
  const [feedPreferenceState, setFeedPreferenceState] = useState(() => ({ userId: props.user.id, value: readFeedPreference(props.user.id) }))
  const [draft, setDraft] = useState(() => readAgentContextDraft(props.user.id))
  const [dismissedNotice, setDismissedNotice] = useState('')
  const delegations = useQuery({ queryKey: queryKeys.agentDelegations(props.user.id), queryFn: ({ signal }) => props.api.agentDelegations(signal), retry: false, enabled: contentRoute })
  const openclawChat = useOpenClawChat({
    enabled: contentRoute && Boolean(delegations.data?.openclaw_chat?.enabled),
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
  const desktopSidebarColumn = sidebarExpanded ? 'min-[1360px]:grid-cols-[232px_minmax(0,1fr)]' : 'min-[1360px]:grid-cols-[72px_minmax(0,1fr)]'
  const visibleRightRailMode: RightRailMode = !contentRoute
    ? 'closed'
    : openclawChat.isRunning
      ? 'agent'
      : !feedRoute && rightRailMode === 'insights'
        ? 'closed'
        : feedRoute && railDesktop && !railManuallySelected && rightRailMode === 'closed'
          ? 'insights'
          : rightRailMode
  const fixedRightRail = contentRoute && railDesktop && visibleRightRailMode !== 'closed'
  const desktopGridColumns = fixedRightRail
    ? `min-[1200px]:grid-cols-[72px_minmax(0,1fr)] ${desktopSidebarColumn} ${sidebarExpanded ? 'min-[1440px]:grid-cols-[232px_minmax(640px,1fr)_360px]' : 'min-[1440px]:grid-cols-[72px_minmax(640px,1fr)_360px]'}`
    : `min-[1200px]:grid-cols-[72px_minmax(0,1fr)] ${desktopSidebarColumn}`

  function toggleSidebar() {
    const value = sidebarExpanded ? 'collapsed' : 'expanded'
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

  const openComposer = useCallback(() => {
    setRightRailMode('agent')
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(
        '[aria-label="发送给 OpenClaw 的问题"], [aria-label="交给 OpenClaw 的问题"]',
      )?.focus()
    })
  }, [])

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
    const previousMode = visibleRightRailMode
    setRailManuallySelected(true)
    setRightRailMode('closed')
    window.requestAnimationFrame(() => {
      if (previousMode === 'insights') insightsToggleRef.current?.focus()
      else agentToggleRef.current?.focus()
    })
  }, [openclawChat.isRunning, visibleRightRailMode])

  const toggleRightRail = useCallback((mode: Exclude<RightRailMode, 'closed'>) => {
    if (openclawChat.isRunning) return
    setRailManuallySelected(true)
    setRightRailMode(visibleRightRailMode === mode ? 'closed' : mode)
  }, [openclawChat.isRunning, visibleRightRailMode])

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
    const railMedia = window.matchMedia('(min-width: 1440px)')
    const mobileMedia = window.matchMedia('(max-width: 767px)')
    const changeExtraWide = (event: MediaQueryListEvent) => {
      setExtraWideDesktop(event.matches)
      if (event.matches) setTabletNavOpen(false)
    }
    const changeMobile = (event: MediaQueryListEvent) => setMobile(event.matches)
    const changeRail = (event: MediaQueryListEvent) => setRailDesktop(event.matches)
    extraWideMedia.addEventListener('change', changeExtraWide)
    mobileMedia.addEventListener('change', changeMobile)
    railMedia.addEventListener('change', changeRail)
    return () => {
      extraWideMedia.removeEventListener('change', changeExtraWide)
      mobileMedia.removeEventListener('change', changeMobile)
      railMedia.removeEventListener('change', changeRail)
    }
  }, [])

  useEffect(() => {
    if (visibleRightRailMode === 'closed' || !railDesktop || openclawChat.isRunning) return
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeRightRail()
    }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [closeRightRail, openclawChat.isRunning, railDesktop, visibleRightRailMode])

  useEffect(() => {
    if (!noticeOpen) return
    const longNotice = props.refreshState === 'failed' || props.refreshState === 'partial' || props.refreshState === 'blocked'
    const timer = window.setTimeout(() => setDismissedNotice(noticeKey), longNotice ? 8000 : 4000)
    return () => window.clearTimeout(timer)
  }, [noticeKey, noticeOpen, props.refreshState])

  return <WorkbenchAgentContext.Provider value={agentValue}>
      <div
        data-testid="live-workbench-shell"
      data-ui-typography="system"
      className={`grid h-dvh min-h-0 grid-cols-1 grid-rows-[52px_minmax(0,1fr)] overflow-hidden bg-background text-foreground min-[768px]:grid-cols-[72px_minmax(0,1fr)] ${desktopGridColumns}`}
      >
        <aside className="hidden min-h-0 flex-col border-r border-separator bg-surface min-[768px]:col-start-1 min-[768px]:row-span-2 min-[768px]:flex" aria-label="桌面导航">
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
          {sidebarExpanded ? <div className="min-h-0 flex-1 overflow-hidden">
            <CategorizedNavigation
              activeQuickView={activeQuickView}
              quickViewsOpen={quickViewsOpen}
              onQuickViewsToggle={() => setQuickViewsOpen((value) => !value)}
              onQuickView={selectQuickView}
            />
          </div> : <nav aria-label="工作台导航" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
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
          <div className="border-t border-separator p-2">
            <Popover>
              <Popover.Trigger
                aria-label="打开账户菜单"
                title={sidebarExpanded ? undefined : '账户'}
                className={`flex min-h-11 w-full items-center gap-2 rounded-xl p-1.5 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus ${sidebarExpanded ? 'justify-start' : 'justify-center'}`}
              >
                <AvatarRoot className="size-8 shrink-0"><AvatarFallback>{(props.user.display_name || props.user.username).slice(0, 1).toUpperCase()}</AvatarFallback></AvatarRoot>
                {sidebarExpanded && <>
                  <span className="min-w-0 flex-1"><span className="type-control block truncate">{props.user.display_name || props.user.username}</span><span className="type-label block text-muted">{roleLabel[props.user.role]}</span></span>
                  <Icons.ChevronUp size={15} className="text-muted" aria-hidden="true" />
                </>}
              </Popover.Trigger>
              <Popover.Content placement="right bottom" offset={8} className="z-50 w-56 p-0">
                <Popover.Dialog aria-label="账户菜单" className="p-2">
                  <div className="px-2 py-2">
                    <strong className="type-control block truncate">{props.user.display_name || props.user.username}</strong>
                    <span className="type-meta text-muted">{props.user.username} · {roleLabel[props.user.role]}</span>
                  </div>
                  <Separator className="my-1" />
                  <Button variant="ghost" className="w-full justify-start" onPress={() => navigate('/settings')}><Icons.Settings size={16} aria-hidden="true" />设置</Button>
                  <Separator className="my-1" />
                  <Button variant="ghost" className="w-full justify-start text-danger" aria-label="退出登录" onPress={() => { openclawChat.disconnect(); props.onLogout() }}><Icons.LogOut size={16} aria-hidden="true" />退出登录</Button>
                </Popover.Dialog>
              </Popover.Content>
            </Popover>
          </div>
        </aside>

        <PageHeader
          title={pageTitle}
          className="col-start-1 row-start-1 min-[768px]:col-start-2"
          actions={contentRoute ? <div className="flex items-center gap-1">
            {feedRoute && <Button
              ref={insightsToggleRef}
              size="sm"
              variant="ghost"
              isIconOnly
              data-right-rail-toggle="insights"
              className={`h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none ${visibleRightRailMode === 'insights' ? 'bg-accent/15 text-accent' : 'text-muted'}`}
              aria-label={visibleRightRailMode === 'insights' ? '收起信息概览' : '展开信息概览'}
              aria-expanded={visibleRightRailMode === 'insights'}
              aria-controls="feed-insights-rail"
              isDisabled={openclawChat.isRunning}
              onPress={() => toggleRightRail('insights')}
            ><Icons.ChartNoAxesCombined size={18} aria-hidden="true" /></Button>}
            <Button
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
              onPress={() => toggleRightRail('agent')}
            ><Icons.SplitPanel open={visibleRightRailMode === 'agent'} size={18} aria-hidden="true" /></Button>
          </div> : undefined}
        />

        <main className="col-start-1 row-start-2 min-h-0 min-w-0 overflow-hidden pb-16 min-[768px]:col-start-2 min-[768px]:pb-0">
          {noticeOpen && <div role={props.refreshState === 'failed' || props.refreshState === 'blocked' ? 'alert' : 'status'} className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted">
            <span className="flex-1">{props.refreshMessage}</span>{props.onRetry && <Button size="sm" variant="ghost" onPress={props.onRetry}>重试</Button>}
            <Button size="sm" variant="ghost" isIconOnly aria-label="关闭更新提示" onPress={() => setDismissedNotice(noticeKey)}><Icons.X size={15} /></Button>
          </div>}
          {props.children}
        </main>

        {contentRoute && (railDesktop ? visibleRightRailMode !== 'closed' && <aside
          id={visibleRightRailMode === 'agent' ? 'live-agent-panel' : 'feed-insights-rail'}
          role="complementary"
          aria-label={visibleRightRailMode === 'agent' ? 'OpenClaw 上下文' : '信息概览'}
          className="col-start-3 row-span-2 hidden min-h-0 min-w-0 grid-rows-[52px_minmax(0,1fr)_auto] overflow-x-hidden border-l border-separator bg-surface min-[1440px]:grid"
        >{visibleRightRailMode === 'agent'
            ? <AgentPanelContent open onClose={closeRightRail} chat={openclawChat} configLoading={delegations.isLoading} value={agentValue} api={props.api} userId={props.user.id} />
            : <FeedInsightsPanel open onClose={closeRightRail} api={props.api} userId={props.user.id} preference={feedPreference} query={props.query} />}
        </aside> : <Drawer isOpen={visibleRightRailMode !== 'closed'} onOpenChange={(open) => { if (!open) closeRightRail() }}>
          <Drawer.Trigger aria-hidden="true" className="hidden">打开右侧面板</Drawer.Trigger>
          <Drawer.Backdrop isDismissable={!openclawChat.isRunning} variant="blur" data-testid="right-rail-drawer-backdrop">
            <Drawer.Content placement={mobile ? 'bottom' : 'right'}>
              <Drawer.Dialog
                id={visibleRightRailMode === 'agent' ? 'live-agent-panel' : 'feed-insights-rail'}
                aria-label={visibleRightRailMode === 'agent' ? 'OpenClaw 上下文' : '信息概览'}
                className={`grid min-h-0 min-w-0 grid-rows-[52px_minmax(0,1fr)_auto] overflow-x-hidden border-separator bg-surface p-0 outline-none ${mobile ? 'h-[min(88dvh,720px)] max-h-[88dvh] w-full rounded-t-2xl border-t' : 'h-dvh w-[360px] max-w-[360px] rounded-l-2xl border-l'}`}
              >
                {visibleRightRailMode === 'agent'
                  ? <AgentPanelContent open onClose={closeRightRail} chat={openclawChat} configLoading={delegations.isLoading} value={agentValue} api={props.api} userId={props.user.id} />
                  : <FeedInsightsPanel open onClose={closeRightRail} api={props.api} userId={props.user.id} preference={feedPreference} query={props.query} />}
              </Drawer.Dialog>
            </Drawer.Content>
          </Drawer.Backdrop>
        </Drawer>)}

        <nav aria-label="移动端主导航" className="fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-6 border-t border-separator bg-surface min-[768px]:hidden">
          {navigation.map(({ label, href, icon: Icon }) => <NavLink key={href} to={href} end={href === '/feed'} aria-label={label} className="type-micro flex min-h-11 min-w-11 flex-col items-center justify-center gap-1 text-muted aria-[current=page]:text-accent">
            <Icon size={17} aria-hidden="true" /><span>{label}</span>
          </NavLink>)}
        </nav>
      </div>
  </WorkbenchAgentContext.Provider>
}
