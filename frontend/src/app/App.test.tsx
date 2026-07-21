import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentType, ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { queryKeys } from '../api/queryKeys'
import type { ServiceApi } from '../api/service'
import type { FeedItem, Job } from '../api/types'
import { validateRegistryFields } from '../features/admin-heroui/sourceFormValidation'
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
    agentDelegations: vi.fn().mockResolvedValue({ enabled: true, subscription_writes_enabled: false, connections: [], mcp_url: '/mcp', openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5 }),
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
      content: { title: `详情标题 ${id}`, title_origin: 'native', excerpt: '详情摘录', body_text: '完整详情正文', content_kind: 'feed_summary', excerpt_truncated: false, body_truncated: false },
      taxonomy: { channel: '详情频道', configured_topics: [], inferred_topics: [], topics: ['详情主题'], entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'ai', score: 9, signal_strength: 'strong', signal_type: 'update', summary_zh: '详情概括' },
    },
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((next, fail) => {
    resolve = next
    reject = fail
  })
  return { promise, resolve, reject }
}

describe('App routes', () => {
  it('reports a non-finite source registry number before it can form a mutation payload', () => {
    const form = new FormData()
    form.set('limit', 'NaN')
    const errors = validateRegistryFields({ type: 'rss', fields: [{ name: 'limit', label: '获取数量', input_type: 'number', required: true, default: 1, min: 1, max: 10 }] }, form, {})
    expect(errors).toEqual({ limit: '获取数量必须是有效数字。' })
  })

  it('does not expose the removed fixed-data MUI preview route', async () => {
    const authStatus = vi.fn().mockResolvedValue({ authenticated: false, user: null })
    const api = { authStatus } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '登录私人信息雷达' }, { timeout: 5000 })).toBeInTheDocument()
    expect(authStatus).toHaveBeenCalled()
  })

  it('redirects protected deep links to the login page when no session exists', async () => {
    const api = { authStatus: vi.fn().mockResolvedValue({ authenticated: false, user: null }) } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/history?item=article-1']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '登录私人信息雷达' })).toBeInTheDocument()
  })

  it('renders the production feed with the authenticated HeroUI workbench', async () => {
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '信息流' }, { timeout: 5000 })).toBeInTheDocument()
    const itemCount = await screen.findByText('1 条内容')
    const orderControl = screen.getByRole('button', { name: '最新优先' })
    const refreshControl = screen.getByRole('button', { name: '更新信息流' })
    const filterControl = screen.getByRole('button', { name: '筛选信息流' })
    expect(itemCount).toHaveClass('type-control')
    expect(orderControl).toHaveClass('type-control')
    expect(refreshControl).toHaveClass('type-control')
    expect(filterControl).toHaveClass('type-control')
    expect(screen.getByTestId('feed-view-bar')).toBeInTheDocument()
    expect(screen.queryByText('旧内容在上，最新内容在下 · 1 条')).not.toBeInTheDocument()
    expect(screen.queryByText('全部', { exact: true })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('article', { name: '真实 API 条目' })).toBeInTheDocument())
    expect(api.latestFeed).toHaveBeenCalled()
    expect(api.agentDelegations).toHaveBeenCalled()
    expect(screen.queryByText('稍后读')).not.toBeInTheDocument()
  })

  it('places collection search and sorting inside the shared Quiet Studio ViewBar', async () => {
    const api = liveApi({
      savedFeed: vi.fn().mockResolvedValue({
        items: [{ id: 'saved-live', title: '收藏条目', url: 'https://example.com/saved-live', published_at: '2026-07-17T02:00:00Z', user_state: { is_saved: true, is_read: false, is_later: false, dismissed: false } }],
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/saved']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('article', { name: '收藏条目' })
    const viewBar = screen.getByTestId('collection-view-bar')
    expect(within(viewBar).getByPlaceholderText('搜索标题、来源或主题')).toBeInTheDocument()
    expect(within(viewBar).getByRole('button', { name: '最新优先' })).toBeInTheDocument()
    expect(within(viewBar).queryByRole('button', { name: '更新信息流' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
    expect(screen.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
    expect(screen.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-fresh-edge', 'start')
  })

  it('shows newest Feed cards first and persists the order toggle', async () => {
    window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    const api = liveApi({ latestFeed: vi.fn().mockResolvedValue({
      schema_version: 2,
      items: [
        { id: 'older', title: '较早内容', url: 'https://example.com/older', published_at: '2026-07-17T01:00:00Z' },
        { id: 'newer', title: '最新内容', url: 'https://example.com/newer', published_at: '2026-07-17T03:00:00Z' },
      ],
    }) })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('article', { name: '最新内容' })
    expect(screen.getAllByRole('article').map((article) => article.getAttribute('aria-label'))).toEqual(['最新内容', '较早内容'])
    await userEvent.click(screen.getByRole('button', { name: '最新优先' }))
    expect(screen.getByRole('button', { name: '最旧优先' })).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.feed.v2:user-live') || '{}')).toMatchObject({ order: 'oldest' })
  })

  it('shows the Feed active-filter count for persisted preferences', async () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-live', JSON.stringify({ unreadFirst: true, source: 'detail-source', channel: '', topic: '', minScore: 8 }))
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByLabelText('已启用 3 项筛选')).toHaveTextContent('3')
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('renders production administration routes in the HeroUI shell without an Agent panel', async () => {
    const source = {
      id: 'source-live', type: 'rss', display_name: '覆盖频道来源', scope: 'private' as const,
      owner_user_id: 'user-live', default_channel: '工作/项目', enabled: true,
    }
    const subscription = {
      id: 'subscription-live', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name,
      source_type: source.type, enabled: true, priority: 80, override_channel: 'AI',
      schedule: { enabled: false, interval_minutes: 60, worker_status: 'ready' },
    }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', label: 'RSS / Atom', fields: [] }] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 1, degraded: 0, failing: 0, unknown: 0, total: 1 },
        items: [{ subscription_id: subscription.id, source_id: source.id, status: 'healthy', consecutive_failures: 0 }],
      }),
      config: vi.fn().mockResolvedValue({ config: { tags: [] }, taxonomy: { channels: ['AI', '其他'], topics: [] } }),
      createSourceFetch: vi.fn().mockResolvedValue({ id: 'source-fetch-live', user_id: 'user-live', job_type: 'source_fetch', status: 'queued' }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '订阅与来源' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelector('[data-page-frame="admin"]')).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(screen.queryByRole('complementary', { name: 'OpenClaw 上下文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Agent 面板/ })).not.toBeInTheDocument()
    expect(document.querySelector('[class*="Mui"]')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'AI' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '工作/项目' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '收起 AI' }))
    expect(screen.queryByRole('button', { name: '立即获取 覆盖频道来源' })).not.toBeInTheDocument()
    const desktopFilters = document.querySelector('[data-desktop-source-filters]') as HTMLElement
    await userEvent.type(within(desktopFilters).getByRole('searchbox', { name: '搜索来源' }), '覆盖频道')
    expect(screen.getByRole('button', { name: '立即获取 覆盖频道来源' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '立即获取 覆盖频道来源' }))
    expect(api.feedSchedule).toHaveBeenCalled()
    expect(api.createSourceFetch).toHaveBeenCalledWith(source.id, subscription.id)
  }, 10_000)

  it('operates live source type, health and scope filters together', async () => {
    const browser = userEvent.setup()
    const sources = [
      { id: 'filter-private', type: 'rss', display_name: 'Private Healthy', scope: 'private' as const, owner_user_id: 'filter-owner', default_channel: 'AI', enabled: true },
      { id: 'filter-workspace', type: 'github_release', display_name: 'Workspace Failing', scope: 'workspace' as const, default_channel: 'AI', enabled: true },
      { id: 'filter-public', type: 'rss', display_name: 'Public Degraded', scope: 'public' as const, default_channel: 'AI', enabled: true },
    ]
    const subscriptions = sources.map((source, index) => ({ id: `filter-sub-${index}`, user_id: 'filter-owner', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true, priority: index }))
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'filter-owner', username: 'owner', role: 'owner', enabled: true } }),
      sources: vi.fn().mockResolvedValue({ sources }), subscriptions: vi.fn().mockResolvedValue({ subscriptions }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }, { type: 'github_release', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 1, degraded: 1, failing: 1, unknown: 0, total: 3 }, items: [
        { subscription_id: 'filter-sub-0', source_id: 'filter-private', status: 'healthy', consecutive_failures: 0 },
        { subscription_id: 'filter-sub-1', source_id: 'filter-workspace', status: 'failing', consecutive_failures: 3 },
        { subscription_id: 'filter-sub-2', source_id: 'filter-public', status: 'degraded', consecutive_failures: 1 },
      ] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }), secrets: vi.fn().mockResolvedValue({ secrets: [] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByText('Workspace Failing')
    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: 'GitHub 发布' }))
    expect(screen.getByText('Workspace Failing')).toBeInTheDocument()
    expect(screen.queryByText('Private Healthy')).not.toBeInTheDocument()
    expect(screen.queryByText('Public Degraded')).not.toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /健康状态/ }))
    await browser.click(await screen.findByRole('option', { name: '连续失败' }))
    await browser.click(screen.getByRole('button', { name: /可见范围/ }))
    await browser.click(await screen.findByRole('option', { name: '团队来源' }))
    expect(screen.getByText('Workspace Failing')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /健康状态/ }))
    await browser.click(await screen.findByRole('option', { name: '正常' }))
    expect(screen.getByText('没有匹配的订阅')).toBeInTheDocument()
  })

  it('keeps source failure details behind a status tooltip and dialog', async () => {
    const browser = userEvent.setup()
    const source = { id: 'health-source', type: 'rss', display_name: '异常来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'health-subscription', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true }
    const rawMessage = '503 Server Error while fetching https://upstream.example/private-feed'
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 1, unknown: 0, total: 1 }, items: [{ subscription_id: subscription.id, source_id: source.id, status: 'failing', consecutive_failures: 3, last_issue: { stage: 'fetch', code: 'HTTPError', message: rawMessage, retryable: true } }] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const card = (await screen.findByText('异常来源')).closest('[data-slot="card"]') as HTMLElement
    expect(within(card).queryByText(/原因：/)).not.toBeInTheDocument()
    expect(within(card).queryByText(rawMessage)).not.toBeInTheDocument()

    const trigger = within(card).getByRole('button', { name: '查看 连续失败 详情' })
    await browser.hover(trigger)
    expect(await screen.findByText('已连续 3 次失败：上游服务暂时不可用或响应超时。')).toBeInTheDocument()
    await browser.click(trigger)

    const dialog = await screen.findByRole('dialog', { name: '来源获取失败' })
    expect(within(dialog).getByText('上游服务暂时不可用或响应超时。')).toBeInTheDocument()
    expect(within(dialog).getByText('已连续 3 次更新失败，该来源的新内容暂时不会进入信息流；历史内容不受影响。')).toBeInTheDocument()
    expect(within(dialog).getByText('点击“立即获取”重试；若仍失败，请稍后再试或检查上游状态。')).toBeInTheDocument()

    const details = within(dialog).getByText('技术详情').closest('details')
    const rawDiagnostics = within(dialog).getByText(rawMessage)
    expect(details).not.toHaveAttribute('open')
    expect(rawDiagnostics.closest('details')).toBe(details)
    expect(rawDiagnostics).not.toBeVisible()
    await browser.click(within(dialog).getByText('技术详情'))
    expect(details).toHaveAttribute('open')
    expect(rawDiagnostics).toBeVisible()
    await browser.click(within(dialog).getByRole('button', { name: '关闭' }))
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('shows source edit controls only for a member-owned private source', async () => {
    const sources = [
      { id: 'matrix-own', type: 'rss', display_name: 'Own Private', scope: 'private' as const, owner_user_id: 'matrix-member', default_channel: 'AI', enabled: true },
      { id: 'matrix-other', type: 'rss', display_name: 'Other Private', scope: 'private' as const, owner_user_id: 'other-member', default_channel: 'AI', enabled: true },
      { id: 'matrix-shared', type: 'rss', display_name: 'Workspace Shared', scope: 'workspace' as const, default_channel: 'AI', enabled: true },
      { id: 'matrix-public', type: 'rss', display_name: 'Public Shared', scope: 'public' as const, default_channel: 'AI', enabled: true },
    ]
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'matrix-member', username: 'member', role: 'member', enabled: true } }), sources: vi.fn().mockResolvedValue({ sources }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: sources.map((source, index) => ({ id: `matrix-sub-${index}`, user_id: 'matrix-member', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true })) }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }), sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 4, total: 4 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('button', { name: '编辑 Own Private 来源' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑 Other Private 来源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑 Workspace Shared 来源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑 Public Shared 来源' })).not.toBeInTheDocument()
  })

  it('protects and explicitly clears a live one-time Agent token', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      agentDelegations: vi.fn().mockResolvedValue({ enabled: true, subscription_writes_enabled: false, mcp_url: '/mcp', openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5, connections: [] }),
      createAgentDelegation: vi.fn().mockResolvedValue({
        connection: { id: 'agent-new', name: 'Desk Mac', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'], token_prefix: 'ih_new', created_at: '2026-07-17T00:00:00Z', expires_at: '2026-10-17T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' },
        token: 'ih_mcp_one_time_live',
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/agents']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '助手连接' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelector('[data-page-frame="admin"]')).toBeInTheDocument()
    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const createDialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.type(within(createDialog).getByRole('textbox', { name: '连接名称' }), 'Desk Mac')
    await browser.click(within(createDialog).getByRole('button', { name: '生成一次性令牌' }))
    const tokenDialog = await screen.findByRole('dialog', { name: '保存一次性 MCP token' })
    expect(within(tokenDialog).getByText('ih_mcp_one_time_live')).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '保存一次性 MCP token' })).toBeInTheDocument()
    await browser.click(screen.getByTestId('one-time-token-backdrop'))
    expect(screen.getByRole('dialog', { name: '保存一次性 MCP token' })).toBeInTheDocument()
    await browser.click(within(tokenDialog).getByRole('button', { name: '我已保存' }))
    expect(screen.queryByText('ih_mcp_one_time_live')).not.toBeInTheDocument()
    expect(JSON.stringify(queryClient.getQueryCache().getAll())).not.toContain('ih_mcp_one_time_live')
    expect(document.querySelector('[class*="Mui"]')).not.toBeInTheDocument()
  }, 10_000)

  it('explains a live single-source fetch block without queueing work', async () => {
    const browser = userEvent.setup()
    const source = { id: 'blocked-source', type: 'rss', display_name: '阻塞来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'blocked-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true, priority: 0 }
    const createSourceFetch = vi.fn()
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', label: 'RSS / Atom', fields: [] }] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: { tags: [] }, taxonomy: { channels: ['AI'], topics: [] } }),
      feedSchedule: vi.fn().mockResolvedValue({ enabled: false, interval_minutes: 360, worker_status: 'stale' }),
      createSourceFetch,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '立即获取 阻塞来源' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('后台获取服务当前不可用')
    expect(createSourceFetch).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '关闭通知' }))
    expect(screen.queryByText(/后台获取服务当前不可用/)).not.toBeInTheDocument()
  })

  it('settles a live source fetch through queued, running and terminal lifecycle states', async () => {
    const browser = userEvent.setup()
    const source = { id: 'lifecycle-source', type: 'rss', display_name: '生命周期来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'lifecycle-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true, priority: 0 }
    const queued: Job = { id: 'lifecycle-job', user_id: 'user-live', job_type: 'source_fetch', source_id: source.id, subscription_id: subscription.id, status: 'queued', created_at: '2026-07-17T01:00:00Z' }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', label: 'RSS / Atom', fields: [] }] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: { tags: [] }, taxonomy: { channels: ['AI'], topics: [] } }),
      jobs: vi.fn().mockResolvedValue({ jobs: [] }),
      createSourceFetch: vi.fn().mockResolvedValue(queued),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '立即获取 生命周期来源' }))
    expect(await screen.findByRole('button', { name: '已排队 生命周期来源' })).toBeDisabled()
    invalidate.mockClear()

    act(() => queryClient.setQueryData(queryKeys.jobs('user-live'), { jobs: [{ ...queued, status: 'running', started_at: '2026-07-17T01:00:01Z' }] }))
    expect(await screen.findByRole('button', { name: '获取中 生命周期来源' })).toBeDisabled()
    expect(invalidate).not.toHaveBeenCalled()

    act(() => queryClient.setQueryData(queryKeys.jobs('user-live'), { jobs: [{ ...queued, status: 'succeeded', started_at: '2026-07-17T01:00:01Z', finished_at: '2026-07-17T01:00:03Z', result: { item_count: 4 } }] }))
    expect(await screen.findByText('生命周期来源 获取完成，共 4 条。')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '立即获取 生命周期来源' })).toBeEnabled()
    await waitFor(() => {
      const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
      expect(keys).toContain(JSON.stringify(queryKeys.sourceHealth('user-live')))
      expect(keys).toContain(JSON.stringify(queryKeys.jobs('user-live')))
      expect(keys).toContain(JSON.stringify(['user', 'user-live', 'feed']))
      expect(keys).toContain(JSON.stringify(queryKeys.history('user-live')))
    })
  }, 10_000)

  it('keeps a manually dismissed source-fetch terminal notice closed across polling rerenders', async () => {
    const browser = userEvent.setup()
    const source = { id: 'dismiss-source', type: 'rss', display_name: '可关闭来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'dismiss-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true }
    const queued: Job = { id: 'dismiss-job', user_id: 'user-live', job_type: 'source_fetch', source_id: source.id, subscription_id: subscription.id, status: 'queued', created_at: '2026-07-17T01:00:00Z' }
    const terminal: Job = { ...queued, status: 'failed', finished_at: '2026-07-17T01:00:01Z', error_message: '可关闭的抓取失败' }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }), sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }), jobs: vi.fn().mockResolvedValue({ jobs: [] }), createSourceFetch: vi.fn().mockResolvedValue(queued),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '立即获取 可关闭来源' }))
    act(() => queryClient.setQueryData(queryKeys.jobs('user-live'), { jobs: [terminal] }))
    expect(await screen.findByText('可关闭的抓取失败')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '关闭通知' }))
    expect(screen.queryByText('可关闭的抓取失败')).not.toBeInTheDocument()

    await act(async () => {
      queryClient.setQueryData(queryKeys.jobs('user-live'), { jobs: [{ ...terminal }] })
      await Promise.resolve()
    })
    expect(screen.queryByText('可关闭的抓取失败')).not.toBeInTheDocument()
  })

  it.each([
    ['partial', undefined, '终态来源 部分完成，请查看运行记录。'],
    ['failed', '上游连接超时', '上游连接超时'],
    ['cancelled', undefined, '终态来源 获取已取消。'],
  ] as const)('surfaces sanitized live source fetch terminal state %s', async (status, errorMessage, expected) => {
    const browser = userEvent.setup()
    const source = { id: `terminal-${status}`, type: 'rss', display_name: '终态来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: `terminal-sub-${status}`, user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true, priority: 0 }
    const queued: Job = { id: `terminal-job-${status}`, user_id: 'user-live', job_type: 'source_fetch', source_id: source.id, subscription_id: subscription.id, status: 'queued', created_at: '2026-07-17T01:00:00Z' }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }), sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }), jobs: vi.fn().mockResolvedValue({ jobs: [] }), createSourceFetch: vi.fn().mockResolvedValue(queued),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '立即获取 终态来源' }))
    act(() => queryClient.setQueryData(queryKeys.jobs('user-live'), { jobs: [{ ...queued, status, error_message: errorMessage, retryable: status === 'failed', result: { debug_payload: 'never expose this terminal payload' } }] }))
    expect(await screen.findByText(expected)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '立即获取 终态来源' })).toBeEnabled()
    expect(screen.queryByText('never expose this terminal payload')).not.toBeInTheDocument()
  }, 10_000)

  it('shows run creation and completion times as separate fields with a pending fallback', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }), sourceTypes: vi.fn().mockResolvedValue({ source_types: [] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: [], topics: [] } }),
      jobs: vi.fn().mockResolvedValue({ jobs: [
        { id: 'pending-job', user_id: 'user-live', job_type: 'source_fetch', status: 'running', created_at: '2026-07-17T01:00:00Z', started_at: '2026-07-17T01:00:01Z' },
        { id: 'done-job', user_id: 'user-live', job_type: 'source_test', status: 'succeeded', created_at: '2026-07-17T02:00:00Z', finished_at: '2026-07-17T02:00:04Z' },
        { id: 'failed-job', user_id: 'user-live', job_type: 'source_fetch', status: 'failed', created_at: '2026-07-17T03:00:00Z', finished_at: '2026-07-17T03:00:04Z', retryable: true, error_message: '安全错误摘要' },
      ] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('tab', { name: '运行记录' }))
    expect(await screen.findAllByText(/创建：.*2026/)).toHaveLength(3)
    expect(screen.getByText('完成：尚未完成')).toBeInTheDocument()
    expect(screen.getAllByText(/完成：.*2026/)).toHaveLength(2)
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
  })

  it('scopes live schedule, subscribe, unsubscribe and retry pending controls to their own entity', async () => {
    const browser = userEvent.setup()
    const subscribedSource = { id: 'pending-subscribed', type: 'rss', display_name: '已订阅来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const availableSource = { id: 'pending-available', type: 'rss', display_name: '未订阅来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'pending-subscription', user_id: 'user-live', source_id: subscribedSource.id, source_display_name: subscribedSource.display_name, source_type: subscribedSource.type, enabled: true }
    const scheduleRequest = deferred<unknown>()
    const subscribeRequest = deferred<unknown>()
    const unsubscribeRequest = deferred<unknown>()
    const retryRequest = deferred<unknown>()
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [subscribedSource, availableSource] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      jobs: vi.fn().mockResolvedValue({ jobs: [{ id: 'pending-retry-job', user_id: 'user-live', job_type: 'source_fetch', source_id: subscribedSource.id, status: 'failed', retryable: true, created_at: '2026-07-17T01:00:00Z', finished_at: '2026-07-17T01:00:01Z' }] }),
      updateFeedSchedule: vi.fn().mockReturnValue(scheduleRequest.promise),
      subscribe: vi.fn().mockReturnValue(subscribeRequest.promise),
      unsubscribe: vi.fn().mockReturnValue(unsubscribeRequest.promise),
      retryJob: vi.fn().mockReturnValue(retryRequest.promise),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '关闭自动更新' }))
    const schedulePending = await screen.findByRole('button', { name: '更新中 自动更新' })
    expect(schedulePending).toBeDisabled()
    expect(screen.getByRole('button', { name: /更新周期/ })).toBeDisabled()
    fireEvent.click(schedulePending)
    expect(api.updateFeedSchedule).toHaveBeenCalledOnce()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    const unsubscribeButton = await screen.findByRole('button', { name: '取消订阅 已订阅来源' })
    const subscribeButton = screen.getByRole('button', { name: '订阅 未订阅来源' })
    await browser.click(unsubscribeButton)
    const unsubscribePending = await screen.findByRole('button', { name: '取消中 已订阅来源' })
    expect(unsubscribePending).toBeDisabled()
    expect(subscribeButton).toBeEnabled()
    fireEvent.click(unsubscribePending)
    expect(api.unsubscribe).toHaveBeenCalledOnce()

    await browser.click(subscribeButton)
    const subscribePending = await screen.findByRole('button', { name: '订阅中 未订阅来源' })
    expect(subscribePending).toBeDisabled()
    expect(unsubscribePending).toBeDisabled()
    fireEvent.click(subscribePending)
    expect(api.subscribe).toHaveBeenCalledOnce()

    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    await browser.click(await screen.findByRole('button', { name: '重试' }))
    const retryPending = await screen.findByRole('button', { name: /重试中/ })
    expect(retryPending).toBeDisabled()
    fireEvent.click(retryPending)
    expect(api.retryJob).toHaveBeenCalledOnce()
  })

  it('keeps successful live mutations pending until refreshed server state is ready', async () => {
    const browser = userEvent.setup()
    const subscribedSource = { id: 'refresh-subscribed', type: 'rss', display_name: '刷新前已订阅', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const availableSource = { id: 'refresh-available', type: 'rss', display_name: '刷新前未订阅', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const originalSubscription = { id: 'refresh-original-sub', user_id: 'user-live', source_id: subscribedSource.id, source_display_name: subscribedSource.display_name, source_type: subscribedSource.type, enabled: true }
    const refreshedSubscription = { id: 'refresh-new-sub', user_id: 'user-live', source_id: availableSource.id, source_display_name: availableSource.display_name, source_type: availableSource.type, enabled: true }
    const retryJob = { id: 'refresh-retry-job', user_id: 'user-live', job_type: 'source_fetch' as const, source_id: subscribedSource.id, status: 'failed' as const, retryable: true, created_at: '2026-07-17T01:00:00Z', finished_at: '2026-07-17T01:00:01Z' }
    const scheduleRequest = deferred<unknown>()
    const subscribeRequest = deferred<unknown>()
    const unsubscribeRequest = deferred<unknown>()
    const retryRequest = deferred<unknown>()
    const invalidation = deferred<void>()
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [subscribedSource, availableSource] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [originalSubscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }), sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }), jobs: vi.fn().mockResolvedValue({ jobs: [retryJob] }),
      updateFeedSchedule: vi.fn().mockReturnValue(scheduleRequest.promise), subscribe: vi.fn().mockReturnValue(subscribeRequest.promise), unsubscribe: vi.fn().mockReturnValue(unsubscribeRequest.promise), retryJob: vi.fn().mockReturnValue(retryRequest.promise),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockReturnValue(invalidation.promise)
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const scheduleButton = await screen.findByRole('button', { name: '关闭自动更新' })
    invalidate.mockClear()
    await browser.click(scheduleButton)
    expect(await screen.findByRole('button', { name: '更新中 自动更新' })).toBeDisabled()
    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    await browser.click(await screen.findByRole('button', { name: '取消订阅 刷新前已订阅' }))
    expect(await screen.findByRole('button', { name: '取消中 刷新前已订阅' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '订阅 刷新前未订阅' }))
    expect(await screen.findByRole('button', { name: '订阅中 刷新前未订阅' })).toBeDisabled()
    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    await browser.click(await screen.findByRole('button', { name: '重试' }))
    expect(await screen.findByRole('button', { name: /重试中/ })).toBeDisabled()

    await act(async () => {
      scheduleRequest.resolve({})
      subscribeRequest.resolve({})
      unsubscribeRequest.resolve({})
      retryRequest.resolve({})
      await Promise.resolve()
    })
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(19))

    await browser.click(screen.getByRole('tab', { name: '我的订阅' }))
    const schedulePending = screen.getByRole('button', { name: '更新中 自动更新' })
    expect(schedulePending).toBeDisabled()
    fireEvent.click(schedulePending)
    expect(api.updateFeedSchedule).toHaveBeenCalledOnce()

    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    const retryPending = screen.getByRole('button', { name: /重试中/ })
    expect(retryPending).toBeDisabled()
    fireEvent.click(retryPending)
    expect(api.retryJob).toHaveBeenCalledOnce()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    const unsubscribePending = screen.getByRole('button', { name: '取消中 刷新前已订阅' })
    const subscribePending = screen.getByRole('button', { name: '订阅中 刷新前未订阅' })
    fireEvent.click(unsubscribePending)
    fireEvent.click(subscribePending)
    expect(api.unsubscribe).toHaveBeenCalledOnce()
    expect(api.subscribe).toHaveBeenCalledOnce()

    act(() => {
      queryClient.setQueryData(queryKeys.feedSchedule('user-live'), { enabled: false, interval_minutes: 60, worker_status: 'ready' })
      queryClient.setQueryData(queryKeys.subscriptions('user-live'), { subscriptions: [refreshedSubscription] })
      queryClient.setQueryData(queryKeys.jobs('user-live'), { jobs: [{ ...retryJob, status: 'queued', retryable: false }] })
      invalidation.resolve()
    })

    await browser.click(screen.getByRole('tab', { name: '我的订阅' }))
    expect(await screen.findByRole('button', { name: '开启自动更新' })).toBeEnabled()
    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    expect(await screen.findByRole('button', { name: '订阅 刷新前已订阅' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '取消订阅 刷新前未订阅' })).toBeEnabled()
    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeInTheDocument()
  })

  it('renders local accessible errors for live schedule, subscribe, unsubscribe and retry actions', async () => {
    const browser = userEvent.setup()
    const subscribedSource = { id: 'error-subscribed', type: 'rss', display_name: '错误已订阅来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const availableSource = { id: 'error-available', type: 'rss', display_name: '错误未订阅来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'error-subscription', user_id: 'user-live', source_id: subscribedSource.id, source_display_name: subscribedSource.display_name, source_type: subscribedSource.type, enabled: true }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [subscribedSource, availableSource] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }), sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      jobs: vi.fn().mockResolvedValue({ jobs: [{ id: 'error-retry-job', user_id: 'user-live', job_type: 'source_fetch', source_id: subscribedSource.id, status: 'failed', retryable: true, created_at: '2026-07-17T01:00:00Z', finished_at: '2026-07-17T01:00:01Z' }] }),
      updateFeedSchedule: vi.fn().mockRejectedValue(new Error('计划保存失败')),
      subscribe: vi.fn().mockRejectedValue(new Error('订阅请求失败')),
      unsubscribe: vi.fn().mockRejectedValue(new Error('取消订阅失败')),
      retryJob: vi.fn().mockRejectedValue(new Error('重试请求失败')),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '关闭自动更新' }))
    expect((await screen.findByText('计划保存失败')).closest('[role="alert"]')).not.toBeNull()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    await browser.click(await screen.findByRole('button', { name: '取消订阅 错误已订阅来源' }))
    expect((await screen.findByText('取消订阅失败')).closest('[role="alert"]')).not.toBeNull()
    await browser.click(screen.getByRole('button', { name: '订阅 错误未订阅来源' }))
    expect((await screen.findByText('订阅请求失败')).closest('[role="alert"]')).not.toBeNull()

    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    await browser.click(await screen.findByRole('button', { name: '重试' }))
    expect((await screen.findByText('重试请求失败')).closest('[role="alert"]')).not.toBeNull()
  })

  it('shows role-scoped live settings and clears only a failed secret value', async () => {
    const browser = userEvent.setup()
    const createSecret = vi.fn().mockRejectedValue(new ApiError(400, { code: 'invalid_secret', message: 'Key 保存失败' }))
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-live', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: ['AI'], topics: ['Agent'] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      createSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '助手与 AI' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelector('[data-page-frame="admin"]')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '获取与主题' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '密钥' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '成员' })).toBeInTheDocument()
    expect(screen.queryByText('精选阈值')).not.toBeInTheDocument()
    expect(screen.queryByText('日报阈值')).not.toBeInTheDocument()
    expect(screen.queryByText('日报条数')).not.toBeInTheDocument()

    await browser.type(screen.getByRole('textbox', { name: 'Key 名称' }), 'DeepSeek')
    await browser.type(screen.getByRole('textbox', { name: 'Key provider' }), 'deepseek')
    await browser.type(screen.getByRole('textbox', { name: '环境变量名' }), 'DEEPSEEK_API_KEY')
    await browser.type(screen.getByLabelText('Key 值'), 'secret-value')
    await browser.click(screen.getByRole('button', { name: '新增 Key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Key 保存失败')
    expect(screen.getByRole('textbox', { name: 'Key 名称' })).toHaveValue('DeepSeek')
    expect(screen.getByRole('textbox', { name: 'Key provider' })).toHaveValue('deepseek')
    expect(screen.getByRole('textbox', { name: '环境变量名' })).toHaveValue('DEEPSEEK_API_KEY')
    expect(screen.getByLabelText('Key 值')).toHaveValue('')
  }, 10_000)

  it('requires explicit confirmation before deleting an unused secret', async () => {
    const browser = userEvent.setup()
    const deletion = deferred<void>()
    const deleteSecret = vi.fn().mockReturnValue(deletion.promise)
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-delete', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [{ id: 'unused-key', name: 'Unused Key', kind: 'ai', provider: 'openai', env_name: 'UNUSED_KEY', is_set: true, used_by: [] }] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      deleteSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const card = (await screen.findByText('Unused Key')).closest('[data-slot="card"]') as HTMLElement
    const trigger = within(card).getByRole('button', { name: '删除' })
    await browser.click(trigger)
    expect(screen.getByRole('dialog', { name: '删除 Unused Key？' })).toBeInTheDocument()
    expect(deleteSecret).not.toHaveBeenCalled()

    await browser.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '删除 Unused Key？' })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
    expect(deleteSecret).not.toHaveBeenCalled()

    await browser.click(trigger)
    await browser.click(screen.getByRole('button', { name: '取消删除' }))
    expect(deleteSecret).not.toHaveBeenCalled()

    await browser.click(trigger)
    await browser.click(screen.getByRole('button', { name: '确认删除' }))
    expect(deleteSecret).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '删除中…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '取消删除' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '删除中…' }))
    expect(deleteSecret).toHaveBeenCalledTimes(1)

    deletion.resolve()
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '删除 Unused Key？' })).not.toBeInTheDocument())
  })

  it('keeps the secret confirmation open when deletion fails', async () => {
    const browser = userEvent.setup()
    const deleteSecret = vi.fn().mockRejectedValue(new ApiError(503, { code: 'secret_delete_failed', message: '密钥删除失败，请稍后重试。' }))
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-delete-failure', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [{ id: 'failed-key', name: 'Failed Key', kind: 'ai', provider: 'openai', env_name: 'FAILED_KEY', is_set: true, used_by: [] }] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      deleteSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const card = (await screen.findByText('Failed Key')).closest('[data-slot="card"]') as HTMLElement
    await browser.click(within(card).getByRole('button', { name: '删除' }))
    await browser.click(screen.getByRole('button', { name: '确认删除' }))

    const dialog = screen.getByRole('dialog', { name: '删除 Failed Key？' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('密钥删除失败，请稍后重试。')
    expect(dialog).toBeInTheDocument()
    expect(deleteSecret).toHaveBeenCalledTimes(1)
  })

  it('uses the production HeroUI login without changing login errors', async () => {
    const browser = userEvent.setup()
    const api = {
      authStatus: vi.fn().mockResolvedValue({ authenticated: false, user: null }),
      login: vi.fn().mockRejectedValue(new ApiError(401, { code: 'invalid_credentials', message: '账号或密码错误' })),
    } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/login']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '登录私人信息雷达' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelector('[data-page-frame="auth"]')).toBeInTheDocument()
    await browser.type(screen.getByLabelText('用户名'), 'owner')
    await browser.type(screen.getByLabelText('密码'), 'wrong-secret')
    await browser.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码错误')
    expect(screen.getByLabelText('密码')).toHaveValue('')
    expect(api.login).toHaveBeenCalledWith('owner', 'wrong-secret')
  })

  it('redirects a successful HeroUI login back into the production workbench', async () => {
    const browser = userEvent.setup()
    let authenticated = false
    const user = { id: 'login-live', username: 'owner', role: 'owner' as const, enabled: true }
    const api = liveApi({
      authStatus: vi.fn().mockImplementation(async () => ({ authenticated, user: authenticated ? user : null })),
      login: vi.fn().mockImplementation(async () => { authenticated = true; return { authenticated: true, user } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/login']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await browser.type(await screen.findByLabelText('用户名'), 'owner')
    await browser.type(screen.getByLabelText('密码'), 'correct-secret')
    await browser.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/feed'))
    expect(api.login).toHaveBeenCalledWith('owner', 'correct-secret')
    expect(await screen.findByRole('heading', { name: '信息流' })).toBeInTheDocument()
  })

  it('keeps advanced source configuration visible without a nested native details editor', async () => {
    const browser = userEvent.setup()
    const source = { id: 'advanced-source', type: 'rss', display_name: 'Advanced RSS', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true, config: { url: 'https://example.com/rss.xml' } }
    const subscription = { id: 'advanced-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', label: 'RSS / Atom', fields: [{ name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '' }] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '编辑 Advanced RSS 来源' }))
    const dialog = await screen.findByRole('dialog', { name: 'Advanced RSS · 来源设置' })
    expect(within(dialog).getByText('高级配置')).toBeVisible()
    expect(dialog.querySelector('details')).not.toBeInTheDocument()
  })

  it('blocks incomplete required Apify options and submits their real registry metadata after selection', async () => {
    const browser = userEvent.setup()
    const createSource = vi.fn().mockResolvedValue({ id: 'apify-new' })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{
        type: 'apify_social', label: 'Apify 社交来源', fields: [
          { name: 'platform', label: '平台', input_type: 'select', required: true, default: '', options: [{ value: 'x', label: 'X' }], help: '选择要抓取的平台。' },
          { name: 'kind', label: '来源类别', input_type: 'select', required: true, default: '', options: [{ value: 'account', label: '账号' }], help: '选择账号或关键词来源。' },
        ],
      }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      createSource,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '新增来源' }))
    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: 'Apify 社交来源' }))
    await browser.type(await screen.findByRole('textbox', { name: '来源名称' }), 'Codex 动态')
    const platformControl = screen.getByLabelText('平台')
    const kindControl = screen.getByLabelText('来源类别')
    expect(platformControl.parentElement).toHaveAttribute('data-required', 'true')
    expect(kindControl.parentElement).toHaveAttribute('data-required', 'true')
    expect(platformControl.parentElement?.querySelector('select')).toBeRequired()
    expect(kindControl.parentElement?.querySelector('select')).toBeRequired()
    expect(screen.getByText('选择要抓取的平台。')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(createSource).not.toHaveBeenCalled()
    expect(await screen.findByText('平台不能为空。')).toBeInTheDocument()
    expect(screen.getByText('来源类别不能为空。')).toBeInTheDocument()

    await browser.click(screen.getByLabelText('平台'))
    await browser.click(await screen.findByRole('option', { name: 'X' }))
    await browser.click(screen.getByLabelText('来源类别'))
    await browser.click(await screen.findByRole('option', { name: '账号' }))
    expect(screen.getByLabelText('平台')).toHaveTextContent('X')
    expect(screen.getByLabelText('来源类别')).toHaveTextContent('账号')
    expect(screen.queryByText('平台不能为空。')).not.toBeInTheDocument()
    expect(screen.queryByText('来源类别不能为空。')).not.toBeInTheDocument()
    const sourceForm = screen.getByRole('button', { name: '创建来源' }).closest('form') as HTMLFormElement
    expect(Array.from(sourceForm.elements).filter((element): element is HTMLInputElement => element instanceof HTMLInputElement && !element.validity.valid).map((element) => ({ name: element.name, value: element.value, required: element.required, validity: element.validity.valid }))).toEqual([])
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    await waitFor(() => expect(createSource).toHaveBeenCalledWith(expect.objectContaining({
      config: expect.objectContaining({ platform: 'x', kind: 'account' }),
    })))
  })

  it('keeps invalid registry source fields out of submission and explains their constraints', async () => {
    const browser = userEvent.setup()
    const createSource = vi.fn().mockResolvedValue({ id: 'validated-source' })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{
        type: 'validated_rss', label: '受限 RSS', fields: [
          { name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '', help: '请输入完整的 HTTPS 地址。' },
          { name: 'limit', label: '获取数量', input_type: 'number', required: true, default: 3, min: 1, max: 10, help: '范围为 1 到 10。' },
          { name: 'include_archived', label: '包含归档内容', input_type: 'boolean', required: false, default: false, help: '仅在需要历史内容时开启。' },
        ],
      }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      createSource,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '新增来源' }))
    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: '受限 RSS' }))
    expect(screen.getByText('请输入完整的 HTTPS 地址。')).toBeInTheDocument()
    expect(screen.getByText('范围为 1 到 10。')).toBeInTheDocument()
    expect(screen.getByText('仅在需要历史内容时开启。')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(await screen.findByText('来源名称不能为空。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.type(screen.getByRole('textbox', { name: '来源名称' }), '受限订阅')
    await browser.type(screen.getByRole('textbox', { name: 'RSS 地址' }), 'not-a-url')
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(await screen.findByText('RSS 地址必须是有效 URL。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    const url = screen.getByRole('textbox', { name: 'RSS 地址' })
    const limit = screen.getByRole('spinbutton', { name: '获取数量' })
    await browser.clear(url)
    await browser.type(url, 'https://example.com/feed.xml')
    await browser.clear(limit)
    await browser.type(limit, '11')
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(await screen.findByText('获取数量不能大于 10。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    await browser.type(limit, '0')
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(await screen.findByText('获取数量不能小于 1。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    await browser.type(limit, '1.5')
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(await screen.findByText('获取数量必须是整数。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    fireEvent.input(limit, { target: { value: 'NaN' } })
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    expect(await screen.findByText(/获取数量(不能为空|必须是有效数字)。/)).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    await browser.type(limit, '4')
    await browser.click(screen.getByRole('button', { name: '创建来源' }))
    await waitFor(() => expect(createSource).toHaveBeenCalledWith(expect.objectContaining({ config: expect.objectContaining({ url: 'https://example.com/feed.xml', limit: 4 }) })))
  })

  it('resets registry defaults when the create-source type changes', async () => {
    const browser = userEvent.setup()
    const createSource = vi.fn().mockResolvedValue({ id: 'switched-source' })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [
        {
          type: 'first_registry', label: '第一种来源', fields: [
            { name: 'mode', label: '抓取模式', input_type: 'select', required: true, default: 'first', options: [{ value: 'first', label: '第一默认值' }] },
          ],
        },
        {
          type: 'second_registry', label: '第二种来源', fields: [
            { name: 'mode', label: '抓取模式', input_type: 'select', required: true, default: 'second', options: [{ value: 'second', label: '第二默认值' }] },
          ],
        },
      ] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      createSource,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '新增来源' }))
    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: '第一种来源' }))
    expect(screen.getByLabelText('抓取模式')).toHaveTextContent('第一默认值')

    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: '第二种来源' }))
    expect(screen.getByLabelText('抓取模式')).toHaveTextContent('第二默认值')
    await browser.type(screen.getByRole('textbox', { name: '来源名称' }), '切换后的来源')
    await browser.click(screen.getByRole('button', { name: '创建来源' }))

    await waitFor(() => expect(createSource).toHaveBeenCalledWith(expect.objectContaining({
      type: 'second_registry',
      config: expect.objectContaining({ mode: 'second' }),
    })))
  })

  it('applies the existing provider defaults in the live AI form', async () => {
    const browser = userEvent.setup()
    const configAction = vi.fn().mockResolvedValue({ config: { ai: {} } })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-ai', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: { provider: 'gemini' }, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [{ id: 'deepseek-key', name: 'DeepSeek Key', kind: 'ai', provider: 'deepseek', env_name: 'DEEPSEEK_API_KEY', is_set: true, used_by: [] }] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      configAction,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '助手与 AI' })
    await browser.click(screen.getByRole('button', { name: /Provider/ }))
    await browser.click(await screen.findByRole('option', { name: 'DeepSeek' }))
    expect(screen.getByRole('textbox', { name: '模型' })).toHaveValue('deepseek-v4-flash')
    expect(screen.getByLabelText('AI Key')).toHaveTextContent('DeepSeek Key')
    await browser.click(screen.getByRole('button', { name: '保存 AI 设置' }))
    expect(configAction).toHaveBeenCalledWith('set_ai', expect.objectContaining({ provider: 'deepseek', model: 'deepseek-v4-flash', api_key_env: 'DEEPSEEK_API_KEY' }))
  })

  it.each(['owner', 'admin'] as const)('lets a live %s change non-owner member roles while protecting owners', async (actorRole) => {
    const browser = userEvent.setup()
    const workspaceOwner = { id: 'workspace-owner', username: 'workspace-owner', display_name: 'Workspace Owner', role: 'owner' as const, enabled: true }
    let editableMember = { id: 'editable-member', username: 'editable', display_name: 'Editable Member', role: 'member' as const, enabled: true }
    const users = vi.fn().mockImplementation(async () => ({ users: [workspaceOwner, editableMember] }))
    const updateUser = vi.fn().mockImplementation(async (_id: string, patch: Record<string, unknown>) => {
      editableMember = { ...editableMember, role: String(patch.role) as 'member' }
      return editableMember
    })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: `actor-${actorRole}`, username: actorRole, role: actorRole, enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }), secrets: vi.fn().mockResolvedValue({ secrets: [] }), users, updateUser,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '成员' })
    expect(screen.queryByRole('button', { name: /角色 workspace-owner/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '切换 workspace-owner 状态' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: /角色 editable/ }))
    await browser.click(await screen.findByRole('option', { name: 'viewer' }))
    expect(updateUser).toHaveBeenCalledWith('editable-member', { role: 'viewer' })
    expect(screen.getByRole('button', { name: '切换 editable 状态' })).toBeEnabled()
  })

  it.each(['member', 'viewer'] as const)('does not expose live member administration controls to a %s', async (actorRole) => {
    const users = vi.fn()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: `actor-${actorRole}`, username: actorRole, role: actorRole, enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }), users,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByText('工作区设置只读')
    expect(screen.queryByRole('heading', { name: '成员' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^角色 / })).not.toBeInTheDocument()
    expect(users).not.toHaveBeenCalled()
  })

  it('shows a neutral Agent connection state while delegation loading is unresolved', async () => {
    const user = userEvent.setup()
    const api = liveApi({ agentDelegations: vi.fn().mockImplementation(() => new Promise(() => undefined)) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await user.click(await screen.findByRole('button', { name: '展开 Agent 面板' }))
    expect(await screen.findByRole('status', { name: '正在检查 Agent 连接' })).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryByText('检查中')).not.toBeInTheDocument()
    expect(screen.queryByText('未配置')).not.toBeInTheDocument()
  })

  it('opens the narrow-screen Agent surface as a real modal dialog', async () => {
    const user = userEvent.setup()
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const toggle = await screen.findByRole('button', { name: '展开 Agent 面板' })
    await user.click(toggle)
    expect(await screen.findByRole('dialog', { name: 'OpenClaw 上下文' })).toBeInTheDocument()
    expect(screen.getAllByText('对话未启用')).toHaveLength(1)
  })

  it('temporarily inserts a deep-linked item returned by feedItem', async () => {
    const feedItem = vi.fn().mockResolvedValue({ id: 'deep', title: '深链条目', url: 'https://example.com/deep', published_at: '2026-07-17T01:00:00Z' })
    const api = liveApi({ feedItem } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=deep']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '深链条目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 深链条目' })).toHaveAttribute('aria-expanded', 'true')
    expect(feedItem).toHaveBeenCalledWith('deep', expect.any(AbortSignal))
  })

  it('waits for the source snapshot before fetching detail for an initial deep link', async () => {
    const snapshot = deferred<{ schema_version: number; items: FeedItem[] }>()
    const feedItem = vi.fn().mockResolvedValue(detailedItem('live-1'))
    const api = liveApi({ latestFeed: vi.fn().mockReturnValue(snapshot.promise), feedItem } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=live-1']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await waitFor(() => expect(api.latestFeed).toHaveBeenCalled())
    expect(feedItem).not.toHaveBeenCalled()
    await act(async () => snapshot.resolve({ schema_version: 2, items: [{ id: 'live-1', title: '真实 API 条目', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z' }] }))
    expect(await screen.findByRole('article', { name: '详情标题 live-1' })).toBeInTheDocument()
    expect(feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
  })

  it('fetches and merges detail when an item already in the snapshot is expanded', async () => {
    const user = userEvent.setup()
    const snapshotItem = detailedItem('live-1')
    if (snapshotItem.presentation) {
      snapshotItem.presentation.content.title = '真实 API 条目'
      snapshotItem.presentation.content.excerpt = '列表内容片段'
      snapshotItem.presentation.content.excerpt_truncated = true
      delete snapshotItem.presentation.content.body_text
    }
    const feedItem = vi.fn().mockResolvedValue(detailedItem('live-1'))
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [snapshotItem] }),
      feedItem,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await user.click(await screen.findByRole('button', { name: '展开 真实 API 条目' }))
    expect(await screen.findByRole('article', { name: '详情标题 live-1' })).toBeInTheDocument()
    expect(await screen.findByText('完整详情正文')).toBeInTheDocument()
    expect(feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
  })

  it('keeps the snapshot card and item parameter when its detail request fails', async () => {
    const feedItem = vi.fn().mockRejectedValue(new ApiError(503, { code: 'detail_failed', message: '详情失败' }))
    const api = liveApi({ feedItem } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '真实 API 条目' })).toBeInTheDocument()
    expect(await screen.findByText('暂时无法读取更多内容；当前卡片仍可继续使用。')).toBeInTheDocument()
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
  })

  it('pins a successfully fetched deep link despite persisted filters and dismissed state', async () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-live', JSON.stringify({ unreadFirst: true, source: 'other-source', channel: '其他频道', topic: '其他主题', minScore: 10 }))
    const deep = detailedItem('filtered-deep', { user_state: { is_read: true, is_saved: false, is_later: false, dismissed: true } })
    const api = liveApi({ feedItem: vi.fn().mockResolvedValue(deep) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=filtered-deep']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByRole('article', { name: '详情标题 filtered-deep' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '收起 详情标题 filtered-deep' })).toHaveAttribute('aria-expanded', 'true')
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('keeps a filter-pinned detail between newer and older matching rows', async () => {
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
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=between']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      await screen.findByRole('article', { name: '详情标题 between' })
      expect(screen.getAllByRole('article').map((article) => article.getAttribute('aria-label'))).toEqual([
        '较新条目',
        '详情标题 between',
        '较旧条目',
      ])
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('keeps unread-first ordering when a selected detail bypasses exclusionary filters', async () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-live', JSON.stringify({ unreadFirst: true, source: 'matching-source', channel: '', topic: '' }))
    const sourceItem = (id: string, title: string, published_at: string, is_read: boolean): FeedItem => ({
      id,
      title,
      url: `https://example.com/${id}`,
      source_id: 'matching-source',
      published_at,
      user_state: { is_read, is_saved: false, is_later: false, dismissed: false },
    })
    const detail = detailedItem('between-read', {
      published_at: '2026-07-17T02:00:00Z',
      user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false },
    })
    if (detail.presentation) detail.presentation.timing.published_at = '2026-07-17T02:00:00Z'
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({
        schema_version: 2,
        items: [
          sourceItem('older-read', '较旧已读条目', '2026-07-17T01:00:00Z', true),
          sourceItem('newer-unread', '较新未读条目', '2026-07-17T03:00:00Z', false),
        ],
      }),
      feedItem: vi.fn().mockResolvedValue(detail),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=between-read']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      await screen.findByRole('article', { name: '详情标题 between-read' })
      expect(screen.getAllByRole('article').map((article) => article.getAttribute('aria-label'))).toEqual([
        '较新未读条目',
        '详情标题 between-read',
        '较旧已读条目',
      ])
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('keeps an in-list deep link when its detail endpoint returns 404', async () => {
    const latest = deferred<{ schema_version: number; items: FeedItem[] }>()
    const api = liveApi({
      latestFeed: vi.fn().mockReturnValue(latest.promise),
      feedItem: vi.fn().mockRejectedValue(new ApiError(404, { code: 'not_found', message: '不存在' })),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await waitFor(() => expect(api.latestFeed).toHaveBeenCalled())
    expect(api.feedItem).not.toHaveBeenCalled()
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(screen.queryByText(/这条信息已不可用/)).not.toBeInTheDocument()
    await act(async () => latest.resolve({
      schema_version: 2,
      items: [{ id: 'live-1', title: '快照回退条目', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z' }],
    }))
    expect(await screen.findByRole('article', { name: '快照回退条目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 快照回退条目' })).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('暂时无法读取更多内容；当前卡片仍可继续使用。')).toBeInTheDocument()
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(api.feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
  })

  it('does not fetch a cached-missing selection before its active source refetch settles', async () => {
    const latest = deferred<{ schema_version: number; items: FeedItem[] }>()
    const api = liveApi({
      latestFeed: vi.fn().mockReturnValue(latest.promise),
      feedItem: vi.fn().mockResolvedValue(detailedItem('live-1')),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(queryKeys.feed('user-live', { hideDismissed: false, unreadFirst: false }), {
      schema_version: 2,
      items: [{ id: 'cached-other', title: '缓存旧条目', url: 'https://example.com/cached-other', published_at: '2026-07-17T01:00:00Z' }],
    })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await waitFor(() => {
      expect(api.latestFeed).toHaveBeenCalled()
    })
    expect(api.feedItem).not.toHaveBeenCalled()
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(screen.queryByText(/这条信息已不可用/)).not.toBeInTheDocument()

    await act(async () => latest.resolve({
      schema_version: 2,
      items: [{ id: 'live-1', title: '后台刷新目标', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z' }],
    }))
    expect(await screen.findByRole('article', { name: '详情标题 live-1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 详情标题 live-1' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(api.feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
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
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed?item=missing']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByText(/这条信息已不可用/)).toBeInTheDocument()
      await waitFor(() => expect(screen.getAllByRole('article').length).toBeGreaterThan(0))
      expect(screen.getByLabelText('当前位置')).toHaveTextContent('/feed')
      expect(screen.getByLabelText('当前位置')).not.toHaveTextContent('item=')
      await waitFor(() => expect(scrollTo.mock.calls.some(([options]) => (options as ScrollToOptions).behavior === 'auto')).toBe(true))
    } finally {
      if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: originalScrollTo })
      else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
    }
  })

  it('renders the saved production route from savedFeed without falling through to latestFeed', async () => {
    const savedItem: FeedItem = {
      id: 'saved-route-item',
      title: '收藏路由条目',
      url: 'https://example.com/saved-route-item',
      published_at: '2026-07-17T02:00:00Z',
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    }
    const savedFeed = vi.fn().mockResolvedValue({ items: [savedItem] })
    const latestFeed = vi.fn().mockResolvedValue({ schema_version: 2, items: [] })
    const api = liveApi({ savedFeed, latestFeed } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/saved']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '收藏' })).toBeInTheDocument()
    expect(await screen.findByRole('article', { name: '收藏路由条目' })).toBeInTheDocument()
    expect(savedFeed).toHaveBeenCalledWith(200, 0, expect.any(AbortSignal))
    expect(latestFeed).not.toHaveBeenCalled()
  })

  it('renders the history production route from historyFeed without falling through to latestFeed', async () => {
    const historyItem: FeedItem = {
      id: 'history-route-item',
      title: '历史路由条目',
      url: 'https://example.com/history-route-item',
      published_at: '2026-07-17T01:00:00Z',
      user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false },
    }
    const historyFeed = vi.fn().mockResolvedValue({ items: [historyItem] })
    const latestFeed = vi.fn().mockResolvedValue({ schema_version: 2, items: [] })
    const api = liveApi({ historyFeed, latestFeed } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/history']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '历史' })).toBeInTheDocument()
    expect(await screen.findByRole('article', { name: '历史路由条目' })).toBeInTheDocument()
    expect(historyFeed).toHaveBeenCalledWith(expect.any(AbortSignal))
    expect(latestFeed).not.toHaveBeenCalled()
  })

  it('replaces the legacy later route with saved, preserving item and dropping obsolete mode', async () => {
    const savedItem: FeedItem = {
      id: 'live-1',
      title: '稍后读迁移条目',
      url: 'https://example.com/live-1',
      published_at: '2026-07-17T02:00:00Z',
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    }
    const savedFeed = vi.fn().mockResolvedValue({ items: [savedItem] })
    const feedItem = vi.fn().mockResolvedValue(savedItem)
    const api = liveApi({
      savedFeed,
      feedItem,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/later?mode=featured&item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '收藏' })).toBeInTheDocument()
    expect(await screen.findByRole('article', { name: '稍后读迁移条目' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/saved?item=live-1'))
    expect(savedFeed).toHaveBeenCalledWith(200, 0, expect.any(AbortSignal))
    expect(feedItem).toHaveBeenCalledWith('live-1', expect.any(AbortSignal))
  })

  it('does not remount the authenticated workbench when inline expansion changes search params', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 40 }, (_, index) => ({
      id: `anchor-${index}`,
      title: `锚点条目 ${index}`,
      url: `https://example.com/anchor-${index}`,
      published_at: new Date(Date.UTC(2026, 6, 17, 0, index)).toISOString(),
      media_urls: [`/api/media/anchor-${index}`],
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
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const save = await screen.findByRole('button', { name: '收藏 真实 API 条目' })
    await user.click(save)
    await waitFor(() => expect(screen.getByRole('button', { name: '收藏 真实 API 条目' })).toBeInTheDocument())
    expect(await screen.findByRole('alert')).toHaveTextContent('收藏失败，状态已恢复。')
    expect(document.querySelector('[class*="Mui"]')).not.toBeInTheDocument()
  })

  it('shows a recovery surface when a routed child crashes', async () => {
    const appModule = await import('./App')
    const Boundary = Reflect.get(appModule, 'AppErrorBoundary') as ComponentType<{ children: ReactNode; surface?: 'app' | 'page' }> | undefined
    expect(Boundary).toBeDefined()
    if (!Boundary) return

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function CrashingChild(): ReactNode {
      throw new Error('render failed')
    }
    try {
      const globalBoundary = render(<Boundary><CrashingChild /></Boundary>)
      expect(screen.getByRole('alert')).toHaveTextContent('页面加载失败')
      expect(screen.getByRole('link', { name: '返回信息流' })).toHaveAttribute('href', '/feed')
      expect(screen.getByRole('alert').tagName).toBe('MAIN')
      globalBoundary.unmount()

      render(<main><Boundary surface="page"><CrashingChild /></Boundary></main>)
      expect(screen.getByRole('alert').tagName).toBe('SECTION')
    } finally {
      consoleError.mockRestore()
    }
  })
})
