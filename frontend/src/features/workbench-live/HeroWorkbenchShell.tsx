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
  type AgentContextDraftV1,
} from './agentContext'
import { HandoffComposer } from './HandoffComposer'
import { WorkbenchAgentContext, type WorkbenchAgentContextValue } from './workbenchAgentContext'
import { relativeTime } from '../feed/feedModel'
import { toWorkbenchCardModel, workbenchSourceLabels } from './workbenchModel'
import {
  applyQuickView,
  detectActiveQuickView,
  WORKBENCH_QUICK_VIEWS,
  type WorkbenchQuickViewId,
} from './workbenchQuickViews'

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
const sidebarPanelToggleClass = 'inline-flex size-10 shrink-0 items-center justify-center rounded-[var(--inteliscope-radius-card)] bg-accent/15 text-accent transition-colors duration-[var(--inteliscope-motion-standard)] hover:bg-accent/20 hover:text-accent focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none'

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
    <p className="type-label px-3 pb-1 pt-2 text-muted/70">浏览</p>
    {browseNavigation.map((item) => <ExpandedRoute key={item.href} {...item} onNavigate={onNavigate} />)}

    <Button
      size="sm"
      variant="ghost"
      className="type-label mt-3 w-full justify-between px-3 text-muted/70"
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

    <p className="type-label mt-3 px-3 pb-1 pt-2 text-muted/70">管理</p>
    {managementNavigation.map((item) => <ExpandedRoute key={item.href} {...item} onNavigate={onNavigate} />)}
  </nav>
}

function initialWideDesktop() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(min-width: 1200px)').matches
    : false
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

type AgentStatus = '已配置' | '未配置' | '检查失败'

