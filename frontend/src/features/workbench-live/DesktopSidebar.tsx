import { createPortal } from 'react-dom'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import type { User } from '../../api/types'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import {
  anchoredTooltipProps,
  AvatarFallback,
  AvatarRoot,
  Button,
  Icons,
  Popover,
  Separator,
  Tooltip,
} from '../../design-system'
import { settingsSectionsForRole } from '../admin-heroui/settingsSections'
import { settingsReturnStateForLocation } from '../settings/settingsReturnState'
import { WORKBENCH_QUICK_VIEWS, type WorkbenchQuickViewId } from './workbenchQuickViews'

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
  role: User['role']
  settingsDirectory?: boolean
}

type DesktopSidebarProps = {
  activeQuickView: WorkbenchQuickViewId | null
  extraWideDesktop: boolean
  onLogout: () => void
  onQuickView: (id: WorkbenchQuickViewId) => void
  quickViewsOpen: boolean
  onQuickViewsToggle: () => void
  sidebarExpanded: boolean
  onSidebarToggle: () => void
  user: User
}

const sidebarItemBase = 'type-control mb-0.5 flex w-full items-center rounded-xl text-muted transition-colors duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none'
const sidebarPanelToggleClass = (open: boolean, desktop = true) => `${desktop ? 'sidebar-desktop-toggle ' : ''}inline-flex size-10 items-center justify-center rounded-[var(--inteliscope-radius-card)] transition-[inset-inline-end,color,background-color] duration-[var(--inteliscope-motion-standard)] focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none ${open ? 'bg-accent/15 text-accent hover:bg-accent/20 hover:text-accent' : 'text-muted hover:bg-default hover:text-foreground'}`

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
  const content = <>{leading}{!compact && <span className="truncate whitespace-nowrap">{label}</span>}</>
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

type SettingsDirectorySurfaceProps = {
  clearTimers: () => void
  closeDirectory: (returnFocus?: boolean) => void
  location: Parameters<typeof settingsReturnStateForLocation>[0]
  onNavigate?: () => void
  position: { left: number; top: number }
  scheduleClose: () => void
  sections: ReadonlyArray<{ id: string; label: string }>
  surfaceRef: RefObject<HTMLDivElement | null>
}

