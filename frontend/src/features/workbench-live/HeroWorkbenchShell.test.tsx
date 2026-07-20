import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { FeedItem, User } from '../../api/types'
import { sidebarPreferenceKey } from '../../app/sidebarPreference'
import { HeroWorkbenchShell } from './HeroWorkbenchShell'

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
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn((query: string): MediaQueryList => {
      const min = query.match(/min-width:\s*(\d+(?:\.\d+)?)px/)
      const max = query.match(/max-width:\s*(\d+(?:\.\d+)?)px/)
      const matches = (!min || width >= Number(min[1])) && (!max || width <= Number(max[1]))
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
} as unknown as ServiceApi

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-probe">{location.pathname}</output>
}

function Shell({ user, path = '/feed', onLogout = vi.fn(), serviceApi = api }: { user: User; path?: string; onLogout?: () => void; serviceApi?: ServiceApi }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>
    <MemoryRouter initialEntries={[path]}>
      <HeroWorkbenchShell api={serviceApi} user={user} query="" onQueryChange={vi.fn()} onLogout={onLogout} refreshState="idle">
        <div>content</div>
      </HeroWorkbenchShell>
      <LocationProbe />
    </MemoryRouter>
  </QueryClientProvider>
}

describe('HeroWorkbenchShell sidebar preference', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('defaults to collapsed and persists independent expanded state per account', async () => {
    const browser = userEvent.setup()
    const first = { id: 'sidebar-a', username: 'alpha', role: 'member' as const, enabled: true }
    const second = { id: 'sidebar-b', username: 'beta', role: 'member' as const, enabled: true }
    const view = render(<Shell user={first} />)

    await browser.click(screen.getByRole('button', { name: '展开侧栏' }))
    expect(screen.getByRole('button', { name: '收起侧栏' })).toBeInTheDocument()
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
    expect(screen.queryByRole('dialog', { name: '分类导航' })).not.toBeInTheDocument()

    await browser.click(trigger)
    expect(trigger).toHaveClass('bg-accent/15', 'text-accent')
    expect(screen.getByRole('dialog', { name: '分类导航' })).toBeInTheDocument()
    expect(screen.getByText('常用视图')).toBeInTheDocument()

    await browser.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '分类导航' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('uses an Inteliscope mark and applies quick views before navigating to Feed', async () => {
    const browser = userEvent.setup()
    render(<Shell path="/settings" user={{ id: 'quick-view', username: 'quick', role: 'member', enabled: true }} />)

    const brandTrigger = screen.getByRole('button', { name: '展开侧栏' })
    expect(brandTrigger).toHaveAttribute('data-inteliscope-mark-trigger')
    expect(brandTrigger).not.toHaveTextContent(/^I$/)
    await browser.click(brandTrigger)
    await browser.click(screen.getByRole('button', { name: 'AI' }))

    expect(screen.getByTestId('location-probe')).toHaveTextContent('/feed')
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.feed.v2:quick-view') || '{}')).toMatchObject({ channel: 'AI', order: 'newest' })
  })

  it('uses the shared sidebar row interaction and split-panel control across desktop states', async () => {
    const browser = userEvent.setup()
    render(<Shell user={{ id: 'sidebar-visual', username: 'visual', role: 'member', enabled: true }} />)

    const expand = screen.getByRole('button', { name: '展开侧栏' })
    expect(expand).toHaveAttribute('data-sidebar-panel-toggle')
    expect(expand.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(expand).toHaveClass('size-10')
    expect(expand).not.toHaveClass('bg-accent/15', 'text-accent')

    await browser.click(expand)
    const collapse = screen.getByRole('button', { name: '收起侧栏' })
    const route = screen.getAllByRole('link', { name: '信息流' }).find((candidate) => candidate.dataset.sidebarNavItem === 'expanded')
    if (!route) throw new Error('expanded Feed route was not rendered')
    const quickView = screen.getByRole('button', { name: 'AI' })
    expect(collapse).toHaveAttribute('data-sidebar-panel-toggle')
    expect(collapse).toHaveClass('bg-accent/15', 'text-accent')
    expect(collapse.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(route).toHaveAttribute('data-sidebar-nav-item', 'expanded')
    expect(quickView).toHaveAttribute('data-sidebar-nav-item', 'expanded')
    expect(route).toHaveClass('min-h-10', 'rounded-xl', 'transition-colors')
    expect(quickView).toHaveClass('min-h-10', 'rounded-xl', 'transition-colors')
    expect(quickView.className).not.toContain('scale-')
  })

  it('opens account actions from the avatar and logs out only from the menu action', async () => {
    const browser = userEvent.setup()
    const onLogout = vi.fn()
    render(<Shell user={{ id: 'account-menu', username: 'alpha', display_name: 'Alpha', role: 'admin', enabled: true }} onLogout={onLogout} />)

    expect(screen.queryByRole('button', { name: '退出登录' })).not.toBeInTheDocument()
    const account = screen.getByRole('button', { name: '打开账户菜单' })
    await browser.click(account)
    expect(screen.getByText('alpha · 管理员')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument()
    expect(onLogout).not.toHaveBeenCalled()

    await browser.click(screen.getByRole('button', { name: '退出登录' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})

describe('HeroWorkbenchShell Feed visual scope', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('keeps the content header limited to title and Agent toggle', () => {
    render(<Shell user={{ id: 'feed-visual', username: 'feed', role: 'member', enabled: true }} />)

    expect(screen.queryByPlaceholderText('搜索标题、来源或主题')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更新信息流' })).not.toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-ui-typography', 'system')
    expect(screen.getByRole('heading', { name: '信息流' })).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: '收起 Agent 面板' })
    expect(toggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
    expect(toggle.querySelector('[data-split-panel-icon]')).not.toBeNull()
    expect(toggle.querySelector('[data-panel-fill]')).toHaveAttribute('opacity', '0.16')
    expect(toggle.querySelector('.lucide-panel-right-close')).toBeNull()
    expect(toggle.querySelector('.lucide-panel-right-open')).toBeNull()
    expect(screen.getByRole('heading', { name: '信息流' }).closest('header')).toHaveAttribute('data-header-visual', 'quiet-studio')
  })

  it('uses the same Quiet Studio header for collection routes', () => {
    render(<Shell path="/saved" user={{ id: 'saved-visual', username: 'saved', role: 'member', enabled: true }} />)

    expect(screen.queryByPlaceholderText('搜索标题、来源或主题')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更新信息流' })).not.toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-ui-typography', 'system')
    const collectionToggle = screen.getByRole('button', { name: '收起 Agent 面板' })
    expect(collectionToggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
    expect(collectionToggle.querySelector('[data-split-panel-icon]')).not.toBeNull()
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
    render(<Shell user={{ id: 'composer-empty', username: 'empty', role: 'member', enabled: true }} />)

    expect(await screen.findByText('交接模式')).toBeInTheDocument()
    expect(screen.queryByText('仅生成交接提示词，不在站内运行 Agent')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制交接提示词' })).toBeDisabled()
    expect(screen.getByText('使用 OpenClaw 当前设置')).toHaveClass('type-label')
    expect(screen.queryByRole('button', { name: /模型偏好/ })).not.toBeInTheDocument()
  })

  it('resolves selected context into human-readable source previews without exposing raw IDs', async () => {
    const rawId = 'instagram:post:DX8pBjzk5qp'
    const feedItem = vi.fn().mockResolvedValue(contextItem(rawId))
    window.sessionStorage.setItem('inteliscope.agent-context.v1:context-preview', JSON.stringify({
      userId: 'context-preview', question: '', itemIds: [rawId], modelPreference: 'auto',
    }))
    render(<Shell
      user={{ id: 'context-preview', username: 'preview', role: 'member', enabled: true }}
      serviceApi={{ ...api, feedItem } as ServiceApi}
    />)

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

    expect(await screen.findByText('内容已失效')).toBeInTheDocument()
    expect(screen.queryByText(rawId)).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '移除失效内容' }))
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v3:context-missing') || '{}')).toMatchObject({ items: [] })
  })

  it('copies a v3 handoff without simulated model guidance or a network request', async () => {
    const browser = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    window.sessionStorage.setItem('inteliscope.agent-context.v3:composer-copy', JSON.stringify({
      userId: 'composer-copy', question: '分析机会', items: [{ articleId: 'item-1', title: '条目一' }],
    }))
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<Shell user={{ id: 'composer-copy', username: 'copy', role: 'member', enabled: true }} />)

    await browser.click(await screen.findByRole('button', { name: '复制交接提示词' }))

    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('[INTELISCOPE_HANDOFF_V3]'))
    expect(writeText).toHaveBeenCalledWith(expect.not.stringContaining('模型偏好'))
    expect(screen.getByRole('status', { name: '交接状态' })).toHaveTextContent('交接提示词已复制')
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v3:composer-copy') || '{}')).toMatchObject({ question: '分析机会' })
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

    await browser.click(await screen.findByRole('button', { name: '复制交接提示词' }))
    expect(screen.getByRole('status', { name: '交接状态' })).toHaveTextContent('无法写入剪贴板，请手动复制')
    expect(screen.getByRole('textbox', { name: '交给 OpenClaw 的问题' })).toHaveValue('保留问题')
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v1:composer-error') || '{}')).toMatchObject({ itemIds: ['item-1'], modelPreference: 'fast' })
  })
})
