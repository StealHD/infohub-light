import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { FeedItem, User } from '../../api/types'
import { sidebarPreferenceKey } from '../../app/sidebarPreference'
import { DesignSystemProvider } from '../../design-system'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import {
  HeroWorkbenchShell,
} from './HeroWorkbenchShell'
import { calculateFeedInsightsLayout, canFloatFeedInsights } from './feedInsightsLayout'

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() { return values.size },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => { values.delete(key) },
    setItem: (key, value) => { values.set(key, String(value)) },
  }
}

function useViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn((query: string): MediaQueryList => {
      const min = query.match(/min-width:\s*(\d+(?:\.\d+)?)px/)
      const max = query.match(/max-width:\s*(\d+(?:\.\d+)?)px/)
      const matches = query.includes('prefers-reduced-motion')
        ? false
        : (!min || width >= Number(min[1])) && (!max || width <= Number(max[1]))
      return { matches, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }
    }),
  })
}

function contextItem(id: string, author = 'Tibo', source = 'X · @thsottiaux'): FeedItem {
  return {
    id,
    title: '@thsottiaux: Oops... I did it again...',
    url: `https://example.com/${id}`,
    source_type: 'apify_social',
    presentation: {
      version: 2,
      source: { id: 'source-x', catalog_type: 'apify_social', platform: 'x', name: source },
      author: { name: author, kind: 'person' },
      timing: { published_at: '2026-07-18T08:00:00Z', fetched_at: '2026-07-18T08:05:00Z' },
      links: { canonical_url: `https://example.com/${id}`, source_url: 'https://example.com/source' },
      content: { title: '@thsottiaux: Oops... I did it again...', title_origin: 'generated', excerpt: 'Oops... I did it again.', content_kind: 'post_body', excerpt_truncated: false },
      taxonomy: { channel: '其他', configured_topics: [], inferred_topics: [], topics: [], entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'fallback', score: 0, signal_strength: 'unknown', signal_type: 'unknown', summary_zh: 'Oops... I did it again.' },
    },
  }
}

const api = {
  agentDelegations: vi.fn().mockResolvedValue({ enabled: true, subscription_writes_enabled: false, connections: [], mcp_url: '/mcp', openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5 }),
  feedItem: vi.fn().mockImplementation((id: string) => Promise.resolve(contextItem(id))),
  latestFeed: vi.fn().mockResolvedValue({ generated_at: '2026-07-18T08:05:00Z', updated_at: '2026-07-18T08:05:00Z', items: [] }),
  sourceHealth: vi.fn().mockResolvedValue({ items: [] }),
  sources: vi.fn().mockResolvedValue({ sources: [] }),
  subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
  feedJobs: vi.fn().mockResolvedValue({ jobs: [] }),
  jobs: vi.fn().mockResolvedValue({ jobs: [] }),
} as unknown as ServiceApi

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-probe">{`${location.pathname}${location.search}${location.hash}`}</output>
}

