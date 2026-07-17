import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentType, ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import type { ServiceApi } from '../api/service'
import type { FeedItem } from '../api/types'
import { AppRoutes } from './App'

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="当前位置">{location.pathname}{location.search}</output>
}

function liveApi(overrides: Partial<ServiceApi> = {}): ServiceApi {
  return {
    authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'user-live', username: 'live', role: 'member', enabled: true } }),
    latestFeed: vi.fn().mockResolvedValue({
      schema_version: 2,
      items: [{ id: 'live-1', title: '真实 API 条目', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z', user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false } }],
    }),
    agentDelegations: vi.fn().mockResolvedValue({ enabled: true, connections: [], mcp_url: '/mcp', token_ttl_days: 90, max_active: 5 }),
    jobs: vi.fn().mockResolvedValue({ jobs: [] }),
    feedSchedule: vi.fn().mockResolvedValue({ enabled: true, interval_minutes: 60, worker_status: 'ready' }),
    updateItemState: vi.fn(),
    ...overrides,
  } as unknown as ServiceApi
}

function detailedItem(id: string, overrides: Partial<FeedItem> = {}): FeedItem {
  return {
    id,
    title: `兼容标题 ${id}`,
    url: `https://example.com/${id}`,
    published_at: '2026-07-17T02:00:00Z',
    user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
    presentation: {
      version: 2,
      source: { id: 'detail-source', catalog_type: 'rss', platform: 'rss', name: '详情来源' },
      author: { name: '详情作者', kind: 'person' },
      timing: { published_at: '2026-07-17T02:00:00Z', fetched_at: '2026-07-17T02:01:00Z' },
      links: { canonical_url: `https://example.com/${id}`, source_url: `https://example.com/${id}` },
      content: { title: `详情标题 ${id}`, title_origin: 'native', excerpt: '详情摘录', body_text: '完整详情正文', content_kind: 'post_body', excerpt_truncated: false, body_truncated: false },
      taxonomy: { channel: '详情频道', configured_topics: [], inferred_topics: [], topics: ['详情主题'], entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'ai', score: 9, signal_strength: 'strong', signal_type: 'update', summary_zh: '详情概括' },
    },
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

describe('App routes', () => {
  it('opens the development workbench preview without requiring an API session', async () => {
    const authStatus = vi.fn().mockResolvedValue({ authenticated: false, user: null })
    const api = { authStatus } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '信息流' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeInTheDocument()
    expect(authStatus).not.toHaveBeenCalled()
  })

  it('redirects protected deep links to the login page when no session exists', async () => {
    const api = { authStatus: vi.fn().mockResolvedValue({ authenticated: false, user: null }) } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/history?item=article-1']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '登录私人信息雷达' })).toBeInTheDocument()
  })

  it('keeps the live HeroUI workbench inside the authenticated real-API boundary', async () => {
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '信息流' }, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('article', { name: '真实 API 条目' })).toBeInTheDocument())
    expect(document.querySelector('[data-ui-system="heroui"]')).toBeInTheDocument()
    expect(api.latestFeed).toHaveBeenCalled()
    expect(api.agentDelegations).toHaveBeenCalled()
    expect(screen.queryByText('稍后读')).not.toBeInTheDocument()
  })

  it('shows a neutral Agent connection state while delegation loading is unresolved', async () => {
    const user = userEvent.setup()
    const api = liveApi({ agentDelegations: vi.fn().mockImplementation(() => new Promise(() => undefined)) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await user.click(await screen.findByRole('button', { name: '展开 Agent 面板' }))
    expect(await screen.findByRole('status', { name: '正在检查 Agent 连接' })).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryByText('检查中')).not.toBeInTheDocument()
    expect(screen.queryByText('未配置')).not.toBeInTheDocument()
  })

  it('opens the narrow-screen Agent surface as a real modal dialog', async () => {
    const user = userEvent.setup()
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const toggle = await screen.findByRole('button', { name: '展开 Agent 面板' })
    await user.click(toggle)
    expect(await screen.findByRole('dialog', { name: 'OpenClaw 上下文' })).toBeInTheDocument()
    expect(screen.getAllByText('未配置')).toHaveLength(1)
  })

  it('temporarily inserts a deep-linked item returned by feedItem', async () => {
    const feedItem = vi.fn().mockResolvedValue({ id: 'deep', title: '深链条目', url: 'https://example.com/deep', published_at: '2026-07-17T01:00:00Z' })
    const api = liveApi({ feedItem } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=deep']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '深链条目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 深链条目' })).toHaveAttribute('aria-expanded', 'true')
    expect(feedItem).toHaveBeenCalledWith('deep', expect.any(AbortSignal))
  })

  it('always fetches selected detail and renders its v2 body over the snapshot copy', async () => {
    const user = userEvent.setup()
    const feedItem = vi.fn().mockResolvedValue(detailedItem('live-1'))
    const api = liveApi({ feedItem } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await user.click(await screen.findByRole('button', { name: '展开 真实 API 条目' }))
    expect(await screen.findByText('完整详情正文')).toBeInTheDocument()
    expect(screen.getByRole('article', { name: '详情标题 live-1' })).toBeInTheDocument()
    expect(feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
  })

  it('keeps the snapshot card usable when selected detail cannot be loaded', async () => {
    const api = liveApi({ feedItem: vi.fn().mockRejectedValue(new ApiError(503, { code: 'detail_failed', message: '详情失败' })) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=live-1']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '真实 API 条目' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('无法读取深链条目')
  })

  it('pins a successfully fetched deep link despite persisted filters and dismissed state', async () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-live', JSON.stringify({ unreadFirst: true, source: 'other-source', channel: '其他频道', topic: '其他主题', minScore: 10 }))
    const deep = detailedItem('filtered-deep', { user_state: { is_read: true, is_saved: false, is_later: false, dismissed: true } })
    const api = liveApi({ feedItem: vi.fn().mockResolvedValue(deep) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=filtered-deep']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByRole('article', { name: '详情标题 filtered-deep' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '收起 详情标题 filtered-deep' })).toHaveAttribute('aria-expanded', 'true')
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('keeps a filter-pinned detail between older and newer matching rows', async () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-live', JSON.stringify({ unreadFirst: false, source: 'matching-source', channel: '', topic: '' }))
    const sourceItem = (id: string, title: string, published_at: string): FeedItem => ({
      id,
      title,
      url: `https://example.com/${id}`,
      source_id: 'matching-source',
      published_at,
      user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
    })
    const detail = detailedItem('between', { published_at: '2026-07-17T02:00:00Z' })
    if (detail.presentation) detail.presentation.timing.published_at = '2026-07-17T02:00:00Z'
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({
        schema_version: 2,
        items: [
          sourceItem('older', '较旧条目', '2026-07-17T01:00:00Z'),
          sourceItem('newer', '较新条目', '2026-07-17T03:00:00Z'),
        ],
      }),
      feedItem: vi.fn().mockResolvedValue(detail),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=between']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      await screen.findByRole('article', { name: '详情标题 between' })
      expect(screen.getAllByRole('article').map((article) => article.getAttribute('aria-label'))).toEqual([
        '较旧条目',
        '详情标题 between',
        '较新条目',
      ])
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('keeps an expanded snapshot when detail 404 resolves before the source query', async () => {
    const latest = deferred<{ schema_version: number; items: FeedItem[] }>()
    const api = liveApi({
      latestFeed: vi.fn().mockReturnValue(latest.promise),
      feedItem: vi.fn().mockRejectedValue(new ApiError(404, { code: 'not_found', message: '不存在' })),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await waitFor(() => expect(api.feedItem).toHaveBeenCalled())
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(screen.queryByText(/这条信息已不可用/)).not.toBeInTheDocument()
    await act(async () => latest.resolve({
      schema_version: 2,
      items: [{ id: 'live-1', title: '快照回退条目', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z' }],
    }))
    expect(await screen.findByRole('article', { name: '快照回退条目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 快照回退条目' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
  })

  it('removes a proven-stale 404 deep link and falls back to bottom-first Feed positioning', async () => {
    const items = Array.from({ length: 20 }, (_, index) => ({
      id: `live-${index + 1}`,
      title: `真实 API 条目 ${index + 1}`,
      url: `https://example.com/live-${index + 1}`,
      published_at: new Date(Date.UTC(2026, 6, 17, 0, index)).toISOString(),
    }))
    const scrollTo = vi.fn()
    const originalScrollTo = HTMLElement.prototype.scrollTo
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo })
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items }),
      feedItem: vi.fn().mockRejectedValue(new ApiError(404, { code: 'not_found', message: '不存在' })),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=missing']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByText(/这条信息已不可用/)).toBeInTheDocument()
      await waitFor(() => expect(screen.getAllByRole('article').length).toBeGreaterThan(0))
      expect(screen.getByLabelText('当前位置')).toHaveTextContent('/__preview/workbench-live')
      expect(screen.getByLabelText('当前位置')).not.toHaveTextContent('item=')
      await waitFor(() => expect(scrollTo.mock.calls.some(([options]) => (options as ScrollToOptions).behavior === 'auto')).toBe(true))
    } finally {
      if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: originalScrollTo })
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
    }
  })

  it('keeps the legacy later route in place before the final cutover', async () => {
    const api = liveApi({
      historyFeed: vi.fn().mockResolvedValue({ items: [] }),
      sourceHealth: vi.fn().mockResolvedValue({ items: [] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/later?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '稍后读' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/later?item=live-1'))
  })

  it('does not remount the authenticated workbench when inline expansion changes search params', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 40 }, (_, index) => ({
      id: `anchor-${index}`,
      title: `锚点条目 ${index}`,
      url: `https://example.com/anchor-${index}`,
      published_at: new Date(Date.UTC(2026, 6, 17, 0, index)).toISOString(),
      user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
    }))
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items }),
      feedItem: vi.fn().mockImplementation((id: string) => {
        const publishedAt = items.find((item) => item.id === id)?.published_at ?? '2026-07-17T02:00:00Z'
        const detail = detailedItem(id, { published_at: publishedAt })
        if (detail.presentation) detail.presentation.timing.published_at = publishedAt
        return Promise.resolve(detail)
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const scrollTo = vi.fn()
    const originalScrollTo = HTMLElement.prototype.scrollTo
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo })
    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

      const shell = await screen.findByTestId('live-workbench-shell', undefined, { timeout: 5000 })
      const feedScroll = await screen.findByTestId('workbench-feed-scroll')
      await waitFor(() => expect(scrollTo).toHaveBeenCalled())
      Object.defineProperties(feedScroll, {
        scrollHeight: { configurable: true, value: 8000 },
        clientHeight: { configurable: true, value: 720 },
        scrollTop: { configurable: true, writable: true, value: 4200 },
      })
      fireEvent.scroll(feedScroll)
      const topVisibleCard = () => Array.from(feedScroll.querySelectorAll<HTMLElement>('[data-index]'))
        .filter((element) => Number(element.style.transform.match(/[-\d.]+/)?.[0] ?? 0) <= feedScroll.scrollTop)
        .sort((left, right) => Number(right.style.transform.match(/[-\d.]+/)?.[0] ?? 0) - Number(left.style.transform.match(/[-\d.]+/)?.[0] ?? 0))[0]
      const topCard = topVisibleCard()
      expect(topCard).toBeDefined()
      const topIndex = topCard.dataset.index
      scrollTo.mockClear()

      await user.click(within(topCard).getByRole('button', { name: /展开 锚点条目/ }))
      await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('item=anchor-'))
      await waitFor(() => expect(within(topCard).getByText('完整详情正文')).toBeInTheDocument())
      expect(screen.getByTestId('live-workbench-shell')).toBe(shell)
      expect(feedScroll.scrollTop).toBe(4200)
      expect(topVisibleCard()?.dataset.index).toBe(topIndex)
      expect(scrollTo.mock.calls.some(([options]) => Math.abs(Number((options as ScrollToOptions).top) - 4200) < 1000)).toBe(false)
    } finally {
      if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: originalScrollTo })
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
    }
  })

  it('rolls optimistic saves back inside a HeroUI-only failure surface', async () => {
    const user = userEvent.setup()
    const api = liveApi({
      updateItemState: vi.fn().mockRejectedValue(new ApiError(500, { code: 'save_failed', message: '收藏失败' })),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const save = await screen.findByRole('button', { name: '收藏 真实 API 条目' })
    await user.click(save)
    await waitFor(() => expect(screen.getByRole('button', { name: '收藏 真实 API 条目' })).toBeInTheDocument())
    expect(await screen.findByRole('alert')).toHaveTextContent('收藏失败，状态已恢复。')
    expect(document.querySelector('[class*="Mui"]')).not.toBeInTheDocument()
  })

  it('shows a recovery surface when a routed child crashes', async () => {
    const appModule = await import('./App')
    const Boundary = Reflect.get(appModule, 'AppErrorBoundary') as ComponentType<{ children: ReactNode }> | undefined
    expect(Boundary).toBeDefined()
    if (!Boundary) return

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function CrashingChild(): ReactNode {
      throw new Error('render failed')
    }
    try {
      render(<Boundary><CrashingChild /></Boundary>)
      expect(screen.getByRole('alert')).toHaveTextContent('页面加载失败')
      expect(screen.getByRole('link', { name: '返回信息流' })).toHaveAttribute('href', '/feed')
    } finally {
      consoleError.mockRestore()
    }
  })
})