function SettingsDirectorySurface({ clearTimers, closeDirectory, location, onNavigate, position, scheduleClose, sections, surfaceRef }: SettingsDirectorySurfaceProps) {
  return createPortal(
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
        if (event.currentTarget.contains(next)) return
        scheduleClose()
      }}
    >
      <p className="type-label px-3 pb-1 pt-1 text-muted">设置目录</p>
      {sections.map((section) => <NavLink
        key={section.id}
        to={`/settings#${section.id}`}
        state={settingsReturnStateForLocation(location)}
        aria-current={location.hash === `#${section.id}` ? 'location' : undefined}
        className="type-control min-h-9 rounded-xl px-3 py-2 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus aria-[current=location]:bg-accent/10 aria-[current=location]:text-accent"
        onClick={() => { closeDirectory(); onNavigate?.() }}
      >{section.label}</NavLink>)}
    </div>,
    document.body,
  )
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

  const closeDirectory = useCallback((returnFocus = false) => {
    clearTimers()
    setOpen(false)
    if (!returnFocus) return
    suppressFocusOpenRef.current = true
    window.requestAnimationFrame(() => {
      triggerRef.current?.focus()
      window.requestAnimationFrame(() => { suppressFocusOpenRef.current = false })
    })
  }, [clearTimers])

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

  useLayoutEffect(() => {
    if (!open) return
    const updatePosition = () => {
      const trigger = triggerRef.current
      if (!trigger) return
      const rect = trigger.getBoundingClientRect()
      setPosition({ left: rect.right + 8, top: Math.min(Math.max(8, rect.top), Math.max(8, window.innerHeight - 300)) })
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
    ? <SettingsDirectorySurface clearTimers={clearTimers} closeDirectory={closeDirectory} location={location} onNavigate={onNavigate} position={position} scheduleClose={scheduleClose} sections={sections} surfaceRef={surfaceRef} />
    : null

  return <>
    <NavLink
      ref={triggerRef}
      to="/settings"
      state={settingsReturnStateForLocation(location)}
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
      onClick={() => { closeDirectory(); onNavigate?.() }}
    >
      <Icons.Settings size={compact ? 18 : 17} aria-hidden="true" />
      {!compact && <span className="truncate whitespace-nowrap">设置</span>}
    </NavLink>
    {surface}
  </>
}

function CategorizedNavigation({ activeQuickView, quickViewsOpen, onQuickViewsToggle, onQuickView, onNavigate, role, settingsDirectory = true }: CategorizedNavigationProps) {
  return <nav aria-label="分类导航内容" className="quiet-scroll-region sidebar-scroll-region h-full min-h-0 w-[var(--inteliscope-width-workbench-sidebar-expanded)] overflow-x-hidden overflow-y-auto px-2 pb-3">
    <p className="type-label px-3 pb-1 pt-2 text-muted">浏览</p>
    {browseNavigation.map(({ icon: Icon, ...item }) => <SidebarNavItem key={item.href} {...item} leading={<Icon size={17} aria-hidden="true" />} onActivate={onNavigate} />)}
    <Button size="sm" variant="ghost" className="type-label mt-3 w-full justify-between px-3 text-muted" aria-expanded={quickViewsOpen} onPress={onQuickViewsToggle}>常用视图<Icons.ChevronDown size={14} className={`transition-transform ${quickViewsOpen ? '' : '-rotate-90'}`} /></Button>
    {quickViewsOpen && <div className="grid gap-0.5">
      {WORKBENCH_QUICK_VIEWS.map((view) => <SidebarNavItem key={view.id} label={view.label} selected={activeQuickView === view.id} leading={<span className={`size-1.5 rounded-full ${activeQuickView === view.id ? 'bg-accent' : 'bg-muted/35'}`} aria-hidden="true" />} onActivate={() => onQuickView(view.id)} />)}
    </div>}
    <p className="type-label mt-3 px-3 pb-1 pt-2 text-muted">管理</p>
    {managementNavigation.map(({ icon: Icon, ...item }) => item.id === 'settings' && settingsDirectory
      ? <SettingsSidebarNavigationItem key={item.href} compact={false} role={role} onNavigate={onNavigate} />
      : <SidebarNavItem key={item.href} {...item} leading={<Icon size={17} aria-hidden="true" />} onActivate={onNavigate} />)}
  </nav>
}

function CompactNavigation({ role }: { role: User['role'] }) {
  return <nav aria-label="工作台导航" className="quiet-scroll-region sidebar-scroll-region h-full min-h-0 w-[var(--inteliscope-width-workbench-sidebar-collapsed)] overflow-x-hidden overflow-y-auto px-2 py-2">
    {browseNavigation.map(({ label, href, icon: Icon }) => <SidebarNavItem key={href} href={href} end={href === '/feed'} compact label={label} leading={<Icon size={18} aria-hidden="true" />} />)}
    <Separator className="my-2" />
    {managementNavigation.map(({ id, label, href, icon: Icon }) => id === 'settings'
      ? <SettingsSidebarNavigationItem key={href} compact role={role} />
      : <SidebarNavItem key={href} href={href} compact label={label} leading={<Icon size={18} aria-hidden="true" />} />)}
  </nav>
}

function SidebarAccount({ expanded, user, onLogout }: { expanded: boolean; user: User; onLogout: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [documentationMenuOpen, setDocumentationMenuOpen] = useState(false)
  const displayName = user.display_name || user.username
  const compactLayerProps = expanded ? {} : { 'aria-hidden': true, inert: true }

  useEffect(() => {
    if (expanded) return
    const frame = window.requestAnimationFrame(() => setDocumentationMenuOpen(false))
    return () => window.cancelAnimationFrame(frame)
  }, [expanded])

  return <div data-sidebar-account-strip className="sidebar-account-strip relative h-[var(--inteliscope-size-sidebar-footer)] shrink-0 overflow-hidden border-t border-separator p-2">
    <div className="sidebar-account-canvas absolute inset-0 flex h-full w-[var(--inteliscope-width-workbench-sidebar-expanded)] items-center gap-1 px-2">
      <Popover isOpen={accountMenuOpen} onOpenChange={setAccountMenuOpen}>
        <Popover.Trigger aria-label="打开账户菜单" title={expanded ? undefined : '账户'} className="sidebar-account-trigger flex h-12 min-w-0 w-[175px] items-center gap-2 rounded-xl p-1.5 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus">
          <span data-sidebar-account-avatar className="sidebar-account-avatar flex size-8 shrink-0 items-center justify-center"><AvatarRoot className="size-8"><AvatarFallback>{displayName.slice(0, 1).toUpperCase()}</AvatarFallback></AvatarRoot></span>
          <span data-sidebar-account-copy className="min-w-0 flex-1" aria-hidden={!expanded}><span className="type-control block truncate">{displayName}</span><span className="type-label block truncate text-muted">{roleLabel[user.role]}</span></span>
        </Popover.Trigger>
        <Popover.Content data-account-menu-surface data-sidebar-menu-direction="up" placement="top start" offset={8} containerPadding={12} className="z-50 w-52 p-0">
          <Popover.Dialog aria-label="账户菜单" className="p-2">
            <div className="px-2 py-2"><strong className="type-control block truncate">{displayName}</strong><span className="type-meta text-muted">{user.username} · {roleLabel[user.role]}</span></div>
            <Separator className="my-1" />
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/users') }}><Icons.Users size={16} aria-hidden="true" />账户与成员</Button>
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/settings', { state: settingsReturnStateForLocation(location) }) }}><Icons.Settings size={16} aria-hidden="true" />设置</Button>
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/manual') }}><Icons.BookOpen size={16} aria-hidden="true" />操作手册</Button>
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/changelog') }}><Icons.ScrollText size={16} aria-hidden="true" />更新日志</Button>
            <a href={PRODUCT_RELEASES_URL} target="_blank" rel="noopener noreferrer" className="type-control flex min-h-9 w-full items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus" onClick={() => setAccountMenuOpen(false)}><Icons.Rocket size={16} aria-hidden="true" />Release 发布页<Icons.ExternalLink className="ml-auto" size={13} aria-hidden="true" /></a>
            <Separator className="my-1" />
            <Button variant="ghost" className="w-full justify-start text-danger" aria-label="退出登录" onPress={onLogout}><Icons.LogOut size={16} aria-hidden="true" />退出登录</Button>
          </Popover.Dialog>
        </Popover.Content>
      </Popover>
      <div {...compactLayerProps} className="sidebar-account-documentation">
        <Popover isOpen={documentationMenuOpen} onOpenChange={setDocumentationMenuOpen}>
          <Popover.Trigger aria-label="打开文档与发布菜单" title="文档与发布" className="flex size-9 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"><Icons.BookMarked size={16} aria-hidden="true" /></Popover.Trigger>
          <Popover.Content data-documentation-menu-surface data-sidebar-menu-direction="up" placement="top end" offset={8} crossOffset={-3} containerPadding={12} className="z-50 w-52 p-0">
            <Popover.Dialog aria-label="文档与发布菜单" className="p-2">
              <Button variant="ghost" className="w-full justify-start" onPress={() => { setDocumentationMenuOpen(false); navigate('/manual') }}><Icons.BookOpen size={16} aria-hidden="true" />操作手册</Button>
              <Button variant="ghost" className="w-full justify-start" onPress={() => { setDocumentationMenuOpen(false); navigate('/changelog') }}><Icons.ScrollText size={16} aria-hidden="true" />更新日志</Button>
              <a href={PRODUCT_RELEASES_URL} target="_blank" rel="noopener noreferrer" className="type-control flex min-h-9 w-full items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus" onClick={() => setDocumentationMenuOpen(false)}><Icons.Rocket size={16} aria-hidden="true" />Release 发布页<Icons.ExternalLink className="ml-auto" size={13} aria-hidden="true" /></a>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
      </div>
    </div>
  </div>
}

export function DesktopSidebar({ activeQuickView, extraWideDesktop, onLogout, onQuickView, quickViewsOpen, onQuickViewsToggle, sidebarExpanded, onSidebarToggle, user }: DesktopSidebarProps) {
  const [tabletNavOpen, setTabletNavOpen] = useState(false)
  const tabletNavToggleRef = useRef<HTMLDivElement>(null)
  const changeTabletNavigation = useCallback((open: boolean) => {
    setTabletNavOpen(open)
    if (!open) window.requestAnimationFrame(() => tabletNavToggleRef.current?.focus())
  }, [])
  const collapsedLayerProps = sidebarExpanded ? { 'aria-hidden': true, inert: true } : {}
  const expandedLayerProps = sidebarExpanded ? {} : { 'aria-hidden': true, inert: true }

  return <aside data-desktop-sidebar data-sidebar-state={sidebarExpanded ? 'expanded' : 'collapsed'} className="hidden min-h-0 flex-col overflow-x-hidden border-r border-separator bg-surface min-[768px]:col-start-1 min-[768px]:row-span-2 min-[768px]:flex" aria-label="桌面导航">
    {extraWideDesktop ? <>
      <div data-sidebar-header className="relative flex h-[var(--inteliscope-size-page-header)] shrink-0 overflow-hidden">
        <div data-sidebar-brand className="sidebar-expanded-canvas flex h-full w-[var(--inteliscope-width-workbench-sidebar-expanded)] items-center gap-2 px-3" aria-hidden={!sidebarExpanded}><Icons.InteliscopeMark size={20} aria-hidden="true" /><span className="type-page-title min-w-0 flex-1 truncate">Inscope</span></div>
        <button type="button" data-sidebar-panel-toggle data-inteliscope-mark-trigger className={sidebarPanelToggleClass(sidebarExpanded)} aria-label={sidebarExpanded ? '收起侧栏' : '展开侧栏'} aria-expanded={sidebarExpanded} onClick={onSidebarToggle}><Icons.SplitPanel open={sidebarExpanded} size={18} aria-hidden="true" /></button>
      </div>
      <div data-sidebar-navigation-frame className="relative min-h-0 flex-1 overflow-hidden">
        <div data-sidebar-layer="collapsed" {...collapsedLayerProps} className="sidebar-collapsed-layer absolute inset-y-0 left-0">{<CompactNavigation role={user.role} />}</div>
        <div data-sidebar-layer="expanded" {...expandedLayerProps} className="sidebar-expanded-layer absolute inset-y-0 left-0"><CategorizedNavigation activeQuickView={activeQuickView} quickViewsOpen={quickViewsOpen} onQuickViewsToggle={onQuickViewsToggle} onQuickView={onQuickView} role={user.role} /></div>
      </div>
      <SidebarAccount expanded={sidebarExpanded} user={user} onLogout={onLogout} />
    </> : <>
      <div className="type-page-title flex h-[var(--inteliscope-size-page-header)] shrink-0 items-center justify-center px-3">
        <Popover isOpen={tabletNavOpen} onOpenChange={changeTabletNavigation}>
          <Popover.Trigger ref={tabletNavToggleRef} data-sidebar-panel-toggle data-inteliscope-mark-trigger aria-label="展开导航" aria-expanded={tabletNavOpen} className={sidebarPanelToggleClass(tabletNavOpen, false)}><Icons.SplitPanel open={tabletNavOpen} size={18} aria-hidden="true" /></Popover.Trigger>
          <Popover.Content placement="right top" offset={8} className="z-50 w-[260px] p-0">
            <Popover.Dialog aria-label="分类导航" className="max-h-[calc(100dvh-24px)] overflow-hidden rounded-2xl border border-separator bg-surface p-0">
              <div className="flex h-[var(--inteliscope-size-page-header)] items-center gap-2 border-b border-separator px-4"><Icons.InteliscopeMark size={20} aria-hidden="true" /><strong className="min-w-0 flex-1 truncate">Inscope</strong></div>
              <CategorizedNavigation activeQuickView={activeQuickView} quickViewsOpen={quickViewsOpen} onQuickViewsToggle={onQuickViewsToggle} onQuickView={(id) => { onQuickView(id); changeTabletNavigation(false) }} onNavigate={() => changeTabletNavigation(false)} role={user.role} settingsDirectory={false} />
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
      </div>
      <CompactNavigation role={user.role} />
      <SidebarAccount expanded={false} user={user} onLogout={onLogout} />
    </>}
  </aside>
}
