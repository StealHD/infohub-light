import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
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
  AvatarRoot,
  Button,
  Card,
  Chip,
  Drawer,
  Icons,
  ListBox,
  Popover,
  SearchField,
  Select,
  Separator,
  Skeleton,
  TextArea,
  Tooltip,
} from '../../design-system'
import {
  buildAgentHandoffPrompt,
  readAgentContextDraft,
  updateAgentContextDraft,
  writeAgentContextDraft,
  type AgentContextDraftV1,
  type AgentModelPreference,
} from './agentContext'
import { WorkbenchAgentContext, type WorkbenchAgentContextValue } from './workbenchAgentContext'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'
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

function ExpandedRoute({ href, label, icon: Icon, onNavigate }: typeof navigation[number] & { onNavigate?: () => void }) {
  return <NavLink
    to={href}
    end={href === '/feed'}
    aria-label={label}
    onClick={onNavigate}
    className={({ isActive }) => `type-control mb-0.5 flex min-h-10 items-center gap-3 rounded-xl px-3 text-muted transition-colors hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus${isActive ? ' bg-default text-foreground' : ''}`}
  ><Icon size={17} aria-hidden="true" /><span>{label}</span></NavLink>
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
      {WORKBENCH_QUICK_VIEWS.map((view) => <Button
        key={view.id}
        size="sm"
        variant="ghost"
        className={`type-control min-h-9 justify-start gap-3 px-3 ${activeQuickView === view.id ? 'bg-default text-foreground' : 'text-muted'}`}
        aria-label={view.label}
        onPress={() => onQuickView(view.id)}
      ><span className={`size-1.5 rounded-full ${activeQuickView === view.id ? 'bg-accent' : 'bg-muted/35'}`} aria-hidden="true" />{view.label}</Button>)}
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
}: {
  open: boolean
  onClose: () => void
  status?: AgentStatus
  value: WorkbenchAgentContextValue
}) {
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2800)
    return () => window.clearTimeout(timer)
  }, [notice])

  async function copyHandoff() {
    try {
      await navigator.clipboard.writeText(buildAgentHandoffPrompt(value.draft))
      setNotice('交接提示词已复制')
    } catch {
      setNotice('无法写入剪贴板，请手动复制')
    }
  }

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
          {value.draft.itemIds.map((id, index) => <Card key={id} variant="secondary" className="flex-row items-center gap-2 p-3">
            <span className="type-meta text-muted">{String(index + 1).padStart(2, '0')}</span>
            <code className="type-meta min-w-0 flex-1 truncate">{id}</code>
            <Button size="sm" variant="ghost" isIconOnly aria-label={`移除 ${id}`} onPress={() => value.removeItem(id)}><Icons.X size={14} /></Button>
          </Card>)}
        </div>
      </div>
      <div className="border-t border-separator p-3">
        <div data-testid="agent-handoff-composer" className="rounded-2xl border border-separator bg-surface-secondary p-2 shadow-sm focus-within:border-border">
          <TextArea
            fullWidth
            variant="secondary"
            className="type-body"
            aria-label="交给 OpenClaw 的问题"
            value={value.draft.question}
            maxLength={1200}
            rows={3}
            placeholder="要求后续处理…"
            onChange={(event) => value.setQuestion(event.target.value)}
          />
          <div className="mt-2 flex min-w-0 items-center gap-1.5 px-1 pb-0.5">
            <Tooltip delay={300}>
              <Tooltip.Trigger aria-label="交接模式说明" className="type-label inline-flex min-h-8 shrink-0 items-center gap-1 rounded-lg px-1.5 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus">
                <Icons.Waypoints size={13} aria-hidden="true" />交接模式
              </Tooltip.Trigger>
              <Tooltip.Content>只复制交接提示词，由本地 OpenClaw 执行。</Tooltip.Content>
            </Tooltip>
            <span className="type-label shrink-0 text-muted">{value.draft.itemIds.length}/8</span>
            <Select
              aria-label="模型偏好"
              selectedKey={value.draft.modelPreference}
              onSelectionChange={(key) => key !== null && value.setModelPreference(String(key) as AgentModelPreference)}
              className="min-w-0 flex-1"
            >
              <Select.Trigger aria-label="模型偏好" className="type-label min-h-8 border-0 bg-transparent px-1.5 shadow-none">
                <Select.Value />
                <Select.Indicator><Icons.ChevronDown size={12} aria-hidden="true" /></Select.Indicator>
              </Select.Trigger>
              <Select.Popover>
                <ListBox items={[
                  { id: 'auto', label: '自动 · OpenClaw 决定' },
                  { id: 'fast', label: '速度优先' },
                  { id: 'deep', label: '深度分析' },
                ]}>{(item) => <ListBox.Item id={item.id} textValue={item.label}>{item.label}</ListBox.Item>}</ListBox>
              </Select.Popover>
            </Select>
            <span role="status" aria-label="交接状态" aria-live="polite" className="type-label min-w-0 truncate text-muted">{notice}</span>
            <Button
              size="sm"
              isIconOnly
              className="size-9 shrink-0 rounded-full active:scale-95 motion-reduce:transform-none"
              isDisabled={!value.draft.itemIds.length}
              aria-label="复制交接提示词"
              onPress={() => void copyHandoff()}
            ><Icons.ArrowUp size={16} aria-hidden="true" /></Button>
          </div>
        </div>
      </div>
    </>}
  </>
}