function Shell({
  user,
  path = '/feed',
  onLogout = vi.fn(),
  serviceApi = api,
  refreshState = 'idle',
  refreshMessage,
  refreshEventKey,
  onRetry,
}: {
  user: User
  path?: string
  onLogout?: () => void
  serviceApi?: ServiceApi
  refreshState?: 'idle' | 'pending' | 'queued' | 'running' | 'stopping' | 'cancelled' | 'partial' | 'failed' | 'succeeded' | 'blocked' | 'reload_failed'
  refreshMessage?: string
  refreshEventKey?: string
  onRetry?: () => void
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>
    <MemoryRouter initialEntries={[path]}>
      <DesignSystemProvider>
        <HeroWorkbenchShell
          api={serviceApi}
          user={user}
          query=""
          onQueryChange={vi.fn()}
          onLogout={onLogout}
          onRetry={onRetry}
          refreshState={refreshState}
          refreshMessage={refreshMessage}
          refreshEventKey={refreshEventKey}
        >
          <div data-page-frame="reading" data-feed-blank-region>content</div>
        </HeroWorkbenchShell>
        <LocationProbe />
      </DesignSystemProvider>
    </MemoryRouter>
  </QueryClientProvider>
}

describe('HeroWorkbenchShell sidebar preference', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('places the continuous page canvas behind the floating header surface', () => {
    render(<Shell user={{ id: 'header-canvas', username: 'canvas', role: 'member', enabled: true }} />)

    expect(document.querySelector('[data-page-canvas]')).toHaveClass('row-start-1', 'row-span-2')
    expect(document.querySelector('[data-page-canvas]')).not.toHaveClass('pt-[var(--inteliscope-size-page-header)]')
    expect(screen.getByRole('heading', { name: '信息流', level: 1 }).closest('header')).toHaveClass('relative', 'z-20', 'row-start-1')
  })

  it('defaults to collapsed and persists independent expanded state per account', async () => {
    const browser = userEvent.setup()
    const first = { id: 'sidebar-a', username: 'alpha', role: 'member' as const, enabled: true }
    const second = { id: 'sidebar-b', username: 'beta', role: 'member' as const, enabled: true }
    const view = render(<Shell user={first} />)

    const sidebarToggle = screen.getByRole('button', { name: '展开侧栏' })
    await browser.click(sidebarToggle)
    expect(screen.getByRole('button', { name: '收起侧栏' })).toBe(sidebarToggle)
    expect(sidebarToggle).toHaveFocus()
    expect(screen.getByText('浏览')).toBeInTheDocument()
    expect(screen.getByText('常用视图')).toBeInTheDocument()
    expect(screen.getByText('管理')).toBeInTheDocument()
    expect(window.localStorage.getItem(sidebarPreferenceKey(first.id))).toBe('expanded')

    view.rerender(<Shell user={second} />)
    expect(screen.getByRole('button', { name: '展开侧栏' })).toBeInTheDocument()
    expect(window.localStorage.getItem(sidebarPreferenceKey(second.id))).toBeNull()

    view.rerender(<Shell user={first} />)
    expect(screen.getByRole('button', { name: '收起侧栏' })).toBeInTheDocument()
  })

  it('opens a categorized overlay below the 1360px breakpoint and returns focus on Escape', async () => {
    useViewport(1280)
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'sidebar-tablet', username: 'tablet', role: 'member', enabled: true }} />)

    const trigger = screen.getByRole('button', { name: '展开导航' })
    expect(trigger).not.toHaveClass('bg-accent/15', 'text-accent')
    expect(trigger).not.toHaveClass('sidebar-desktop-toggle')
    expect(screen.queryByRole('dialog', { name: '分类导航' })).not.toBeInTheDocument()

    await browser.click(trigger)
    expect(trigger).toHaveClass('bg-accent/15', 'text-accent')
    expect(screen.getByRole('dialog', { name: '分类导航' })).toBeInTheDocument()
    expect(screen.getByText('常用视图')).toBeInTheDocument()

    await browser.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '分类导航' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('opens the role-scoped settings directory from collapsed and expanded sidebar focus', async () => {
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'settings-directory', username: 'settings', role: 'member', enabled: true }} />)

    const collapsedSettings = screen.getByRole('link', { name: '设置' })
    expect(collapsedSettings).toHaveAttribute('data-sidebar-nav-item', 'collapsed')
    await browser.hover(collapsedSettings)
    expect(screen.queryByRole('dialog', { name: '设置目录' })).not.toBeInTheDocument()
    const collapsedDirectory = await screen.findByRole('dialog', { name: '设置目录' })
    expect(within(collapsedDirectory).getAllByRole('link')).toHaveLength(4)
    expect(within(collapsedDirectory).queryByRole('link', { name: '获取与主题' })).not.toBeInTheDocument()

    await browser.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '设置目录' })).not.toBeInTheDocument())
    await waitFor(() => expect(collapsedSettings).toHaveFocus())

    await browser.click(screen.getByRole('button', { name: '展开侧栏' }))
    const expandedSettings = screen.getAllByRole('link', { name: '设置' })
      .find((candidate) => candidate.getAttribute('data-sidebar-nav-item') === 'expanded')
    if (!expandedSettings) throw new Error('expanded Settings route was not rendered')
    expandedSettings.focus()
    const expandedDirectory = await screen.findByRole('dialog', { name: '设置目录' })
    await browser.click(within(expandedDirectory).getByRole('link', { name: '消息通知' }))
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/settings#settings-notifications')
  })

  it('uses an Inteliscope mark and applies quick views before navigating to Feed', async () => {
    const browser = userEvent.setup()
    render(<Shell path="/settings" user={{ id: 'quick-view', username: 'quick', role: 'member', enabled: true }} />)

    const brandTrigger = screen.getByRole('button', { name: '展开侧栏' })
    expect(brandTrigger).toHaveAttribute('data-inteliscope-mark-trigger')
    expect(brandTrigger).not.toHaveTextContent(/^I$/)
    await browser.click(brandTrigger)
    expect(screen.queryByRole('button', { name: 'AI' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '未读' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '朋友动态' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '产品机会' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '公共订阅' }))

    expect(screen.getByTestId('location-probe')).toHaveTextContent('/feed')
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.feed.v2:quick-view') || '{}')).toMatchObject({ channel: '', subscriptionScope: 'public', order: 'newest' })
  })

  it('uses the shared sidebar row interaction and split-panel control across desktop states', async () => {
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'sidebar-visual', username: 'visual', role: 'member', enabled: true }} />)

    const expand = screen.getByRole('button', { name: '展开侧栏' })
    expect(expand).toHaveAttribute('data-sidebar-panel-toggle')
    expect(expand.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(expand).toHaveClass('sidebar-desktop-toggle')
    expect(expand).toHaveClass('size-10')
    expect(expand).not.toHaveClass('bg-accent/15', 'text-accent')

    await browser.click(expand)
    const shell = screen.getByTestId('live-workbench-shell')
    expect(shell).toHaveAttribute('data-layout-motion', 'deliberate')
    expect(shell).toHaveClass('transition-[grid-template-columns]', 'duration-[var(--inteliscope-motion-deliberate)]')
    expect(shell.style.gridTemplateColumns).toContain('232px')
    expect(screen.getByRole('navigation', { name: '分类导航内容' })).toHaveClass('sidebar-scroll-region')
    const collapse = screen.getByRole('button', { name: '收起侧栏' })
    expect(collapse).toBe(expand)
    const route = screen.getAllByRole('link', { name: '信息流' }).find((candidate) => candidate.dataset.sidebarNavItem === 'expanded')
    if (!route) throw new Error('expanded Feed route was not rendered')
    const quickView = screen.getByRole('button', { name: '公共订阅' })
    expect(collapse).toHaveAttribute('data-sidebar-panel-toggle')
    expect(collapse).toHaveClass('bg-accent/15', 'text-accent')
    expect(collapse.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(route).toHaveAttribute('data-sidebar-nav-item', 'expanded')
    expect(quickView).toHaveAttribute('data-sidebar-nav-item', 'expanded')
    expect(route).toHaveClass('min-h-10', 'rounded-xl', 'transition-colors')
    expect(quickView).toHaveClass('min-h-10', 'rounded-xl', 'transition-colors')
    expect(quickView.className).not.toContain('scale-')
    const documentation = screen.getByRole('button', { name: '打开文档与发布菜单' })
    expect(documentation.closest('[data-sidebar-account-strip]')).toHaveClass('p-2')
    expect(documentation.closest('[data-sidebar-account-strip]')).toHaveClass('h-[var(--inteliscope-size-sidebar-footer)]', 'shrink-0')
    expect(documentation.querySelector('.lucide-book-marked')).not.toBeNull()
    expect(documentation.parentElement?.querySelector('.lucide-chevron-up')).toBeNull()
    await browser.click(documentation)
    const menu = screen.getByRole('dialog', { name: '文档与发布菜单' })
    expect(document.querySelector('[data-documentation-menu-surface]')).toHaveClass('w-52')
    expect(document.querySelector('[data-documentation-menu-surface]')).toHaveAttribute('data-sidebar-menu-direction', 'up')
    expect(within(menu).getByRole('button', { name: '操作手册' })).toBeInTheDocument()
    expect(within(menu).getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('href', PRODUCT_RELEASES_URL)
    await browser.click(within(menu).getByRole('button', { name: '更新日志' }))
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/changelog')
    expect(screen.getByRole('heading', { name: '更新日志' })).toBeInTheDocument()
  })

  it('keeps both fixed navigation canvases mounted while only the active one is interactive', async () => {
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'sidebar-fixed-canvas', username: 'canvas', role: 'member', enabled: true }} />)

    const sidebar = screen.getByRole('complementary', { name: '桌面导航' })
    const collapsedLayer = sidebar.querySelector<HTMLElement>('[data-sidebar-layer="collapsed"]')
    const expandedLayer = sidebar.querySelector<HTMLElement>('[data-sidebar-layer="expanded"]')
    const accountStrip = sidebar.querySelector<HTMLElement>('[data-sidebar-account-strip]')
    const accountTrigger = screen.getByRole('button', { name: '打开账户菜单' })
    if (!collapsedLayer || !expandedLayer || !accountStrip) throw new Error('fixed desktop sidebar canvases were not rendered')

    expect(sidebar).toHaveAttribute('data-sidebar-state', 'collapsed')
    expect(collapsedLayer.querySelector('nav')).toHaveClass('w-[var(--inteliscope-width-workbench-sidebar-collapsed)]')
    expect(expandedLayer.querySelector('nav')).toHaveClass('w-[var(--inteliscope-width-workbench-sidebar-expanded)]')
    expect(expandedLayer).toHaveAttribute('aria-hidden', 'true')
    expect(expandedLayer).toHaveAttribute('inert')
    expect(accountStrip).toHaveClass('h-[var(--inteliscope-size-sidebar-footer)]', 'shrink-0')
    expect(accountTrigger).toHaveClass('h-12')

    await browser.click(screen.getByRole('button', { name: '展开侧栏' }))
    expect(sidebar).toHaveAttribute('data-sidebar-state', 'expanded')
    expect(collapsedLayer).toHaveAttribute('aria-hidden', 'true')
    expect(collapsedLayer).toHaveAttribute('inert')
    expect(expandedLayer).not.toHaveAttribute('aria-hidden')
    expect(expandedLayer).not.toHaveAttribute('inert')
    expect(sidebar.querySelector('[data-sidebar-account-copy]')).toHaveAttribute('aria-hidden', 'false')
    expect(sidebar.querySelector('[data-sidebar-brand]')).toHaveAttribute('aria-hidden', 'false')
  })

  it('opens account actions from the avatar and logs out only from the menu action', async () => {
    const browser = userEvent.setup()
    const onLogout = vi.fn()
    render(<Shell user={{ id: 'account-menu', username: 'alpha', display_name: 'Alpha', role: 'admin', enabled: true }} onLogout={onLogout} />)

    expect(screen.queryByRole('button', { name: '退出登录' })).not.toBeInTheDocument()
    const account = screen.getByRole('button', { name: '打开账户菜单' })
    expect(account.closest('[data-sidebar-account-strip]')).toHaveClass('p-2')
    await browser.click(account)
    expect(screen.getByText('alpha · 管理员')).toBeInTheDocument()
    expect(document.querySelector('[data-account-menu-surface]')).toHaveClass('w-52')
    expect(document.querySelector('[data-account-menu-surface]')).toHaveAttribute('data-sidebar-menu-direction', 'up')
    expect(screen.getByRole('button', { name: '操作手册' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '更新日志' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('href', PRODUCT_RELEASES_URL)
    expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument()
    expect(onLogout).not.toHaveBeenCalled()

    await browser.click(screen.getByRole('button', { name: '退出登录' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('keeps account routes and logout reachable from the safe-area mobile More sheet', async () => {
    useViewport(390)
    const browser = userEvent.setup()
    const onLogout = vi.fn()
    render(<Shell user={{ id: 'mobile-account', username: 'mobile', role: 'member', enabled: true }} onLogout={onLogout} />)

    const navigation = screen.getByRole('navigation', { name: '移动端主导航' })
    expect(navigation).toHaveClass('pb-[env(safe-area-inset-bottom)]', 'grid-cols-5')
    const trigger = within(navigation).getByRole('button', { name: '更多与账户' })
    await browser.click(trigger)

    const sheet = screen.getByRole('dialog', { name: '更多与账户' })
    expect(sheet).toHaveClass('pb-[env(safe-area-inset-bottom)]')
    expect(within(sheet).getByRole('button', { name: '账户与成员' })).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: '设置' })).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: '操作手册' })).toBeInTheDocument()
    expect(within(sheet).getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('href', PRODUCT_RELEASES_URL)
    await browser.click(within(sheet).getByRole('button', { name: '退出登录' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})

describe('HeroWorkbenchShell Feed visual scope', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('only allows automatic insights when the measured reading gutter is large enough', () => {
    expect(canFloatFeedInsights(1440, 1064)).toBe(true)
    expect(canFloatFeedInsights(1440, 1065)).toBe(false)
    expect(calculateFeedInsightsLayout(
      { left: 72, right: 1364 },
      { left: 308, right: 1128 },
      true,
    )).toEqual({
      panelLeft: 1000,
      readingShift: -140,
      obstructsFeed: false,
    })
    expect(calculateFeedInsightsLayout(
      { left: 72, right: 1264 },
      { left: 100, right: 920 },
      true,
    )).toEqual({
      panelLeft: 900,
      readingShift: -16,
      obstructsFeed: true,
    })
    expect(calculateFeedInsightsLayout(
      { left: 72, right: 1364 },
      { left: 308, right: 1128 },
      false,
    )).toEqual({
      panelLeft: 1000,
      readingShift: 0,
      obstructsFeed: true,
    })
  })

  it('shows a terminal refresh event once in an overlay toast with one retry action', async () => {
    const browser = userEvent.setup()
    const retry = vi.fn()
    const user = { id: 'refresh-toast', username: 'refresh', role: 'member' as const, enabled: true }
    const view = render(<Shell
      user={user}
      refreshState="failed"
      refreshMessage="上游连接超时"
      refreshEventKey="job-1:failed"
      onRetry={retry}
    />)

    const message = await screen.findByText('上游连接超时')
    const toastRegion = message.closest('[data-slot="toast-region"]')
    expect(toastRegion).not.toBeNull()
    expect(toastRegion?.closest('[data-page-frame]')).toBeNull()
    await browser.click(screen.getByRole('button', { name: '重试' }))
    expect(retry).toHaveBeenCalledTimes(1)

    view.rerender(<Shell
      user={user}
      refreshState="failed"
      refreshMessage="上游连接超时"
      refreshEventKey="job-1:failed"
      onRetry={retry}
    />)
    await waitFor(() => expect(screen.queryByText('上游连接超时')).not.toBeInTheDocument())
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('distinguishes a completed acquisition from a failed Feed data reload', async () => {
    render(<Shell
      user={{ id: 'reload-failed', username: 'reload-failed', role: 'member', enabled: true }}
      refreshState="reload_failed"
      refreshMessage="内容获取已完成，但信息流加载失败。请点击“刷新”重试。"
      refreshEventKey="source-job:reload-failed"
    />)

    expect(await screen.findByText('信息流加载失败')).toBeInTheDocument()
    expect(screen.getByText('内容获取已完成，但信息流加载失败。请点击“刷新”重试。')).toBeInTheDocument()
    expect(screen.queryByText('信息流更新未开始')).not.toBeInTheDocument()
  })

  it('exposes Agent on subscriptions without exposing Insights', async () => {
    const browser = userEvent.setup()
    render(<Shell path="/subscriptions" user={{ id: 'subscription-agent', username: 'sub', role: 'member', enabled: true }} />)

    expect(screen.getByRole('heading', { name: '订阅与来源' }).closest('header')).toHaveAttribute('data-page-header-appearance', 'inset')
    expect(screen.queryByRole('button', { name: '展开信息概览' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(screen.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeInTheDocument()
    const statusContainer = document.querySelector('[data-agent-header-status]') as HTMLElement
    expect(screen.getByText('OpenClaw 对话')).toBeInTheDocument()
    expect(statusContainer).toHaveClass('items-center', 'self-center')
    const statusReveal = document.querySelector('[data-loading-reveal="agent-status"]') as HTMLElement
    expect(statusReveal).toHaveClass(
      '[&_[data-content-layer]]:items-center',
      '[&_[data-content-layer]]:justify-center',
    )
    expect(statusReveal.querySelector('[data-status-indicator]')).toHaveClass('self-center')
    expect(statusReveal).toHaveTextContent('未配置')
    expect(statusContainer.querySelectorAll('[data-status-indicator]')).toHaveLength(1)
    expect(api.agentDelegations).toHaveBeenCalled()
  })

  it('softly dismisses obstructing Insights when the fixed Agent rail leaves insufficient room', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.tagName === 'MAIN') return { left: 72, right: 1264, top: 52, bottom: 900, width: 1192, height: 848, x: 72, y: 52, toJSON: () => ({}) }
      if (this.matches('[data-page-frame="reading"]')) return { left: 258, right: 1078, top: 60, bottom: 850, width: 820, height: 790, x: 258, y: 60, toJSON: () => ({}) }
      if (this.getAttribute('aria-label') === '信息概览') return { left: 900, right: 1252, top: 60, bottom: 700, width: 352, height: 640, x: 900, y: 60, toJSON: () => ({}) }
      return originalRect.call(this)
    })
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'obstructed-insights', username: 'blocked', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    const surface = screen.getByRole('complementary', { name: '信息概览' })
    await browser.click(screen.getByRole('button', { name: '切换到白天模式' }))
    expect(surface).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(surface).toBeInTheDocument()
    await waitFor(() => expect(surface).toHaveAttribute('data-insights-surface', 'closing'))
    expect(surface).toHaveAttribute('aria-hidden', 'true')
    expect(surface).toHaveAttribute('inert')
    expect(surface).toHaveClass('quiet-surface-exit', 'pointer-events-none')
    await waitFor(() => expect(surface).not.toBeInTheDocument(), { timeout: 600 })
    expect(screen.getByRole('complementary', { name: 'OpenClaw 上下文' })).toHaveClass('overflow-hidden', 'overscroll-none')
    vi.restoreAllMocks()
  })

  it('keeps non-obstructing Insights open after Feed blank-space activation', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.tagName === 'MAIN') return { left: 72, right: 1376, top: 52, bottom: 900, width: 1304, height: 848, x: 72, y: 52, toJSON: () => ({}) }
      if (this.matches('[data-page-frame="reading"]')) return { left: 314, right: 1134, top: 60, bottom: 850, width: 820, height: 790, x: 314, y: 60, toJSON: () => ({}) }
      if (this.getAttribute('aria-label') === '信息概览') return { left: 1012, right: 1364, top: 60, bottom: 700, width: 352, height: 640, x: 1012, y: 60, toJSON: () => ({}) }
      return originalRect.call(this)
    })
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'clear-insights', username: 'clear', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    await waitFor(() => expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-insights-obstructs-feed', 'false'))
    expect(screen.getByRole('complementary', { name: '信息概览' })).toHaveStyle({ left: '1012px' })
    expect(screen.getByText('content').closest('main')?.style.getPropertyValue('--inteliscope-feed-reading-shift')).toBe('-134px')
    await browser.click(screen.getByText('content'))
    expect(screen.getByRole('complementary', { name: '信息概览' })).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('uses the whole workbench non-interactive surface to dismiss obstructing manual Insights', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.tagName === 'MAIN') return { left: 72, right: 1264, top: 52, bottom: 900, width: 1192, height: 848, x: 72, y: 52, toJSON: () => ({}) }
      if (this.matches('[data-page-frame="reading"]')) return { left: 258, right: 1078, top: 60, bottom: 850, width: 820, height: 790, x: 258, y: 60, toJSON: () => ({}) }
      if (this.getAttribute('aria-label') === '信息概览') return { left: 900, right: 1252, top: 60, bottom: 700, width: 352, height: 640, x: 900, y: 60, toJSON: () => ({}) }
      return originalRect.call(this)
    })
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'wide-dismiss-insights', username: 'wide-dismiss', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    const surface = screen.getByRole('complementary', { name: '信息概览' })
    await waitFor(() => expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-insights-obstructs-feed', 'true'))
    await browser.click(screen.getByRole('button', { name: '切换到白天模式' }))
    expect(surface).toHaveAttribute('data-insights-surface', 'manual')
    await browser.click(screen.getByRole('heading', { name: '信息流' }))
    await waitFor(() => expect(surface).toHaveAttribute('data-insights-surface', 'closing'))
    expect(surface).toHaveAttribute('inert')
    await waitFor(() => expect(surface).not.toBeInTheDocument(), { timeout: 600 })
    vi.restoreAllMocks()
  })

  it('softly dismisses Insights when a docked Agent becomes an overlay after resize', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.tagName === 'MAIN') return { left: 72, right: 1376, top: 52, bottom: 900, width: 1304, height: 848, x: 72, y: 52, toJSON: () => ({}) }
      if (this.matches('[data-page-frame="reading"]')) return { left: 314, right: 1134, top: 60, bottom: 850, width: 820, height: 790, x: 314, y: 60, toJSON: () => ({}) }
      return originalRect.call(this)
    })
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'responsive-insights', username: 'responsive', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    const surface = screen.getByRole('complementary', { name: '信息概览' })
    await waitFor(() => expect(surface).toHaveAttribute('data-insights-surface', 'manual'))

    useViewport(1024)
    window.dispatchEvent(new Event('resize'))

    await waitFor(() => expect(screen.getByRole('dialog', { name: 'OpenClaw 上下文' })).toBeInTheDocument())
    await waitFor(() => expect(surface).toHaveAttribute('data-insights-surface', 'closing'))
    expect(surface).toHaveAttribute('aria-hidden', 'true')
    await waitFor(() => expect(surface).not.toBeInTheDocument(), { timeout: 600 })
    vi.restoreAllMocks()
  })

  it('keeps the content header limited to title, panel controls and the theme mode', async () => {
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'feed-visual', username: 'feed', role: 'member', enabled: true }} />)

    expect(screen.queryByPlaceholderText('搜索标题、来源或主题')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更新信息流' })).not.toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-ui-typography', 'system')
    const header = screen.getByRole('heading', { name: '信息流' }).closest('header')
    expect(header).not.toBeNull()
    expect(Array.from(header!.querySelectorAll('button')).map((button) => button.getAttribute('aria-label'))).toEqual([
      '切换到白天模式',
      '展开信息概览',
      '展开 Agent 面板',
    ])
    expect(screen.getByRole('button', { name: '展开信息概览' })).toHaveAttribute('aria-expanded', 'false')
    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    expect(screen.getByRole('button', { name: '收起信息概览' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('complementary', { name: '信息概览' })).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: '展开 Agent 面板' })
    await browser.click(toggle)
    const activeToggle = screen.getByRole('button', { name: '收起 Agent 面板' })
    expect(activeToggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
    expect(activeToggle.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(activeToggle.querySelector('[data-panel-fill]')).toHaveAttribute('opacity', '0.16')
    expect(activeToggle.querySelector('[data-panel-fill]')).toHaveAttribute('pointer-events', 'none')
    expect(activeToggle.querySelector('.lucide-panel-right-close')).toBeNull()
    expect(activeToggle.querySelector('.lucide-panel-right-open')).toBeNull()
    expect(screen.getByRole('complementary', { name: '信息概览' })).toHaveClass('quiet-surface-enter')
    const agentRail = screen.getByRole('complementary', { name: 'OpenClaw 上下文' })
    expect(agentRail).toHaveClass('transition-[opacity,transform]', 'duration-[var(--inteliscope-motion-deliberate)]', 'opacity-100')
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-fixed-agent-rail-phase', 'open')
    expect(screen.getByRole('heading', { name: '信息流' }).closest('header')).toHaveAttribute('data-header-visual', 'quiet-studio')

    await browser.click(activeToggle)
    expect(agentRail).toHaveAttribute('aria-hidden', 'true')
    expect(agentRail).toHaveAttribute('inert')
    expect(agentRail).toHaveAttribute('data-rail-surface-state', 'closing')
    await waitFor(() => expect(agentRail).not.toBeInTheDocument(), { timeout: 600 })
  })

  it('resizes the fixed desktop Agent rail with the keyboard and persists the account width', async () => {
    const browser = userEvent.setup()
    const user = { id: 'rail-width', username: 'rail', role: 'member' as const, enabled: true }
    render(<Shell user={user} />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    const separator = screen.getByRole('separator', { name: '调整信息流和 Agent 面板宽度' })
    expect(separator).toHaveAttribute('aria-valuenow', '400')
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.bootstrap-shell.v1') || 'null')).toMatchObject({
      userId: user.id,
      rightRail: 'agent',
      rightRailWidth: 400,
    })

    separator.focus()
    await browser.keyboard('{ArrowLeft}')
    expect(separator).toHaveAttribute('aria-valuenow', '424')
    expect(window.localStorage.getItem(`inteliscope.ui.right-rail.v1:${user.id}`)).toBe(JSON.stringify({ width: 424 }))
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.bootstrap-shell.v1') || 'null')).toMatchObject({ rightRailWidth: 424 })

    await browser.dblClick(separator)
    expect(separator).toHaveAttribute('aria-valuenow', '400')
  })

  it('restores a docked Agent rail without replaying its entrance animation', () => {
    const user = { id: 'restored-rail', username: 'restored', role: 'member' as const, enabled: true }
    window.localStorage.setItem('inteliscope.ui.bootstrap-shell.v1', JSON.stringify({
      userId: user.id,
      sidebar: 'collapsed',
      rightRail: 'agent',
      rightRailWidth: 420,
    }))

    render(<Shell user={user} />)

    expect(screen.getByRole('button', { name: '收起 Agent 面板' })).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'OpenClaw 上下文' })).not.toHaveClass('quiet-surface-enter')
    expect(screen.getByRole('separator', { name: '调整信息流和 Agent 面板宽度' })).toHaveAttribute('aria-valuenow', '420')
  })

  it('docks whenever layout space is sufficient and falls back to a Drawer otherwise', async () => {
    const browser = userEvent.setup()
    const view = render(<Shell user={{ id: 'dynamic-dock', username: 'dock', role: 'member', enabled: true }} />)

    useViewport(1280)
    window.dispatchEvent(new Event('resize'))
    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-fixed-agent-rail', 'true')
    expect(screen.getByRole('separator', { name: '调整信息流和 Agent 面板宽度' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'OpenClaw 上下文' })).not.toBeInTheDocument()

    view.unmount()
    useViewport(1024)
    render(<Shell user={{ id: 'dynamic-overlay', username: 'overlay', role: 'member', enabled: true }} />)
    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-fixed-agent-rail', 'false')
    expect(screen.queryByRole('separator', { name: '调整信息流和 Agent 面板宽度' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'OpenClaw 上下文' })).toHaveClass('overflow-hidden', 'overscroll-none')
  })

  it('keeps the insights card content-sized and expands distributions after three items', async () => {
    const browser = userEvent.setup()
    const channels = ['AI', '产品', '投资', '生活', '政策']
    const serviceApi = {
      ...api,
      latestFeed: vi.fn().mockResolvedValue({
        schema_version: 2,
        generated_at: '2026-07-21T08:05:00Z',
        updated_at: '2026-07-21T08:05:00Z',
        items: channels.map((channel, index) => {
          const value = contextItem(`insight-${index}`)
          return {
            ...value,
            presentation: value.presentation ? {
              ...value.presentation,
              taxonomy: { ...value.presentation.taxonomy, channel },
            } : undefined,
          }
        }),
      }),
      sourceHealth: vi.fn().mockResolvedValue({ items: [] }),
    } as unknown as ServiceApi
    render(<Shell user={{ id: 'insights-natural', username: 'insights', role: 'member', enabled: true }} serviceApi={serviceApi} />)

    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    const surface = screen.getByRole('complementary', { name: '信息概览' })
    expect(surface).toHaveClass('flex', 'flex-col')
    expect(surface.className).not.toContain('grid-rows-')
    const channelSection = await screen.findByRole('region', { name: '主要频道' })
    const reveal = within(channelSection).getByRole('button', { name: '查看更多 2 项' })
    expect(within(channelSection).getAllByText(/AI|产品|投资|生活|政策/)).toHaveLength(3)
    await browser.click(reveal)
    expect(within(channelSection).getByRole('button', { name: '收起' })).toHaveAttribute('aria-expanded', 'true')
    expect(within(channelSection).getAllByText(/AI|产品|投资|生活|政策/)).toHaveLength(5)
  })

  it('loads subscription statistics independently and deep-links to the requested tab', async () => {
    const browser = userEvent.setup()
    const serviceApi = {
      ...api,
      subscriptions: vi.fn().mockResolvedValue({
        subscriptions: [{ id: 'sub-1' }, { id: 'sub-2' }],
      }),
      sources: vi.fn().mockResolvedValue({
        sources: [{ id: 'source-1' }, { id: 'source-2' }, { id: 'source-3' }],
      }),
      feedJobs: vi.fn().mockResolvedValue({
        jobs: [
          { id: 'job-1', user_id: 'insights-stats' },
          { id: 'job-2', user_id: 'insights-stats' },
          { id: 'job-other', user_id: 'someone-else' },
        ],
      }),
    } as unknown as ServiceApi
    render(<Shell
      user={{ id: 'insights-stats', username: 'stats', role: 'owner', enabled: true }}
      serviceApi={serviceApi}
    />)

    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    const statistics = await screen.findByRole('region', { name: '订阅与运行' })
    expect(within(statistics).getByRole('button', { name: '我的订阅 2，打开相关页面' })).toBeInTheDocument()
    expect(within(statistics).getByRole('button', { name: '来源库 3，打开相关页面' })).toBeInTheDocument()
    expect(within(statistics).getByRole('button', { name: '最近运行 2，打开相关页面' })).toBeInTheDocument()
    expect(within(statistics).getByText('最近运行只统计信息流相关记录，最多 20 条。')).toBeInTheDocument()
    expect(serviceApi.sources).toHaveBeenCalledWith(true, expect.any(AbortSignal))

    await browser.click(within(statistics).getByRole('button', { name: '最近运行 2，打开相关页面' }))
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/subscriptions?tab=jobs')
  })

  it('uses an em dash instead of a false zero when one statistics request fails', async () => {
    const browser = userEvent.setup()
    const serviceApi = {
      ...api,
      subscriptions: vi.fn().mockRejectedValue(new Error('subscriptions unavailable')),
      sources: vi.fn().mockResolvedValue({ sources: [{ id: 'source-1' }] }),
      feedJobs: vi.fn().mockRejectedValue(new Error('jobs unavailable')),
    } as unknown as ServiceApi
    render(<Shell
      user={{ id: 'insights-partial', username: 'partial', role: 'member', enabled: true }}
      serviceApi={serviceApi}
    />)

    await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
    const statistics = await screen.findByRole('region', { name: '订阅与运行' })
    expect(await within(statistics).findByRole('button', { name: '我的订阅暂时无法读取' })).toHaveTextContent('—')
    expect(within(statistics).getByRole('button', { name: '来源库 1，打开相关页面' })).toBeEnabled()
    expect(await within(statistics).findByRole('button', { name: '最近运行暂时无法读取' })).toHaveTextContent('—')
  })

  it('uses the same Quiet Studio header for collection routes', async () => {
    const browser = userEvent.setup()
    render(<Shell path="/saved" user={{ id: 'saved-visual', username: 'saved', role: 'member', enabled: true }} />)

    expect(screen.queryByPlaceholderText('搜索标题、来源或主题')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更新信息流' })).not.toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-ui-typography', 'system')
    const collectionToggle = screen.getByRole('button', { name: '展开 Agent 面板' })
    await browser.click(collectionToggle)
    const activeToggle = screen.getByRole('button', { name: '收起 Agent 面板' })
    expect(activeToggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
    expect(activeToggle.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(screen.getByRole('heading', { name: '收藏' }).closest('header')).toHaveAttribute('data-header-visual', 'quiet-studio')
  })
})