function AgentPanelContent({
  open,
  onClose,
  status,
  value,
  api,
  userId,
}: {
  open: boolean
  onClose: () => void
  status?: AgentStatus
  value: WorkbenchAgentContextValue
  api: ServiceApi
  userId: string
}) {
  const itemQueries = useQueries({
    queries: value.draft.itemIds.map((id) => ({
      queryKey: queryKeys.feedItem(userId, id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.feedItem(id, signal),
      enabled: open,
      retry: false,
    })),
  })
  return <>
    <header className="flex h-[52px] items-center gap-2 border-b border-separator px-4">
      <Icons.Sparkles size={17} aria-hidden="true" />
      <strong className="min-w-0 flex-1 truncate">OpenClaw 上下文</strong>
      {status
        ? <Chip size="sm" color={status === '已配置' ? 'accent' : 'default'} variant="primary"><Chip.Label>{status}</Chip.Label></Chip>
        : <span role="status" aria-busy="true" aria-label="正在检查 Agent 连接"><Skeleton className="h-4 w-8 rounded-lg" /></span>}
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭 Agent 面板" onPress={onClose}>
        <Icons.X size={17} aria-hidden="true" />
      </Button>
    </header>
    {open && <>
      <div className="min-h-0 overflow-y-auto p-4" data-testid="agent-scroll-region">
        <div className="type-meta mb-3 flex justify-between text-muted"><span>已选上下文</span><span>{value.draft.itemIds.length} / 8</span></div>
        {!value.draft.itemIds.length && <Card variant="transparent" className="p-3">
          <Card.Description>从信息卡片加入内容，再生成交给本地 OpenClaw 的确定性提示词。</Card.Description>
        </Card>}
        <div className="grid gap-2">
          {value.draft.itemIds.map((id, index) => {
            const query = itemQueries[index]
            if (!query || query.isPending) return <Card key={id} variant="secondary" className="flex-row items-center gap-3 p-3">
              <Skeleton className="size-8 shrink-0 rounded-full" />
              <span role="status" className="type-meta min-w-0 flex-1 text-muted">正在读取内容</span>
              <Button size="sm" variant="ghost" isIconOnly aria-label="移除正在加载的内容" onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
            </Card>
            if (query.isError || !query.data) return <Card key={id} variant="secondary" className="flex-row items-center gap-3 p-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-default text-muted"><Icons.FileWarning size={15} aria-hidden="true" /></span>
              <span className="type-control min-w-0 flex-1">内容已失效</span>
              <Button size="sm" variant="ghost" isIconOnly aria-label="移除失效内容" onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
            </Card>
            const card = toWorkbenchCardModel(query.data)
            const sourceLabels = workbenchSourceLabels(card, true)
            const removeLabel = card.authorLabel || card.sourceLabel || '所选内容'
            return <Card key={id} variant="secondary" className="flex-row items-center gap-3 p-3">
              <AvatarRoot className="size-8 shrink-0">
                {card.sourceAvatar && <AvatarImage src={card.sourceAvatar} alt={card.source} />}
                <AvatarFallback>{card.source.slice(0, 1).toUpperCase()}</AvatarFallback>
              </AvatarRoot>
              <span className="min-w-0 flex-1">
                <span className="type-meta flex min-w-0 items-center gap-1.5 text-muted">
                  {sourceLabels.map((label, labelIndex) => <Fragment key={label}>
                    {labelIndex > 0 && <span aria-hidden="true">·</span>}
                    <span className="truncate">{label}</span>
                  </Fragment>)}
                  <span aria-hidden="true">·</span>
                  <span className="shrink-0">{relativeTime(card.publishedAt)}</span>
                </span>
                <span className="type-control mt-0.5 block truncate">{card.primaryText}</span>
              </span>
              <Button size="sm" variant="ghost" isIconOnly aria-label={`移除 ${removeLabel}`} onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
            </Card>
          })}
        </div>
      </div>
      <HandoffComposer value={value} />
    </>}
  </>
}

export function HeroWorkbenchShell(props: HeroWorkbenchShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const contentRoute = ['/feed', '/saved', '/history'].includes(location.pathname)
  const pageTitle = location.pathname.endsWith('/subscriptions') ? '订阅与来源' : location.pathname.endsWith('/agents') ? '助手连接' : location.pathname.endsWith('/settings') ? '设置' : location.pathname.endsWith('/saved') ? '收藏' : location.pathname.endsWith('/history') ? '历史' : '信息流'
  const agentToggleRef = useRef<HTMLButtonElement>(null)
  const tabletNavToggleRef = useRef<HTMLDivElement>(null)
  const [wideDesktop, setWideDesktop] = useState(initialWideDesktop)
  const [extraWideDesktop, setExtraWideDesktop] = useState(initialExtraWideDesktop)
  const [mobile, setMobile] = useState(initialMobile)
  const [agentOpen, setAgentOpen] = useState(initialWideDesktop)
  const [tabletNavOpen, setTabletNavOpen] = useState(false)
  const [quickViewsOpen, setQuickViewsOpen] = useState(true)
  const [sidebarState, setSidebarState] = useState(() => ({ userId: props.user.id, value: readSidebarPreference(props.user.id) }))
  const [feedPreferenceState, setFeedPreferenceState] = useState(() => ({ userId: props.user.id, value: readFeedPreference(props.user.id) }))
  const [draft, setDraft] = useState(() => readAgentContextDraft(props.user.id))
  const [dismissedNotice, setDismissedNotice] = useState('')
  const delegations = useQuery({ queryKey: queryKeys.agentDelegations(props.user.id), queryFn: ({ signal }) => props.api.agentDelegations(signal), retry: false, enabled: contentRoute })
  const agentStatus: AgentStatus | undefined = delegations.isLoading
    ? undefined
    : delegations.isError
    ? '检查失败'
    : delegations.data?.enabled && delegations.data.connections.some((connection) => connection.status === 'active')
      ? '已配置'
      : '未配置'
  const refreshing = props.refreshState === 'pending' || props.refreshState === 'queued' || props.refreshState === 'running'
  const noticeKey = props.refreshEventKey || `${props.refreshState}:${props.refreshMessage ?? ''}`
  const noticeOpen = Boolean(props.refreshMessage) && !refreshing && dismissedNotice !== noticeKey
  const sidebarPreference = sidebarState.userId === props.user.id ? sidebarState.value : readSidebarPreference(props.user.id)
  const feedPreference = feedPreferenceState.userId === props.user.id ? feedPreferenceState.value : readFeedPreference(props.user.id)
  const activeQuickView = detectActiveQuickView(feedPreference)
  const sidebarExpanded = extraWideDesktop && sidebarPreference === 'expanded'
  const desktopSidebarColumn = sidebarExpanded ? 'min-[1360px]:grid-cols-[232px_minmax(0,1fr)]' : 'min-[1360px]:grid-cols-[72px_minmax(0,1fr)]'
  const desktopGridColumns = contentRoute && wideDesktop && agentOpen
    ? `min-[1200px]:grid-cols-[72px_minmax(640px,1fr)_360px] ${sidebarExpanded ? 'min-[1360px]:grid-cols-[232px_minmax(640px,1fr)_360px]' : 'min-[1360px]:grid-cols-[72px_minmax(640px,1fr)_360px]'}`
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

  const persistDraft = useCallback((next: AgentContextDraftV1) => {
    setDraft(writeAgentContextDraft(props.user.id, next))
  }, [props.user.id])

  const agentValue = useMemo<WorkbenchAgentContextValue>(() => ({
    draft,
    toggleItem: (id) => persistDraft(updateAgentContextDraft(draft, id)),
    removeItem: (id) => persistDraft({ ...draft, itemIds: draft.itemIds.filter((value) => value !== id) }),
    setQuestion: (question) => persistDraft({ ...draft, question }),
    setModelPreference: (modelPreference) => persistDraft({ ...draft, modelPreference }),
  }), [draft, persistDraft])

  const closeAgent = useCallback(() => {
    setAgentOpen(false)
    window.requestAnimationFrame(() => agentToggleRef.current?.focus())
  }, [])

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
    const desktopMedia = window.matchMedia('(min-width: 1200px)')
    const extraWideMedia = window.matchMedia('(min-width: 1360px)')
    const mobileMedia = window.matchMedia('(max-width: 767px)')
    const changeDesktop = (event: MediaQueryListEvent) => {
      setWideDesktop(event.matches)
      setAgentOpen(contentRoute && event.matches)
    }
    const changeExtraWide = (event: MediaQueryListEvent) => {
      setExtraWideDesktop(event.matches)
      if (event.matches) setTabletNavOpen(false)
    }
    const changeMobile = (event: MediaQueryListEvent) => setMobile(event.matches)
    desktopMedia.addEventListener('change', changeDesktop)
    extraWideMedia.addEventListener('change', changeExtraWide)
    mobileMedia.addEventListener('change', changeMobile)
    return () => {
      desktopMedia.removeEventListener('change', changeDesktop)
      extraWideMedia.removeEventListener('change', changeExtraWide)
      mobileMedia.removeEventListener('change', changeMobile)
    }
  }, [contentRoute])

  useEffect(() => {
    if (!agentOpen || !wideDesktop) return
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeAgent()
    }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [agentOpen, closeAgent, wideDesktop])

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
                className={sidebarPanelToggleClass}
                aria-label="收起侧栏"
                aria-expanded="true"
                onClick={toggleSidebar}
              ><Icons.SplitPanel open size={18} aria-hidden="true" /></button>
            </> : <button
              type="button"
              data-sidebar-panel-toggle
              data-inteliscope-mark-trigger
              className={sidebarPanelToggleClass}
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
                className={sidebarPanelToggleClass}
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
                  <Button variant="ghost" className="w-full justify-start text-danger" aria-label="退出登录" onPress={props.onLogout}><Icons.LogOut size={16} aria-hidden="true" />退出登录</Button>
                </Popover.Dialog>
              </Popover.Content>
            </Popover>
          </div>
        </aside>

        <PageHeader
          title={pageTitle}
          className="col-start-1 row-start-1 min-[768px]:col-start-2"
          actions={contentRoute ? <Button
            ref={agentToggleRef}
            size="sm"
            variant="ghost"
            isIconOnly
            data-agent-toggle-visual="quiet-studio"
            data-agent-open={agentOpen ? 'true' : 'false'}
            className="h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 data-[agent-open=true]:bg-accent/15 data-[agent-open=true]:text-accent motion-reduce:transform-none"
            aria-label={agentOpen ? '收起 Agent 面板' : '展开 Agent 面板'}
            aria-expanded={agentOpen}
            aria-controls="live-agent-panel"
            onPress={() => setAgentOpen((value) => !value)}
          ><Icons.SplitPanel open={agentOpen} size={18} aria-hidden="true" /></Button> : undefined}
        />

        <main className="col-start-1 row-start-2 min-h-0 min-w-0 overflow-hidden pb-16 min-[768px]:col-start-2 min-[768px]:pb-0">
          {noticeOpen && <div role={props.refreshState === 'failed' || props.refreshState === 'blocked' ? 'alert' : 'status'} className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted">
            <span className="flex-1">{props.refreshMessage}</span>{props.onRetry && <Button size="sm" variant="ghost" onPress={props.onRetry}>重试</Button>}
            <Button size="sm" variant="ghost" isIconOnly aria-label="关闭更新提示" onPress={() => setDismissedNotice(noticeKey)}><Icons.X size={15} /></Button>
          </div>}
          {props.children}
        </main>

        {contentRoute && (wideDesktop ? agentOpen && <aside
          id="live-agent-panel"
          role="complementary"
          aria-label="OpenClaw 上下文"
          className="col-start-3 row-span-2 hidden min-h-0 grid-rows-[52px_minmax(0,1fr)_auto] border-l border-separator bg-surface min-[1200px]:grid"
        ><AgentPanelContent open={agentOpen} onClose={closeAgent} status={agentStatus} value={agentValue} api={props.api} userId={props.user.id} /></aside> : <Drawer isOpen={agentOpen} onOpenChange={(open) => open ? setAgentOpen(true) : closeAgent()}>
          <Drawer.Trigger aria-hidden="true" className="hidden">打开 Agent 面板</Drawer.Trigger>
          <Drawer.Backdrop isDismissable variant="blur" data-testid="agent-drawer-backdrop">
            <Drawer.Content placement={mobile ? 'bottom' : 'right'}>
              <Drawer.Dialog
                id="live-agent-panel"
                aria-label="OpenClaw 上下文"
                className={`grid min-h-0 grid-rows-[52px_minmax(0,1fr)_auto] border-separator bg-surface p-0 outline-none ${mobile ? 'h-[min(78dvh,640px)] max-h-[78dvh] w-full rounded-t-2xl border-t' : 'h-dvh w-[360px] max-w-[360px] rounded-l-2xl border-l'}`}
              >
                <AgentPanelContent open onClose={closeAgent} status={agentStatus} value={agentValue} api={props.api} userId={props.user.id} />
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