export function HeroWorkbenchShell(props: HeroWorkbenchShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const contentRoute = ['/feed', '/saved', '/history'].includes(location.pathname)
  const feedRoute = location.pathname === '/feed'
  const collectionHeaderControls = contentRoute && !feedRoute
  const pageTitle = location.pathname.endsWith('/subscriptions') ? '订阅' : location.pathname.endsWith('/agents') ? '助手连接' : location.pathname.endsWith('/settings') ? '设置' : location.pathname.endsWith('/saved') ? '收藏' : location.pathname.endsWith('/history') ? '历史' : '信息流'
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

  function requestRefresh() {
    window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
    props.onRefresh?.()
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
              <Button size="sm" variant="ghost" isIconOnly aria-label="收起侧栏" onPress={toggleSidebar}>
                <Icons.PanelLeftClose size={16} aria-hidden="true" />
              </Button>
            </> : <Button
              size="sm"
              variant="ghost"
              isIconOnly
              data-inteliscope-mark-trigger
              aria-label="展开侧栏"
              onPress={toggleSidebar}
            ><Icons.InteliscopeMark size={21} aria-hidden="true" /></Button> : <Popover isOpen={tabletNavOpen} onOpenChange={changeTabletNavigation}>
              <Popover.Trigger
                ref={tabletNavToggleRef}
                data-inteliscope-mark-trigger
                aria-label="展开导航"
                className="inline-flex size-10 items-center justify-center rounded-xl text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
              ><Icons.InteliscopeMark size={21} aria-hidden="true" /></Popover.Trigger>
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
            {browseNavigation.map(({ label, href, icon: Icon }) => <NavLink
              key={href}
              to={href}
              end={href === '/feed'}
              aria-label={label}
              className={({ isActive }) => `mb-1 flex min-h-11 items-center justify-center rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus${isActive ? ' bg-default text-foreground' : ''}`}
            ><Icon size={18} aria-hidden="true" /></NavLink>)}
            <Separator className="my-2" />
            {managementNavigation.map(({ label, href, icon: Icon }) => <NavLink
              key={href}
              to={href}
              aria-label={label}
              className={({ isActive }) => `mb-1 flex min-h-11 items-center justify-center rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus${isActive ? ' bg-default text-foreground' : ''}`}
            ><Icon size={18} aria-hidden="true" /></NavLink>)}
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

        <header
          data-header-visual={feedRoute ? 'quiet-studio' : undefined}
          className={`col-start-1 row-start-1 flex h-[52px] items-center gap-2 border-b border-separator px-3 min-[768px]:col-start-2 min-[768px]:px-4 ${feedRoute ? 'bg-surface/95 supports-[backdrop-filter:blur(1px)]:backdrop-blur-lg' : 'bg-surface'}`}
        >
          {contentRoute ? <h1 className="type-page-title shrink-0">{pageTitle}</h1> : <strong className="type-page-title shrink-0">{pageTitle}</strong>}
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
          >{feedRoute
            ? <Icons.SplitPanel open={agentOpen} size={18} aria-hidden="true" />
            : agentOpen
              ? <Icons.PanelRightClose size={17} aria-hidden="true" />
              : <Icons.PanelRightOpen size={17} aria-hidden="true" />}</Button>}
        </header>

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
        ><AgentPanelContent open={agentOpen} onClose={closeAgent} status={agentStatus} value={agentValue} /></aside> : <Drawer isOpen={agentOpen} onOpenChange={(open) => open ? setAgentOpen(true) : closeAgent()}>
          <Drawer.Trigger aria-hidden="true" className="hidden">打开 Agent 面板</Drawer.Trigger>
          <Drawer.Backdrop isDismissable variant="blur" data-testid="agent-drawer-backdrop">
            <Drawer.Content placement={mobile ? 'bottom' : 'right'}>
              <Drawer.Dialog
                id="live-agent-panel"
                aria-label="OpenClaw 上下文"
                className={`grid min-h-0 grid-rows-[52px_minmax(0,1fr)_auto] border-separator bg-surface p-0 outline-none ${mobile ? 'h-[min(78dvh,640px)] max-h-[78dvh] w-full rounded-t-2xl border-t' : 'h-dvh w-[360px] max-w-[360px] rounded-l-2xl border-l'}`}
              >
                <AgentPanelContent open onClose={closeAgent} status={agentStatus} value={agentValue} />
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
