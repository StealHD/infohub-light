import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentType, ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { queryKeys } from '../api/queryKeys'
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
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((next, fail) => {
    resolve = next
    reject = fail
  })
  return { promise, resolve, reject }
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

  it('keeps live administration routes in the HeroUI shell without an Agent panel', async () => {
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '订阅与来源' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(screen.queryByRole('complementary', { name: 'OpenClaw 上下文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Agent 面板/ })).not.toBeInTheDocument()
    expect(document.querySelector('[data-ui-system="heroui"]')).toBeInTheDocument()
    expect(document.querySelector('[class*="Mui"]')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'AI' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '工作/项目' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '收起 AI' }))
    expect(screen.queryByRole('button', { name: '立即获取 覆盖频道来源' })).not.toBeInTheDocument()
    await userEvent.type(screen.getByRole('searchbox', { name: '搜索来源' }), '覆盖频道')
    expect(screen.getByRole('button', { name: '立即获取 覆盖频道来源' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '立即获取 覆盖频道来源' }))
    expect(api.feedSchedule).toHaveBeenCalled()
    expect(api.createSourceFetch).toHaveBeenCalledWith(source.id, subscription.id)
  }, 10_000)

  it('protects and explicitly clears a live one-time Agent token', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      agentDelegations: vi.fn().mockResolvedValue({ enabled: true, mcp_url: '/mcp', token_ttl_days: 90, max_active: 5, connections: [] }),
      createAgentDelegation: vi.fn().mockResolvedValue({
        connection: { id: 'agent-new', name: 'Desk Mac', client_type: 'openclaw', scopes: ['inteliscope:read'], token_prefix: 'ih_new', created_at: '2026-07-17T00:00:00Z', expires_at: '2026-10-17T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' },
        token: 'ih_mcp_one_time_live',
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live/agents']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const createDialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.type(within(createDialog).getByRole('textbox', { name: '连接名称' }), 'Desk Mac')
    await browser.click(within(createDialog).getByRole('button', { name: '生成一次性令牌' }))
    const tokenDialog = await screen.findByRole('dialog', { name: '保存一次性令牌' })
    expect(within(tokenDialog).getByText('ih_mcp_one_time_live')).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '保存一次性令牌' })).toBeInTheDocument()
    await browser.click(screen.getByTestId('one-time-token-backdrop'))
    expect(screen.getByRole('dialog', { name: '保存一次性令牌' })).toBeInTheDocument()
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '立即获取 阻塞来源' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('后台获取服务当前不可用')
    expect(createSourceFetch).not.toHaveBeenCalled()
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '助手与 AI' })).toBeInTheDocument()
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

  it('exposes a DEV-only HeroUI login without changing login errors', async () => {
    const browser = userEvent.setup()
    const api = {
      authStatus: vi.fn().mockResolvedValue({ authenticated: false, user: null }),
      login: vi.fn().mockRejectedValue(new ApiError(401, { code: 'invalid_credentials', message: '账号或密码错误' })),
    } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live/login']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '登录私人信息雷达' })).toBeInTheDocument()
    expect(document.querySelector('[data-ui-system="heroui"]')).toBeInTheDocument()
    await browser.type(screen.getByLabelText('用户名'), 'owner')
    await browser.type(screen.getByLabelText('密码'), 'wrong-secret')
    await browser.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码错误')
    expect(screen.getByLabelText('密码')).toHaveValue('')
    expect(api.login).toHaveBeenCalledWith('owner', 'wrong-secret')
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live/settings']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '助手与 AI' })
    await browser.click(screen.getByRole('button', { name: /Provider/ }))
    await browser.click(await screen.findByRole('option', { name: 'DeepSeek' }))
    expect(screen.getByRole('textbox', { name: '模型' })).toHaveValue('deepseek-v4-flash')
    expect(screen.getByLabelText('AI Key')).toHaveTextContent('DeepSeek Key')
    await browser.click(screen.getByRole('button', { name: '保存 AI 设置' }))
    expect(configAction).toHaveBeenCalledWith('set_ai', expect.objectContaining({ provider: 'deepseek', model: 'deepseek-v4-flash', api_key_env: 'DEEPSEEK_API_KEY' }))
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
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=between-read']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      await screen.findByRole('article', { name: '详情标题 between-read' })
      expect(screen.getAllByRole('article').map((article) => article.getAttribute('aria-label'))).toEqual([
        '较新未读条目',
        '较旧已读条目',
        '详情标题 between-read',
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

  it('keeps a cached-missing selection while its active source refetch can still return the target', async () => {
    const latest = deferred<{ schema_version: number; items: FeedItem[] }>()
    const detail = deferred<FeedItem>()
    const api = liveApi({
      latestFeed: vi.fn().mockReturnValue(latest.promise),
      feedItem: vi.fn().mockReturnValue(detail.promise),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(queryKeys.feed('user-live', { hideDismissed: false, unreadFirst: false }), {
      schema_version: 2,
      items: [{ id: 'cached-other', title: '缓存旧条目', url: 'https://example.com/cached-other', published_at: '2026-07-17T01:00:00Z' }],
    })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await waitFor(() => {
      expect(api.latestFeed).toHaveBeenCalled()
      expect(api.feedItem).toHaveBeenCalled()
    })
    await act(async () => detail.reject(new ApiError(404, { code: 'not_found', message: '不存在' })))
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('?item=live-1')
    expect(screen.queryByText(/这条信息已不可用/)).not.toBeInTheDocument()

    await act(async () => latest.resolve({
      schema_version: 2,
      items: [{ id: 'live-1', title: '后台刷新目标', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z' }],
    }))
    expect(await screen.findByRole('article', { name: '后台刷新目标' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 后台刷新目标' })).toHaveAttribute('aria-expanded', 'true')
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