describe('HeroWorkbenchShell OpenClaw composer', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('presents a handoff composer and disables copying without context', async () => {
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'composer-empty', username: 'empty', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(await screen.findByText('交接模式')).toBeInTheDocument()
    expect(screen.queryByText('仅生成交接提示词，不在站内运行 Agent')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制交接提示词' })).toBeDisabled()
    expect(screen.getByText('使用 OpenClaw 当前设置')).toHaveClass('type-label')
    expect(screen.queryByRole('button', { name: /模型偏好/ })).not.toBeInTheDocument()
  })

  it('resolves selected context into human-readable source previews without exposing raw IDs', async () => {
    const browser = userEvent.setup()
    const rawId = 'instagram:post:DX8pBjzk5qp'
    const feedItem = vi.fn().mockResolvedValue(contextItem(rawId))
    window.sessionStorage.setItem('inteliscope.agent-context.v1:context-preview', JSON.stringify({
      userId: 'context-preview', question: '', itemIds: [rawId], modelPreference: 'auto',
    }))
    render(<Shell
      user={{ id: 'context-preview', username: 'preview', role: 'member', enabled: true }}
      serviceApi={{ ...api, feedItem } as ServiceApi}
    />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(await screen.findByText('Tibo')).toBeInTheDocument()
    expect(screen.getByText('@thsottiaux')).toBeInTheDocument()
    expect(screen.getByText('Oops... I did it again.')).toBeInTheDocument()
    expect(screen.queryByText(rawId)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /移除 Tibo/ })).toBeInTheDocument()
    expect(feedItem).toHaveBeenCalledTimes(1)
  })

  it('keeps all eight context removal actions visible in compact non-wrapping rows', async () => {
    useViewport(390)
    const browser = userEvent.setup()
    const ids = Array.from({ length: 8 }, (_, index) => `twitter:tweet:compact-${index + 1}`)
    const feedItem = vi.fn().mockImplementation((id: string) => Promise.resolve(contextItem(
      id,
      'Tibo with a deliberately long display name that must not expand the row',
      'X · An intentionally long source label that must be truncated',
    )))
    window.sessionStorage.setItem('inteliscope.agent-context.v1:compact-context', JSON.stringify({
      userId: 'compact-context', question: '', itemIds: ids, modelPreference: 'auto',
    }))
    render(<Shell
      user={{ id: 'compact-context', username: 'compact', role: 'member', enabled: true }}
      serviceApi={{ ...api, feedItem } as ServiceApi}
    />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))

    const removeButtons = await screen.findAllByRole('button', { name: /^移除 / })
    expect(removeButtons).toHaveLength(8)
    expect(screen.getByRole('dialog', { name: 'OpenClaw 上下文' })).toHaveClass('max-h-[88dvh]')
    expect(screen.getByTestId('agent-scroll-region')).toHaveClass('overflow-hidden')
    for (const button of removeButtons) {
      const row = button.closest('[data-agent-context-item]')
      expect(row).not.toBeNull()
      expect(row).toHaveClass('h-9', 'min-w-0')
    }
  })

  it('keeps an unavailable context independently removable', async () => {
    const browser = userEvent.setup()
    const rawId = 'missing:item'
    window.sessionStorage.setItem('inteliscope.agent-context.v1:context-missing', JSON.stringify({
      userId: 'context-missing', question: '', itemIds: [rawId], modelPreference: 'auto',
    }))
    render(<Shell
      user={{ id: 'context-missing', username: 'missing', role: 'member', enabled: true }}
      serviceApi={{ ...api, feedItem: vi.fn().mockRejectedValue(new Error('not found')) } as ServiceApi}
    />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(await screen.findByText('内容已失效')).toBeInTheDocument()
    expect(screen.queryByText(rawId)).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '移除失效内容' }))
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v6:context-missing') || '{}')).toMatchObject({ items: [] })
  })

  it('copies a v8 handoff with a safe source reference and no network side effect', async () => {
    const browser = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    window.sessionStorage.setItem('inteliscope.agent-context.v3:composer-copy', JSON.stringify({
      userId: 'composer-copy', question: '分析机会', items: [{ articleId: 'item-1', title: '条目一' }],
    }))
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<Shell user={{ id: 'composer-copy', username: 'copy', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    await browser.click(await screen.findByRole('button', { name: '复制交接提示词' }))

    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('[INTELISCOPE_HANDOFF_V8]'))
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('原文网址="https://example.com/item-1"'))
    expect(writeText).toHaveBeenCalledWith(expect.not.stringContaining('模型偏好'))
    expect(screen.getByRole('status', { name: '交接状态' })).toHaveTextContent('交接提示词已复制')
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v6:composer-copy') || '{}')).toMatchObject({
      question: '分析机会',
      items: [{ sourceUrl: 'https://example.com/item-1' }],
    })
    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })

  it('keeps the draft intact when clipboard access fails', async () => {
    const browser = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
    window.sessionStorage.setItem('inteliscope.agent-context.v1:composer-error', JSON.stringify({
      userId: 'composer-error', question: '保留问题', itemIds: ['item-1'], modelPreference: 'fast',
    }))
    render(<Shell user={{ id: 'composer-error', username: 'error', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    await browser.click(await screen.findByRole('button', { name: '复制交接提示词' }))
    expect(screen.getByRole('status', { name: '交接状态' })).toHaveTextContent('无法写入剪贴板，请手动复制')
    expect(screen.getByRole('textbox', { name: '交给 OpenClaw 的问题' })).toHaveValue('保留问题')
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v6:composer-error') || '{}')).toMatchObject({
      question: '保留问题',
      items: [{ articleId: 'item-1', sourceUrl: 'https://example.com/item-1' }],
    })
  })
})
