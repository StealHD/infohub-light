import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentType, ReactNode } from 'react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { queryKeys } from '../api/queryKeys'
import type { ServiceApi } from '../api/service'
import type { FeedItem, Job, WebhookProviderOption } from '../api/types'
import { actionToast, DesignSystemProvider } from '../design-system'
import { validateRegistryFields } from '../features/admin-heroui/sourceFormValidation'
import { AppRoutes } from './App'

const actorSupportProfiles = [
  { id: 'x/profile/items', route_key: 'x/profile', platform: 'x' as const, target_type: 'profile' as const, capability: 'items' as const, mode: 'primary' as const, label: 'X Profile' },
  { id: 'youtube/channel/items', route_key: 'youtube/channel/items', platform: 'youtube' as const, target_type: 'channel' as const, capability: 'items' as const, mode: 'fallback' as const, label: 'YouTube Channel' },
  { id: 'instagram/profile/items', route_key: 'instagram/profile/items', platform: 'instagram' as const, target_type: 'profile' as const, capability: 'items' as const, mode: 'primary' as const, label: 'Instagram Profile' },
]

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="当前位置">{location.pathname}{location.search}</output>
}

function NavigationProbe() {
  const navigate = useNavigate()
  return <div>
    <button type="button" onClick={() => navigate('/feed')}>测试前往信息流</button>
    <button type="button" onClick={() => navigate('/saved')}>测试前往收藏</button>
    <button type="button" onClick={() => navigate('/history')}>测试前往历史</button>
  </div>
}

function webhookProviderOptions(): WebhookProviderOption[] {
  return [
    { provider: 'generic_event', label: '通用事件 JSON', description: 'event/data', url_hint: 'https://example.com/webhook', signing: 'none', verification_mode: 'http_status' },
    { provider: 'generic_text', label: '通用文本 JSON', description: 'text', url_hint: 'https://example.com/webhook', signing: 'none', verification_mode: 'http_status' },
    { provider: 'feishu_lark_v2', label: '飞书 / Lark V2', description: '平台文本', url_hint: 'https://open.feishu.cn/open-apis/bot/v2/hook/…', signing: 'optional', verification_mode: 'provider_response' },
    { provider: 'wecom', label: '企业微信群机器人', description: '平台文本', url_hint: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…', signing: 'none', verification_mode: 'provider_response' },
    { provider: 'dingtalk', label: '钉钉自定义机器人', description: '平台文本', url_hint: 'https://oapi.dingtalk.com/robot/send?access_token=…', signing: 'optional', verification_mode: 'provider_response' },
    { provider: 'slack', label: 'Slack / GovSlack', description: '平台文本', url_hint: 'https://hooks.slack.com/services/…/…/…', signing: 'none', verification_mode: 'provider_response' },
    { provider: 'discord', label: 'Discord Incoming Webhook', description: '平台文本', url_hint: 'https://discord.com/api/webhooks/…/…', signing: 'none', verification_mode: 'provider_response' },
  ]
}

function notificationChannelStates({
  selected = 'webhook',
  emailConfigured = false,
  emailAvailable = true,
  webhookConfigured = false,
  telegramConfigured = false,
  telegramAvailable = true,
}: {
  selected?: 'email' | 'webhook' | 'telegram'
  emailConfigured?: boolean
  emailAvailable?: boolean
  webhookConfigured?: boolean
  telegramConfigured?: boolean
  telegramAvailable?: boolean
} = {}) {
  const base = {
    generation: 1,
    enabled_at: null,
    last_test_status: null,
    last_tested_at: null,
    last_test_error_code: null,
  }
  return {
    email: {
      ...base,
      enabled: selected === 'email',
      configured: emailConfigured,
      available: emailAvailable,
    },
    webhook: {
      ...base,
      enabled: selected === 'webhook',
      configured: webhookConfigured,
      available: true,
      provider: 'generic_event' as const,
      provider_explicit: true,
      signing_secret_configured: false,
      verification_mode: 'http_status' as const,
    },
    telegram: {
      ...base,
      enabled: selected === 'telegram',
      configured: telegramConfigured,
      available: telegramAvailable,
    },
  }
}

function emptyTelegramTransport() {
  return {
    schema_version: 1 as const,
    configured: false,
    enabled: false,
    token_configured: false,
    generation: 0,
    last_test_status: null,
    last_test_generation: null,
    last_tested_at: null,
    last_test_error_code: null,
    can_enable: false,
    ready: false,
    updated_at: null,
  }
}

function liveApi(overrides: Partial<ServiceApi> = {}): ServiceApi {
  return {
    authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'user-live', username: 'live', role: 'member', enabled: true } }),
    latestFeed: vi.fn().mockResolvedValue({
      schema_version: 2,
      items: [{ id: 'live-1', title: '真实 API 条目', url: 'https://example.com/live-1', published_at: '2026-07-17T02:00:00Z', user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false } }],
    }),
    feedEndMessages: vi.fn().mockResolvedValue({
      schema_version: 1,
      source: 'builtin',
      status: 'disabled',
      generation: 0,
      generated_at: null,
      last_attempt_at: null,
      next_refresh_at: null,
      retry_at: null,
      last_error_code: null,
      scenes: {
        empty: ['这里暂时很安静。'],
        first_end: ['这一轮内容先到这里。'],
        repeat_end: ['又到末尾了。'],
      },
    }),
    refreshFeedEndMessages: vi.fn(),
    agentDelegations: vi.fn().mockResolvedValue({ enabled: true, subscription_writes_enabled: false, connections: [], mcp_url: '/mcp', openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5 }),
    feedJobs: vi.fn().mockResolvedValue({ jobs: [] }),
    jobs: vi.fn().mockResolvedValue({ jobs: [] }),
    feedSchedule: vi.fn().mockResolvedValue({ enabled: true, interval_minutes: 60, worker_status: 'ready' }),
    notificationSettings: vi.fn().mockResolvedValue({
      schema_version: 4,
      enabled: false,
      target_ids: [],
      selected_targets: [],
      channels: ['email'],
      channel: 'email',
      channel_states: notificationChannelStates({
        selected: 'email',
        emailAvailable: false,
        telegramAvailable: false,
      }),
      email_configured: false,
      email_transport_ready: false,
      webhook_configured: false,
      webhook_provider: 'generic_event',
      webhook_provider_explicit: true,
      webhook_signing_secret_configured: false,
      webhook_verification_mode: 'http_status',
      webhook_provider_options: webhookProviderOptions(),
      telegram_configured: false,
      telegram_transport_ready: false,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
      updated_at: '2026-07-24T00:00:00Z',
    }),
    notificationTargets: vi.fn().mockResolvedValue({
      schema_version: 1,
      targets: [],
      webhook_provider_options: webhookProviderOptions(),
    }),
    notificationServices: vi.fn().mockResolvedValue({
      schema_version: 1,
      services: [],
      channel_credentials: {
        email: {
          configured: false,
          ready: false,
          generation: 0,
          provider: null,
          sender_name: 'Inteliscope',
          region: null,
          sender_email_configured: false,
          smtp_username_configured: false,
          providers: [],
        },
        telegram: { configured: false, ready: false, generation: 0 },
        webhook: { configured: true, ready: true, generation: 0 },
      },
      webhook_provider_options: webhookProviderOptions(),
      can_manage: true,
    }),
    updateItemState: vi.fn(),
    ignoredFeed: vi.fn().mockResolvedValue({ items: [], pagination: { limit: 200, offset: 0, count: 0, total: 0 } }),
    subscribe: vi.fn().mockResolvedValue({ subscription: { reused_item_count: 0 } }),
    apifyKeyPool: vi.fn().mockResolvedValue({ enabled: false, generation: 0, status: 'disabled', active_secret_id: null, members: [] }),
    apifyActorXProfileRoute: vi.fn().mockResolvedValue({
      schema_version: 1,
      route: 'x/profile',
      generation: 1,
      status: 'ready',
      active_candidate_id: 'scrape-badger',
      last_switch_reason: null,
      last_switch_at: null,
      retry_at: null,
      blocked_reason: null,
      quota: {
        currency: 'USD',
        total_remaining_usd: 5,
        x_allocatable_usd: 4,
        spend_24h_usd: 0,
        estimated_days_remaining: null,
        as_of: null,
      },
      limits: { per_run_usd: 0.02, per_job_usd: 0.06, failed_spend_6h_usd: 0.08 },
      candidates: [],
    }),
    apifyActorRoutes: vi.fn().mockResolvedValue({
      schema_version: 1,
      generation: 1,
      support_profiles: actorSupportProfiles,
      routes: [],
    }),
    sourceCapabilities: vi.fn().mockResolvedValue({
      schema_version: 1,
      generation: 1,
      support_profiles: actorSupportProfiles,
      capabilities: [],
    }),
    apifyActorAlertSettings: vi.fn().mockResolvedValue({
      schema_version: 4,
      enabled: false,
      target_ids: [],
      selected_targets: [],
      channels: ['webhook'],
      channel: 'webhook',
      channel_states: notificationChannelStates({
        webhookConfigured: false,
        emailAvailable: false,
        telegramAvailable: false,
      }),
      events: ['actor_switched', 'route_exhausted', 'quota_low', 'budget_blocked', 'start_outcome_unknown', 'recovered'],
      email_configured: false,
      email_transport_ready: false,
      webhook_configured: false,
      webhook_provider: 'generic_event',
      webhook_provider_explicit: true,
      webhook_signing_secret_configured: false,
      webhook_verification_mode: 'http_status',
      webhook_provider_options: webhookProviderOptions(),
      telegram_configured: false,
      telegram_transport_ready: false,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
      last_alert_status: null,
      last_alerted_at: null,
      last_alert_error_code: null,
      updated_at: null,
    }),
    apifyActorAlertIncidents: vi.fn().mockResolvedValue({ schema_version: 3, incidents: [] }),
    notificationTelegramTransport: vi.fn().mockResolvedValue(emptyTelegramTransport()),
    storageSummary: vi.fn().mockResolvedValue({
      schema_version: 1,
      policy: { feed_snapshot_days: 30, feed_snapshot_per_user: 20, source_snapshot_days: 7, completed_job_days: 14, analysis_cache_days: 30, usage_event_days: 90, archive_after_days: 90, automatic_permanent_delete: false },
      bytes: { database: 1024, media: 0, archives: 0 },
      counts: { content_total: 0, content_online: 0, content_archived: 0, feed_snapshots: 0, source_snapshots: 0, media_assets: 0, archive_batches: 0 },
      readiness: { feed_storage_v3: true, content_timeline_v11: true, ready: true },
      last_cleanup_at: null,
    }),
    storageArchives: vi.fn().mockResolvedValue({ schema_version: 1, archives: [] }),
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

function basicFeedItem(id: string, title: string): FeedItem {
  return {
    id,
    title,
    url: `https://example.com/${id}`,
    published_at: '2026-07-17T02:00:00Z',
    user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
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
    const itemCount = await screen.findByText('近7天 · 1 条')
    const orderControl = screen.getByRole('button', { name: '排序顺序：最新优先' })
    const reloadControl = screen.getByRole('button', { name: '重新载入信息流数据' })
    const updateControl = screen.getByRole('button', { name: '获取新内容' })
    const filterControl = screen.getByRole('button', { name: '筛选信息流' })
    expect(itemCount).toHaveClass('type-control')
    expect(itemCount).toHaveClass('whitespace-nowrap')
    expect(itemCount.closest('[data-loading-reveal="feed-count"]')).toHaveClass('min-w-16')
    expect(itemCount.closest('[data-loading-reveal="feed-count"]')).not.toHaveClass('w-16')
    expect(orderControl).toHaveClass('size-8')
    expect(reloadControl).toHaveClass('size-8')
    expect(updateControl).toHaveClass('size-8')
    expect(filterControl).toHaveClass('size-8')
    expect(screen.getByRole('searchbox', { name: '搜索全部内容' })).toBeInTheDocument()
    expect(screen.getByTestId('feed-view-bar')).toBeInTheDocument()
    expect(screen.queryByText('旧内容在上，最新内容在下 · 1 条')).not.toBeInTheDocument()
    expect(screen.queryByText('全部', { exact: true })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('article', { name: '真实 API 条目' })).toBeInTheDocument())
    expect(api.latestFeed).toHaveBeenCalled()
    expect(api.agentDelegations).toHaveBeenCalled()
    expect(screen.queryByText('稍后读')).not.toBeInTheDocument()
  })

  it('replaces the deterministic empty card with one lightweight empty message', async () => {
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [] }),
      feedEndMessages: vi.fn().mockResolvedValue({
        schema_version: 1,
        source: 'ai',
        status: 'ready',
        generation: 2,
        generated_at: '2026-07-29T00:00:00Z',
        last_attempt_at: '2026-07-29T00:00:00Z',
        next_refresh_at: '2026-08-05T00:00:00Z',
        retry_at: null,
        last_error_code: null,
        scenes: {
          empty: ['空白也可以很从容。'],
          first_end: ['这一轮先读到这里。'],
          repeat_end: ['再次走到列表末尾。'],
        },
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const emptyMessage = await screen.findByTestId('feed-empty-message')
    expect(emptyMessage).toHaveTextContent('信息流为空·空白也可以很从容。')
    expect(within(emptyMessage).getByText('空白也可以很从容。')).toHaveClass('truncate')
    expect(emptyMessage).not.toHaveClass('card', 'rounded-xl', 'border', 'bg-surface-secondary')
    expect(screen.queryByText('信息流还是空的')).not.toBeInTheDocument()
    expect(screen.queryByText('先订阅来源，再获取一次新内容。')).not.toBeInTheDocument()
  })

  it('does not show empty copy while a single-character search waits for explicit submission', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByTestId('feed-empty-message')
    await browser.type(screen.getByRole('searchbox', { name: '搜索全部内容' }), '单')

    expect(await screen.findByTestId('feed-search-submit-message')).toHaveTextContent('输入单个字符后按回车搜索')
    await waitFor(() => expect(screen.queryByTestId('feed-empty-message')).not.toBeInTheDocument())
  })

  it('isolates content search by route while keeping an empty Feed search visible', async () => {
    const browser = userEvent.setup()
    const savedItem = {
      ...basicFeedItem('saved-search-item', '收藏里的目标'),
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    }
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({
        schema_version: 2,
        items: [basicFeedItem('feed-unrelated-item', '信息流独立内容')],
      }),
      savedFeed: vi.fn().mockResolvedValue({ items: [savedItem] }),
      historyFeed: vi.fn().mockResolvedValue({ items: [basicFeedItem('history-item', '历史独立内容')] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/saved']}><DesignSystemProvider><AppRoutes api={api} /><NavigationProbe /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '收藏里的目标' })).toBeInTheDocument()
    const savedSearch = screen.getByRole('searchbox', { name: '搜索当前列表' })
    await browser.type(savedSearch, '只存在于收藏的关键词')
    expect(screen.queryByRole('article', { name: '收藏里的目标' })).not.toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '测试前往信息流' }))
    expect(await screen.findByRole('article', { name: '信息流独立内容' })).toBeInTheDocument()
    expect(screen.queryByText('搜索：只存在于收藏的关键词')).not.toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: '搜索全部内容' })).toHaveValue('')

    await browser.click(screen.getByRole('button', { name: '测试前往收藏' }))
    expect(await screen.findByRole('searchbox', { name: '搜索当前列表' })).toHaveValue('只存在于收藏的关键词')
  })

  it('reloads Feed data without creating a background update job', async () => {
    const browser = userEvent.setup()
    const nextFeed = deferred<{ schema_version: number; items: FeedItem[] }>()
    const latestFeed = vi.fn()
      .mockResolvedValueOnce({
        schema_version: 2,
        items: [basicFeedItem('before-reload', '刷新前条目')],
      })
      .mockReturnValueOnce(nextFeed.promise)
    const createFeedRefresh = vi.fn()
    const api = liveApi({ latestFeed, createFeedRefresh } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '刷新前条目' })).toBeInTheDocument()
    const reload = screen.getByRole('button', { name: '重新载入信息流数据' })
    expect(reload).not.toHaveAttribute('aria-busy')
    await browser.click(reload)

    expect(screen.getByRole('button', { name: '重新载入信息流数据' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '重新载入信息流数据' })).toHaveAttribute('aria-busy', 'true')
    await browser.click(screen.getByRole('button', { name: '重新载入信息流数据' }))
    expect(latestFeed).toHaveBeenCalledTimes(2)
    expect(createFeedRefresh).not.toHaveBeenCalled()

    act(() => nextFeed.resolve({
      schema_version: 2,
      items: [basicFeedItem('after-reload', '刷新后条目')],
    }))
    expect(await screen.findByRole('article', { name: '刷新后条目' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '重新载入信息流数据' })).toBeEnabled()
      expect(screen.getByRole('button', { name: '重新载入信息流数据' })).not.toHaveAttribute('aria-busy')
    })
  })

  it('keeps the last trusted Feed visible when a manual data reload fails', async () => {
    const browser = userEvent.setup()
    const latestFeed = vi.fn()
      .mockResolvedValueOnce({
        schema_version: 2,
        items: [basicFeedItem('trusted-feed', '可信旧条目')],
      })
      .mockRejectedValueOnce(new ApiError(503, { code: 'temporarily_unavailable', message: '最新信息流暂时不可用' }))
    const api = liveApi({ latestFeed } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '可信旧条目' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '重新载入信息流数据' }))

    expect(await screen.findByText('信息流刷新失败')).toBeInTheDocument()
    expect(screen.getByText('最新信息流暂时不可用')).toBeInTheDocument()
    expect(screen.getByRole('article', { name: '可信旧条目' })).toBeInTheDocument()
    expect(screen.queryByText('信息流加载失败')).not.toBeInTheDocument()
  })

  it('allows a viewer to reload Feed data while keeping background updates disabled', async () => {
    const latestFeed = vi.fn().mockResolvedValue({
      schema_version: 2,
      items: [basicFeedItem('viewer-feed', '只读信息流条目')],
    })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'viewer-user', username: 'viewer', role: 'viewer', enabled: true } }),
      latestFeed,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '只读信息流条目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新载入信息流数据' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '获取新内容' })).toBeDisabled()
  })

  it('clears queued Toasts before a replacement account can render', async () => {
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '信息流' })
    act(() => {
      actionToast.success('旧账户操作完成')
    })
    expect(await screen.findByText('旧账户操作完成')).toBeInTheDocument()

    act(() => {
      queryClient.setQueryData(queryKeys.auth, {
        authenticated: true,
        user: { id: 'replacement-user', username: 'replacement', role: 'member', enabled: true },
      })
    })

    await waitFor(() => expect(screen.queryByText('旧账户操作完成')).not.toBeInTheDocument())
  })

  it('releases the static boot shell only after the authenticated shell commits', async () => {
    const bootShell = document.createElement('div')
    bootShell.id = 'inteliscope-bootstrap-shell'
    document.body.append(bootShell)
    window.localStorage.removeItem('inteliscope.ui.bootstrap-shell.v1')
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByRole('heading', { name: '信息流' })).toBeInTheDocument()
      expect(document.getElementById('inteliscope-bootstrap-shell')).not.toBeInTheDocument()
      expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.bootstrap-shell.v1') || 'null')).toEqual({
        userId: 'user-live',
        sidebar: 'collapsed',
        rightRail: 'closed',
        rightRailWidth: 400,
      })
    } finally {
      bootShell.remove()
      window.localStorage.removeItem('inteliscope.ui.bootstrap-shell.v1')
    }
  })

  it('keeps Feed geometry fixed while initial data reveals locally', async () => {
    const feed = deferred<{ schema_version: number; items: Array<{ id: string; title: string; url: string; published_at: string }> }>()
    const api = liveApi({ latestFeed: vi.fn(() => feed.promise) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '信息流' })
    const loading = screen.getByRole('status', { name: '正在读取信息流' })
    expect(loading.closest('[data-loading-reveal="feed"]')).toHaveAttribute('data-loading-state', 'loading')
    expect(document.querySelectorAll('[data-workbench-feed-skeleton-row]')).toHaveLength(5)
    for (const row of document.querySelectorAll<HTMLElement>('[data-workbench-feed-skeleton-row]')) {
      expect(row.style.height).toBe('156px')
      expect(row.querySelector('.inteliscope-skeleton-calm')).not.toBeNull()
    }
    expect(screen.queryByText('0 条内容')).not.toBeInTheDocument()
    expect(document.querySelector('[data-feed-count-skeleton]')).toBeInTheDocument()

    feed.resolve({
      schema_version: 2,
      items: [{ id: 'revealed', title: '浮现内容', url: 'https://example.com/revealed', published_at: '2026-07-22T00:00:00Z' }],
    })

    expect(await screen.findByRole('article', { name: '浮现内容' })).toBeInTheDocument()
    const reveal = document.querySelector('[data-loading-reveal="feed"]')
    expect(reveal).toHaveAttribute('data-loading-state', 'revealing')
    expect(reveal?.querySelector('[data-loading-layer]')).toHaveClass('inteliscope-skeleton-exit')
    expect(reveal?.querySelector('[data-content-layer]')).toHaveClass('inteliscope-content-reveal')
    fireEvent.animationEnd(reveal!.querySelector('[data-loading-layer]')!, { animationName: 'inteliscope-skeleton-exit' })
    await waitFor(() => expect(reveal?.querySelector('[data-loading-layer]')).not.toBeInTheDocument())
    expect(screen.getByText('近7天 · 1 条')).toBeInTheDocument()
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
    expect(within(viewBar).getByPlaceholderText('搜索当前列表')).toBeInTheDocument()
    expect(within(viewBar).getByRole('button', { name: '排序顺序：最新优先' })).toBeInTheDocument()
    expect(within(viewBar).queryByRole('button', { name: '重新载入信息流数据' })).not.toBeInTheDocument()
    expect(within(viewBar).queryByRole('button', { name: '获取新内容' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
    expect(screen.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
    expect(screen.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-fresh-edge', 'start')
  })

  it('offers an eight-second Undo action that restores a removed saved item in place', async () => {
    const browser = userEvent.setup()
    const savedItem = {
      ...basicFeedItem('undo-saved', '可撤销收藏'),
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    }
    const updateItemState = vi.fn()
      .mockResolvedValueOnce({ ...savedItem.user_state, is_saved: false })
      .mockResolvedValueOnce(savedItem.user_state)
    const api = liveApi({
      savedFeed: vi.fn().mockResolvedValue({ items: [savedItem] }),
      updateItemState,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/saved']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '可撤销收藏' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '取消收藏 可撤销收藏' }))
    expect(await screen.findByText('已取消收藏')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('article', { name: '可撤销收藏' })).not.toBeInTheDocument())
    await browser.click(screen.getByRole('button', { name: '撤销' }))

    await waitFor(() => expect(updateItemState).toHaveBeenNthCalledWith(2, 'undo-saved', { is_saved: true }))
    expect(await screen.findByRole('article', { name: '可撤销收藏' })).toBeInTheDocument()
  })

  it('restores an ignored Feed item through the same guarded Undo flow', async () => {
    const browser = userEvent.setup()
    const item = basicFeedItem('undo-dismissed', '可撤销忽略')
    const updateItemState = vi.fn()
      .mockResolvedValueOnce({ ...item.user_state, dismissed: true })
      .mockResolvedValueOnce({ ...item.user_state, dismissed: false })
    const api = liveApi({
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [item] }),
      updateItemState,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    const card = await screen.findByRole('article', { name: '可撤销忽略' })
    await browser.click(within(card).getByRole('button', { name: '更多操作 可撤销忽略' }))
    await browser.click(screen.getByRole('button', { name: '忽略' }))
    expect(await screen.findByText('已忽略这条内容')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('article', { name: '可撤销忽略' })).not.toBeInTheDocument())
    await browser.click(screen.getByRole('button', { name: '撤销' }))

    await waitFor(() => expect(updateItemState).toHaveBeenNthCalledWith(2, 'undo-dismissed', { dismissed: false }))
    expect(await screen.findByRole('article', { name: '可撤销忽略' })).toBeInTheDocument()
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
    await userEvent.click(screen.getByRole('button', { name: '排序顺序：最新优先' }))
    expect(screen.getByRole('button', { name: '排序顺序：最旧优先' })).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.feed.v2:user-live') || '{}')).toMatchObject({ order: 'oldest' })
  })

  it('shows the Feed active-filter count for persisted preferences', async () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-live', JSON.stringify({ unreadFirst: true, source: 'detail-source', channel: '', topic: '', minScore: 8 }))
    const api = liveApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByRole('button', { name: '筛选信息流，已启用 2 项' })).toHaveTextContent('2')
    } finally {
      window.localStorage.removeItem('inteliscope.ui.feed.v2:user-live')
    }
  })

  it('renders the subscriptions route in the HeroUI shell with an available Agent panel', async () => {
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '订阅与来源' }, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(document.querySelector('[data-page-frame="admin"]')).toBeInTheDocument())
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelector('[data-page-frame="admin"]')).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(screen.queryByRole('complementary', { name: 'OpenClaw 上下文' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '展开 Agent 面板' })).toBeInTheDocument()
    expect(document.querySelector('[class*="Mui"]')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '全部', level: 2 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '工作/项目' })).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: '当前频道订阅' })).toBeInTheDocument()
    const sourceCard = screen.getByText('覆盖频道来源').closest('[data-compact-source-row="subscription"]') as HTMLElement
    expect(sourceCard.querySelector('[data-source-card-header]')).toHaveClass('items-center')
    const healthChip = await within(sourceCard).findByLabelText('健康状态：正常')
    expect(healthChip).toHaveTextContent('正常')
    expect(healthChip).toHaveAttribute('aria-label', '健康状态：正常')
    expect(healthChip).toHaveClass('self-center')
    const scheduleCard = document.querySelector('[data-feed-schedule]') as HTMLElement
    const scheduleSwitch = within(scheduleCard).getByRole('switch', { name: '全局自动更新' })
    expect(scheduleSwitch.closest('[data-slot="switch"]')).toHaveTextContent('')
    expect(within(scheduleCard).getByText('覆盖 1 个订阅')).toBeInTheDocument()
    expect(sourceCard).toHaveTextContent('更新：全局')
    expect(sourceCard).toHaveTextContent('每 1 小时')
    expect(within(scheduleCard).getByRole('button', { name: /更新周期/ })).toBeInTheDocument()
    expect(within(scheduleCard).queryByRole('button', { name: '管理自动更新' })).not.toBeInTheDocument()
    const channelRail = document.querySelector('[data-channel-rail]') as HTMLElement
    const sourceSearch = within(channelRail).getByRole('searchbox', { name: '搜索来源' })
    await userEvent.type(sourceSearch, '不存在')
    expect(screen.getByText('没有匹配的订阅')).toBeInTheDocument()
    expect(sourceSearch).toHaveFocus()
    await userEvent.clear(sourceSearch)
    await userEvent.type(sourceSearch, '覆盖频道')
    expect(screen.getByRole('button', { name: /^立即获取 覆盖频道来源；/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^立即获取 覆盖频道来源；/ }))
    expect(api.feedSchedule).toHaveBeenCalled()
    expect(api.createSourceFetch).toHaveBeenCalledWith(source.id, subscription.id)
  }, 10_000)

  it('keeps a slow schedule check neutral until the backend explicitly responds', async () => {
    const scheduleRequest = deferred<{ enabled: boolean; interval_minutes: number; worker_status: 'ready' }>()
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 },
        items: [],
      }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: [], topics: [] } }),
      feedSchedule: vi.fn().mockReturnValue(scheduleRequest.promise),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('正在检查后台服务')).toBeInTheDocument()
    expect(screen.getByText('当前没有跟随全局的订阅')).toBeInTheDocument()
    expect(screen.queryByText('后台服务不可用')).not.toBeInTheDocument()
    act(() => scheduleRequest.resolve({ enabled: true, interval_minutes: 60, worker_status: 'ready' }))
    await waitFor(() => expect(screen.getByRole('switch', { name: '全局自动更新' })).toBeChecked())
    expect(screen.queryByText('正在检查后台服务')).not.toBeInTheDocument()
  })

  it('ignores 100 historical feed-job terminals and keeps the full jobs query dormant', async () => {
    const browser = userEvent.setup()
    const historicalJobs = Array.from({ length: 100 }, (_, index): Job => ({
      id: `historical-source-job-${index}`,
      user_id: 'user-live',
      job_type: 'source_fetch',
      source_id: `historical-source-${index}`,
      subscription_id: `historical-subscription-${index}`,
      status: index % 2 === 0 ? 'succeeded' : 'failed',
      created_at: `2026-07-16T${String(index % 24).padStart(2, '0')}:00:00Z`,
      finished_at: `2026-07-16T${String(index % 24).padStart(2, '0')}:00:01Z`,
      error_message: index % 2 === 0 ? undefined : '历史错误不应弹出',
    }))
    const feedJobs = vi.fn().mockResolvedValue({ jobs: historicalJobs })
    const jobs = vi.fn().mockResolvedValue({ jobs: historicalJobs })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [] }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 },
        items: [],
      }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: [], topics: [] } }),
      feedJobs,
      jobs,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '订阅与来源' })).toBeInTheDocument()
    await waitFor(() => expect(feedJobs).toHaveBeenCalledOnce())
    await act(async () => Promise.resolve())
    expect(jobs).not.toHaveBeenCalled()
    expect(api.latestFeed).not.toHaveBeenCalled()
    expect(invalidate).not.toHaveBeenCalled()
    expect(screen.queryByText('历史错误不应弹出')).not.toBeInTheDocument()

    await browser.click(await screen.findByRole('tab', { name: '运行记录' }))
    await waitFor(() => expect(jobs).toHaveBeenCalledOnce())
    await waitFor(() => expect(document.querySelectorAll('[data-compact-job-card]')).toHaveLength(100))
  })

  it('settles two same-batch source fetches with one canonical Feed reload and one global invalidation batch', async () => {
    const browser = userEvent.setup()
    const feedReload = deferred<{ schema_version: number; items: FeedItem[] }>()
    const sources = [
      { id: 'batch-source-a', type: 'rss', display_name: '批量来源 A', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true },
      { id: 'batch-source-b', type: 'rss', display_name: '批量来源 B', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true },
    ]
    const subscriptions = sources.map((source, index) => ({
      id: `batch-subscription-${index}`,
      user_id: 'user-live',
      source_id: source.id,
      source_display_name: source.display_name,
      source_type: source.type,
      enabled: true,
    }))
    const queuedJobs = sources.map((source, index): Job => ({
      id: `batch-job-${index}`,
      user_id: 'user-live',
      job_type: 'source_fetch',
      source_id: source.id,
      subscription_id: subscriptions[index].id,
      status: 'queued',
      created_at: `2026-07-17T01:00:0${index}Z`,
    }))
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 0, degraded: 0, failing: 0, unknown: 2, total: 2 },
        items: [],
      }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      createSourceFetch: vi.fn().mockImplementation((sourceId: string) => Promise.resolve(
        queuedJobs.find((job) => job.source_id === sourceId),
      )),
      latestFeed: vi.fn().mockReturnValue(feedReload.promise),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    for (const source of sources) {
      await browser.click(await screen.findByRole('button', { name: new RegExp(`^立即获取 ${source.display_name}；`) }))
    }
    await waitFor(() => expect(api.createSourceFetch).toHaveBeenCalledTimes(2))
    invalidate.mockClear()

    act(() => queryClient.setQueryData(queryKeys.feedJobs('user-live'), {
      jobs: queuedJobs.map((job, index) => ({
        ...job,
        status: index === 0 ? 'succeeded' : 'partial',
        finished_at: `2026-07-17T01:00:1${index}Z`,
        result: { new_item_count: index + 1, snapshot_created: true },
      })),
    }))

    await waitFor(() => expect(api.latestFeed).toHaveBeenCalledOnce())
    const invalidatedKeys = () => invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
    await waitFor(() => {
      expect(invalidatedKeys().filter((key) => key === JSON.stringify(queryKeys.sourceHealth('user-live')))).toHaveLength(1)
      expect(invalidatedKeys().filter((key) => key === JSON.stringify(queryKeys.historyRoot('user-live')))).toHaveLength(1)
    })
    expect(invalidatedKeys()).not.toContain(JSON.stringify(queryKeys.jobs('user-live')))

    act(() => feedReload.resolve({ schema_version: 2, items: [basicFeedItem('batch-result', '批量结果')] }))
    expect(await screen.findByText('批量来源 A 获取完成')).toBeInTheDocument()
    expect(await screen.findByText('批量来源 B 部分完成')).toBeInTheDocument()
    expect(screen.getAllByText(/批量来源 [AB] (获取完成|部分完成)/)).toHaveLength(2)
  }, 10_000)

  it('optimistically toggles card notifications and rolls back a failed PATCH', async () => {
    const browser = userEvent.setup()
    const source = {
      id: 'notification-source',
      type: 'rss',
      display_name: '通知回滚来源',
      scope: 'private' as const,
      owner_user_id: 'user-live',
      default_channel: 'AI',
      enabled: true,
    }
    const subscription = {
      id: 'notification-subscription',
      user_id: 'user-live',
      source_id: source.id,
      source_display_name: source.display_name,
      source_type: source.type,
      enabled: true,
      analysis_mode: 'full' as const,
      notify_on_new_items: false,
    }
    let rejectUpdate: (reason?: unknown) => void = () => undefined
    const updateSubscription = vi.fn(() => new Promise((_resolve, reject) => {
      rejectUpdate = reject
    }))
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 1, degraded: 0, failing: 0, unknown: 0, total: 1 }, items: [{ subscription_id: subscription.id, source_id: source.id, status: 'healthy', consecutive_failures: 0 }] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      updateSubscription,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    const notification = await screen.findByRole('switch', { name: '新内容通知：通知回滚来源' })
    expect(notification).not.toBeChecked()
    await browser.click(notification)
    await waitFor(() => expect(updateSubscription).toHaveBeenCalledWith(subscription.id, { notify_on_new_items: true }))
    expect(notification).toBeChecked()
    expect(notification).toHaveAttribute('aria-disabled', 'true')

    rejectUpdate(new Error('保存失败'))
    await waitFor(() => {
      expect(notification).not.toBeChecked()
      expect(notification).toBeEnabled()
    })
    expect(await screen.findByText('通知回滚来源 通知设置保存失败')).toBeInTheDocument()
  })

  it('preserves a custom source schedule when a notification PATCH omits schedule data', async () => {
    const browser = userEvent.setup()
    const source = {
      id: 'notification-schedule-source',
      type: 'rss',
      display_name: '自定义周期来源',
      scope: 'private' as const,
      owner_user_id: 'user-live',
      default_channel: 'AI',
      enabled: true,
    }
    const schedule = {
      enabled: true,
      interval_minutes: 60,
      allowed_intervals: [30, 60, 180, 360],
      next_run_at: '2026-07-30T04:00:00Z',
      worker_status: 'ready',
    }
    const subscription = {
      id: 'notification-schedule-subscription',
      user_id: 'user-live',
      source_id: source.id,
      source_display_name: source.display_name,
      source_type: source.type,
      enabled: true,
      analysis_mode: 'full' as const,
      notify_on_new_items: false,
      schedule,
    }
    const updateSubscription = vi.fn().mockResolvedValue({
      id: subscription.id,
      user_id: subscription.user_id,
      source_id: subscription.source_id,
      source_display_name: subscription.source_display_name,
      source_type: subscription.source_type,
      enabled: subscription.enabled,
      analysis_mode: subscription.analysis_mode,
      notify_on_new_items: true,
    })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 1, degraded: 0, failing: 0, unknown: 0, total: 1 }, items: [{ subscription_id: subscription.id, source_id: source.id, status: 'healthy', consecutive_failures: 0 }] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      updateSubscription,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    const notification = await screen.findByRole('switch', { name: '新内容通知：自定义周期来源' })
    await browser.click(notification)
    await waitFor(() => expect(updateSubscription).toHaveBeenCalledWith(subscription.id, { notify_on_new_items: true }))
    await waitFor(() => expect(notification).toBeEnabled())

    expect(queryClient.getQueryData(queryKeys.subscriptions('user-live'))).toMatchObject({
      subscriptions: [{ id: subscription.id, notify_on_new_items: true, schedule }],
    })
  })

  it('keeps channel choices independent across tabs and falls back when filtering removes a channel', async () => {
    const browser = userEvent.setup()
    const sources = [
      { id: 'channel-ai', type: 'rss', display_name: 'AI 来源', scope: 'public' as const, default_channel: 'AI', enabled: true },
      { id: 'channel-work', type: 'github_release', display_name: '项目来源', scope: 'workspace' as const, default_channel: '工作/项目', enabled: true },
      { id: 'channel-finance', type: 'rss', display_name: '金融来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: '金融', enabled: true },
    ]
    const subscriptions = sources.slice(0, 2).map((source, index) => ({
      id: `channel-sub-${index}`,
      user_id: 'user-live',
      source_id: source.id,
      source_display_name: source.display_name,
      source_type: source.type,
      enabled: true,
    }))
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }, { type: 'github_release', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 2, degraded: 0, failing: 0, unknown: 0, total: 2 },
        items: subscriptions.map((subscription) => ({ subscription_id: subscription.id, source_id: subscription.source_id, status: 'healthy' as const, consecutive_failures: 0 })),
      }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI', '工作/项目', '金融'], topics: [] } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '全部', level: 2 })
    await browser.click(within(screen.getByRole('navigation', { name: '我的订阅频道' })).getByRole('button', { name: /工作\/项目/ }))
    expect(screen.getByRole('heading', { name: '工作/项目' })).toBeInTheDocument()
    expect(screen.getByText('项目来源')).toBeInTheDocument()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    expect(screen.getByRole('heading', { name: 'AI' })).toBeInTheDocument()
    await browser.click(within(screen.getByRole('navigation', { name: '来源库频道' })).getByRole('button', { name: /金融/ }))
    expect(screen.getByRole('heading', { name: '金融' })).toBeInTheDocument()

    await browser.click(screen.getByRole('tab', { name: '我的订阅' }))
    expect(screen.getByRole('heading', { name: '工作/项目' })).toBeInTheDocument()
    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    expect(screen.getByRole('heading', { name: '金融' })).toBeInTheDocument()

    const compactControls = document.querySelector('[data-compact-channel-controls]') as HTMLElement
    await browser.type(within(compactControls).getByRole('searchbox', { name: '搜索来源' }), 'AI 来源')
    expect(screen.getByRole('heading', { name: 'AI' })).toBeInTheDocument()
    expect(screen.getByText('AI 来源')).toBeInTheDocument()
  })

  it('deep-links subscription tabs without permanent count badges', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: [], topics: [] } }),
      jobs: vi.fn().mockResolvedValue({ jobs: [] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions?tab=jobs']}><DesignSystemProvider><AppRoutes api={api} /><LocationProbe /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('tab', { name: '运行记录' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: '我的订阅' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '来源库' })).toBeInTheDocument()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('/subscriptions?tab=library')
    await browser.click(screen.getByRole('tab', { name: '我的订阅' }))
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('/subscriptions?tab=subscriptions')
  })

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
    const subscriptionNavigation = screen.getByRole('navigation', { name: '我的订阅频道' })
    expect(within(subscriptionNavigation).getByRole('button', { name: /^全部，/ })).toBeInTheDocument()
    await browser.click(within(subscriptionNavigation).getByRole('button', { name: /^公共订阅，/ }))
    expect(screen.getByText('Workspace Failing')).toBeInTheDocument()
    expect(screen.getByText('Public Degraded')).toBeInTheDocument()
    expect(screen.queryByText('Private Healthy')).not.toBeInTheDocument()
    await browser.click(within(subscriptionNavigation).getByRole('button', { name: /^私人订阅，/ }))
    expect(screen.getByText('Private Healthy')).toBeInTheDocument()
    expect(screen.queryByText('Workspace Failing')).not.toBeInTheDocument()
    await browser.click(within(subscriptionNavigation).getByRole('button', { name: /^异常，/ }))
    expect(screen.getByRole('heading', { name: '异常', level: 2 })).toBeInTheDocument()
    expect(screen.getByText('Workspace Failing')).toBeInTheDocument()
    expect(screen.getByText('Public Degraded')).toBeInTheDocument()
    expect(screen.queryByText('Private Healthy')).not.toBeInTheDocument()
    await browser.click(within(subscriptionNavigation).getByRole('button', { name: /^全部，/ }))
    await browser.click(screen.getAllByRole('button', { name: '筛选来源，已启用 0 项' })[0])
    const filterDialog = await screen.findByRole('dialog', { name: '筛选来源' })
    await browser.click(within(filterDialog).getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: 'GitHub 发布' }))
    expect(screen.getByText('Workspace Failing')).toBeInTheDocument()
    expect(screen.queryByText('Private Healthy')).not.toBeInTheDocument()
    expect(screen.queryByText('Public Degraded')).not.toBeInTheDocument()

    await browser.click(within(filterDialog).getByRole('button', { name: /健康状态/ }))
    await browser.click(await screen.findByRole('option', { name: '连续失败' }))
    await browser.click(within(filterDialog).getByRole('button', { name: /可见范围/ }))
    await browser.click(await screen.findByRole('option', { name: '公共订阅' }))
    expect(screen.getByText('Workspace Failing')).toBeInTheDocument()

    await browser.click(within(filterDialog).getByRole('button', { name: /健康状态/ }))
    await browser.click(await screen.findByRole('option', { name: '正常' }))
    expect(screen.getByText('没有匹配的订阅')).toBeInTheDocument()
    expect(screen.getAllByText('全局自动更新').length).toBeGreaterThan(0)
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
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 1, unknown: 0, total: 1 }, items: [{ subscription_id: subscription.id, source_id: source.id, status: 'failing', consecutive_failures: 3, last_fetched_count: 0, last_attempt_at: '2026-07-18T03:00:00Z', last_success_at: '2026-07-10T03:00:00Z', last_issue: { stage: 'fetch', code: 'HTTPError', message: rawMessage, retryable: true } }] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const card = (await screen.findByText('异常来源')).closest('[data-slot="card"]') as HTMLElement
    expect(within(card).queryByText(/原因：/)).not.toBeInTheDocument()
    expect(within(card).queryByText(rawMessage)).not.toBeInTheDocument()
    const latestAttempt = new Date('2026-07-18T03:00:00Z').toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    expect(card).toHaveTextContent(`今日0近7天0历史0更新：全局·每 1 小时·${latestAttempt}`)

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

    expect(await screen.findByRole('button', { name: '编辑来源：Own Private' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '分享来源：Own Private' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更多操作：Own Private' })).not.toBeInTheDocument()
    for (const sourceName of ['Other Private', 'Workspace Shared', 'Public Shared']) {
      expect(screen.queryByRole('button', { name: `编辑来源：${sourceName}` })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: `分享来源：${sourceName}` })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: `更多操作：${sourceName}` })).not.toBeInTheDocument()
    }
  })

  it('keeps viewer subscription rows read-only without a source-management menu', async () => {
    const browser = userEvent.setup()
    const source = { id: 'viewer-source', type: 'rss', display_name: '只读来源', scope: 'public' as const, default_channel: 'AI', enabled: true }
    const subscription = { id: 'viewer-sub', user_id: 'viewer-user', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true }
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'viewer-user', username: 'viewer', role: 'viewer', enabled: true } }),
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 1, degraded: 0, failing: 0, unknown: 0, total: 1 }, items: [{ subscription_id: subscription.id, source_id: source.id, status: 'healthy', consecutive_failures: 0 }] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('button', { name: '查看 只读来源 订阅' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '立即获取 只读来源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新增来源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '分享来源：只读来源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更多操作：只读来源' })).not.toBeInTheDocument()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    expect(screen.getByRole('button', { name: '取消订阅 只读来源' })).toBeDisabled()
  })

  it('protects and explicitly clears a live one-time Agent token', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      agentDelegations: vi.fn().mockResolvedValue({ enabled: true, subscription_writes_enabled: false, mcp_url: '/mcp', openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5, connections: [] }),
      createAgentDelegation: vi.fn().mockResolvedValue({
        connection: { id: 'agent-new', name: 'Desk Mac', client_type: 'openclaw', access: 'read', diagnostics_scope: 'self', scopes: ['inteliscope:read'], token_prefix: 'ih_new', created_at: '2026-07-17T00:00:00Z', expires_at: '2026-10-17T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' },
        token: 'ih_mcp_one_time_live',
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/agents']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '助手连接' })).toBeInTheDocument()
    await waitFor(() => expect(document.querySelector('[data-page-frame="admin"]')).toBeInTheDocument())
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

  it('explains a live single-source fetch block in an overlay without queueing work', async () => {
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('已关闭 · 1 个订阅等待全局开启')).toBeInTheDocument()
    expect(screen.getByText('更新：跟随全局')).toBeInTheDocument()
    expect(screen.getByText('全局已关闭')).toBeInTheDocument()
    await browser.click(await screen.findByRole('button', { name: /^立即获取 阻塞来源；/ }))
    const message = await screen.findByText('后台获取服务当前不可用，请稍后再试。')
    expect(message.closest('[data-slot="toast-region"]')).not.toBeNull()
    expect(message.closest('[data-page-frame]')).toBeNull()
    expect(createSourceFetch).not.toHaveBeenCalled()
  })

  it('settles a live source fetch through queued, running and terminal lifecycle states', async () => {
    const browser = userEvent.setup()
    const feedReload = deferred<{ schema_version: number; items: FeedItem[] }>()
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
      latestFeed: vi.fn().mockReturnValue(feedReload.promise),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: /^立即获取 生命周期来源；/ }))
    expect(await screen.findByRole('button', { name: /^已排队 生命周期来源；/ })).toBeDisabled()
    invalidate.mockClear()

    act(() => queryClient.setQueryData(queryKeys.feedJobs('user-live'), { jobs: [{ ...queued, status: 'running', started_at: '2026-07-17T01:00:01Z' }] }))
    expect(await screen.findByRole('button', { name: /^获取中 生命周期来源；/ })).toBeDisabled()
    expect(invalidate).not.toHaveBeenCalled()

    act(() => queryClient.setQueryData(queryKeys.feedJobs('user-live'), { jobs: [{ ...queued, status: 'succeeded', started_at: '2026-07-17T01:00:01Z', finished_at: '2026-07-17T01:00:03Z', result: { item_count: 4, new_item_count: 2 } }] }))
    await waitFor(() => expect(api.latestFeed).toHaveBeenCalledOnce())
    expect(screen.queryByText('生命周期来源 获取完成')).not.toBeInTheDocument()
    act(() => feedReload.resolve({ schema_version: 2, items: [basicFeedItem('lifecycle-feed', '生命周期信息流条目')] }))
    const completion = await screen.findByText('生命周期来源 获取完成')
    expect(completion.closest('[data-slot="toast-region"]')).not.toBeNull()
    expect(screen.getByText('新增 2 条，信息流已加载。')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^立即获取 生命周期来源；/ })).toBeEnabled()
    await waitFor(() => {
      const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
      expect(keys).toContain(JSON.stringify(queryKeys.sourceHealth('user-live')))
      expect(keys).toContain(JSON.stringify(queryKeys.historyRoot('user-live')))
      expect(keys).not.toContain(JSON.stringify(queryKeys.jobs('user-live')))
    })
  }, 10_000)

  it('does not replay a cleared source-fetch terminal toast across polling rerenders', async () => {
    const browser = userEvent.setup()
    const source = { id: 'dismiss-source', type: 'rss', display_name: '可关闭来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'dismiss-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true }
    const queued: Job = { id: 'dismiss-job', user_id: 'user-live', job_type: 'source_fetch', source_id: source.id, subscription_id: subscription.id, status: 'queued', created_at: '2026-07-17T01:00:00Z' }
    const terminal: Job = { ...queued, status: 'failed', finished_at: '2026-07-17T01:00:01Z', error_message: '可关闭的抓取失败' }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }), sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }), feedJobs: vi.fn().mockResolvedValue({ jobs: [] }), createSourceFetch: vi.fn().mockResolvedValue(queued),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: /^立即获取 可关闭来源；/ }))
    act(() => queryClient.setQueryData(queryKeys.feedJobs('user-live'), { jobs: [terminal] }))
    expect(await screen.findByText('可关闭的抓取失败')).toBeInTheDocument()
    actionToast.clear()
    await waitFor(() => expect(screen.queryByText('可关闭的抓取失败')).not.toBeInTheDocument())

    await act(async () => {
      queryClient.setQueryData(queryKeys.feedJobs('user-live'), { jobs: [{ ...terminal }] })
      await Promise.resolve()
    })
    expect(screen.queryByText('可关闭的抓取失败')).not.toBeInTheDocument()
  })

  it.each([
    ['partial', undefined, '终态来源 部分完成', '信息流已加载；请查看运行记录。'],
    ['failed', '上游连接超时', '终态来源 获取失败', '上游连接超时'],
    ['cancelled', undefined, '终态来源 获取已取消', '任务已取消。'],
  ] as const)('surfaces sanitized live source fetch terminal state %s', async (status, errorMessage, title, description) => {
    const browser = userEvent.setup()
    const source = { id: `terminal-${status}`, type: 'rss', display_name: '终态来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: `terminal-sub-${status}`, user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true, priority: 0 }
    const queued: Job = { id: `terminal-job-${status}`, user_id: 'user-live', job_type: 'source_fetch', source_id: source.id, subscription_id: subscription.id, status: 'queued', created_at: '2026-07-17T01:00:00Z' }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }), sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }), subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }), config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }), feedJobs: vi.fn().mockResolvedValue({ jobs: [] }), createSourceFetch: vi.fn().mockResolvedValue(queued),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: /^立即获取 终态来源；/ }))
    act(() => queryClient.setQueryData(queryKeys.feedJobs('user-live'), { jobs: [{ ...queued, status, error_message: errorMessage, retryable: status === 'failed', result: { debug_payload: 'never expose this terminal payload' } }] }))
    const terminalTitle = await screen.findByText(title)
    expect(terminalTitle.closest('[data-slot="toast-region"]')).not.toBeNull()
    expect(screen.getByText(description)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^立即获取 终态来源；/ })).toBeEnabled()
    expect(screen.queryByText('never expose this terminal payload')).not.toBeInTheDocument()
  }, 10_000)

  it('shows compact run timing with an in-progress fallback', async () => {
    const browser = userEvent.setup()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'user-live', username: 'owner', role: 'owner', enabled: true } }),
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
    expect(await screen.findAllByText(/创建 .* · /)).toHaveLength(3)
    expect(screen.getByText(/创建 .* · 进行中/)).toBeInTheDocument()
    expect(screen.getAllByText(/· 完成 /)).toHaveLength(2)
    expect(document.querySelectorAll('[data-compact-job-card]')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
    const completedCard = screen.getByText('测试来源连接').closest('[data-compact-job-card]') as HTMLElement
    const technicalTrigger = within(completedCard).getByRole('button', { name: '技术详情' })
    const schemaTrigger = within(completedCard).getByRole('button', { name: '响应结构' })
    expect(technicalTrigger).toHaveAttribute('aria-expanded', 'false')
    expect(schemaTrigger).toHaveAttribute('aria-expanded', 'false')
    await browser.click(technicalTrigger)
    await browser.click(schemaTrigger)
    expect(technicalTrigger).toHaveAttribute('aria-expanded', 'true')
    expect(schemaTrigger).toHaveAttribute('aria-expanded', 'true')
    expect(completedCard.querySelectorAll('[data-disclosure-state="open"]')).toHaveLength(2)
  })

  it('adds a readable run record to OpenClaw context without exposing the job id', async () => {
    const browser = userEvent.setup()
    const source = { id: 'context-source', type: 'rss', display_name: '上下文来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const job = { id: 'internal-job-id', user_id: 'user-live', job_type: 'source_test' as const, source_id: source.id, status: 'succeeded' as const, created_at: '2026-07-17T02:00:00Z', finished_at: '2026-07-17T02:00:04Z', result: { item_count: 2 } }
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      jobs: vi.fn().mockResolvedValue({ jobs: [job] }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('tab', { name: '运行记录' }))
    await browser.click(await screen.findByRole('button', { name: '加入 OpenClaw 上下文：测试来源连接' }))
    await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/subscriptions'))
    await waitFor(() => {
      const contextItem = document.querySelector('[data-context-resource="job"]')
      expect(contextItem).toBeInTheDocument()
      expect(contextItem).toHaveTextContent('测试来源连接')
    })
    expect(screen.queryByText('internal-job-id')).not.toBeInTheDocument()
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

    await browser.click(await screen.findByRole('switch', { name: '全局自动更新' }))
    const schedulePending = await screen.findByRole('switch', { name: '全局自动更新' })
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

  it('keeps catalog mutations pending for refreshed state while retry updates the job cache directly', async () => {
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

    const scheduleButton = await screen.findByRole('switch', { name: '全局自动更新' })
    expect(scheduleButton).toBeChecked()
    invalidate.mockClear()
    await browser.click(scheduleButton)
    expect(await screen.findByRole('switch', { name: '全局自动更新' })).toBeDisabled()
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
      retryRequest.resolve({ ...retryJob, status: 'queued', retryable: false })
      await Promise.resolve()
    })
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(13))

    await browser.click(screen.getByRole('tab', { name: '我的订阅' }))
    const schedulePending = screen.getByRole('switch', { name: '全局自动更新' })
    expect(schedulePending).toBeDisabled()
    fireEvent.click(schedulePending)
    expect(api.updateFeedSchedule).toHaveBeenCalledOnce()

    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeInTheDocument()
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
    const refreshedSchedule = await screen.findByRole('switch', { name: '全局自动更新' })
    expect(refreshedSchedule).toBeEnabled()
    expect(refreshedSchedule).not.toBeChecked()
    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    expect(await screen.findByRole('button', { name: '订阅 刷新前已订阅' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '取消订阅 刷新前未订阅' })).toBeEnabled()
    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeInTheDocument()
  }, 15_000)

  it('renders overlay errors for live schedule, subscribe, unsubscribe and retry actions', async () => {
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('switch', { name: '全局自动更新' }))
    expect((await screen.findByText('计划保存失败')).closest('[data-slot="toast-region"]')).not.toBeNull()

    await browser.click(screen.getByRole('tab', { name: '来源库' }))
    await browser.click(await screen.findByRole('button', { name: '取消订阅 错误已订阅来源' }))
    expect((await screen.findAllByText(/取消订阅失败/)).length).toBeGreaterThan(0)
    await browser.click(screen.getByRole('button', { name: '订阅 错误未订阅来源' }))
    expect(await screen.findByText('订阅请求失败')).toBeInTheDocument()

    await browser.click(screen.getByRole('tab', { name: '运行记录' }))
    await browser.click(await screen.findByRole('button', { name: '重试' }))
    expect((await screen.findByText('重试请求失败')).closest('[data-slot="toast-region"]')).not.toBeNull()
  }, 15_000)

  it('shows successful Key creation once in a top overlay without adding a page notice', async () => {
    const browser = userEvent.setup()
    const createSecret = vi.fn().mockResolvedValue({
      id: 'secret-new',
      name: 'DeepSeek',
      kind: 'ai',
      provider: 'deepseek',
      env_name: 'DEEPSEEK_API_KEY',
      is_set: true,
      used_by: [],
    })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-key-success', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      createSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/secrets']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByText('新增密钥')
    await browser.click(screen.getByRole('button', { name: '新增 Key' }))
    await browser.type(await screen.findByRole('textbox', { name: 'Key 名称' }), 'DeepSeek')
    await browser.type(screen.getByRole('textbox', { name: 'Key provider' }), 'deepseek')
    await browser.type(screen.getByRole('textbox', { name: '环境变量名' }), 'DEEPSEEK_API_KEY')
    await browser.type(screen.getByLabelText('Key 值'), 'write-only-value')
    await browser.click(screen.getByRole('button', { name: '安全保存 Key' }))

    await waitFor(() => expect(createSecret).toHaveBeenCalledOnce())
    const successMessages = await screen.findAllByText('Key 已安全保存')
    expect(successMessages).toHaveLength(1)
    expect(successMessages[0].closest('[data-slot="toast-region"]')).not.toBeNull()
    expect(successMessages[0].closest('[data-page-frame]')).toBeNull()
    expect(screen.queryByText('Key 已保存，页面不会回显真实值。')).not.toBeInTheDocument()
  }, 15_000)

  it('redirects legacy secret bookmarks and blocks direct secret access without data requests', async () => {
    const ownerApi = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-settings-hash', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
    } as Partial<ServiceApi>)
    const ownerClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const ownerView = render(<QueryClientProvider client={ownerClient}><MemoryRouter initialEntries={['/settings/legacy#settings-secrets']}><DesignSystemProvider><AppRoutes api={ownerApi} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByText('新增密钥')
    await waitFor(() => expect(document.querySelector('[data-settings-page="secrets"]')).toBeInTheDocument())
    ownerView.unmount()

    const secrets = vi.fn()
    const apifyKeyPool = vi.fn()
    const secretQuota = vi.fn()
    const memberApi = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'member-settings-hash', username: 'member', role: 'member', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets,
      apifyKeyPool,
      secretQuota,
    } as Partial<ServiceApi>)
    const memberClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={memberClient}><MemoryRouter initialEntries={['/settings/secrets']}><DesignSystemProvider><AppRoutes api={memberApi} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '概览', level: 1 })).toBeInTheDocument()
    await waitFor(() => expect(document.querySelector('[data-settings-page="overview"]')).toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: '密钥' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '高级' })).not.toBeInTheDocument()
    expect(secrets).not.toHaveBeenCalled()
    expect(apifyKeyPool).not.toHaveBeenCalled()
    expect(secretQuota).not.toHaveBeenCalled()
  })

  it('keeps the settings overview request-free and loads only the selected native page', async () => {
    const browser = userEvent.setup()
    const config = vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } })
    const secrets = vi.fn().mockResolvedValue({ secrets: [] })
    const ignoredFeed = vi.fn().mockResolvedValue({ items: [], pagination: { limit: 200, offset: 0, count: 0, total: 0 } })
    const notificationSettings = vi.fn().mockResolvedValue({
      schema_version: 4,
      enabled: true,
      target_ids: [],
      selected_targets: [],
      channels: ['webhook'],
      channel: 'webhook',
      channel_states: notificationChannelStates({ webhookConfigured: true }),
      email_configured: false,
      email_transport_ready: true,
      webhook_configured: true,
      webhook_provider: 'generic_event',
      webhook_provider_explicit: true,
      webhook_signing_secret_configured: false,
      webhook_verification_mode: 'http_status',
      webhook_provider_options: webhookProviderOptions(),
      telegram_configured: false,
      telegram_transport_ready: true,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
      updated_at: '2026-07-30T00:00:00Z',
    })
    const notificationTargets = vi.fn().mockResolvedValue({
      schema_version: 1,
      targets: [],
      webhook_provider_options: webhookProviderOptions(),
    })
    const notificationServices = vi.fn().mockResolvedValue({
      schema_version: 1,
      services: [],
      channel_credentials: {
        email: {
          configured: false,
          ready: false,
          generation: 0,
          provider: null,
          sender_name: 'Inteliscope',
          region: null,
          sender_email_configured: false,
          smtp_username_configured: false,
          providers: [],
        },
        telegram: { configured: false, ready: false, generation: 0 },
        webhook: { configured: true, ready: true, generation: 0 },
      },
      webhook_provider_options: webhookProviderOptions(),
      can_manage: true,
    })
    const notificationEmailTransport = vi.fn().mockResolvedValue({
      schema_version: 1,
      configured: false,
      provider: null,
      sender_email: null,
      sender_name: 'Inteliscope',
      region: null,
      smtp_username: null,
      enabled: false,
      credential_configured: false,
      generation: 0,
      last_test_status: null,
      last_test_generation: null,
      last_tested_at: null,
      last_test_error_code: null,
      can_enable: false,
      ready: false,
      connection: null,
      providers: [],
      updated_at: null,
    })
    const notificationTelegramTransport = vi.fn().mockResolvedValue(emptyTelegramTransport())
    const hiddenQueries = {
      config,
      secrets,
      ignoredFeed,
      notificationSettings,
      notificationTargets,
      notificationServices,
      notificationEmailTransport,
      notificationTelegramTransport,
      apifyKeyPool: vi.fn().mockResolvedValue({ enabled: false, generation: 0, status: 'disabled', active_secret_id: null, members: [] }),
      apifyActorRoutes: vi.fn(),
      apifyActorAlertSettings: vi.fn(),
      apifyActorAlertIncidents: vi.fn(),
      storageSummary: vi.fn(),
      storageArchives: vi.fn(),
      secretQuota: vi.fn(),
      feedEndMessages: vi.fn(),
    }
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-settings-lazy', username: 'owner', role: 'owner', enabled: true } }),
      ...hiddenQueries,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '概览', level: 1 })).toBeInTheDocument()
    expect(screen.queryByTestId('live-workbench-shell')).not.toBeInTheDocument()
    expect(document.querySelector('[data-settings-workspace]')).toBeInTheDocument()
    await act(async () => Promise.resolve())
    for (const query of Object.values(hiddenQueries)) expect(query).not.toHaveBeenCalled()

    await browser.click(screen.getByRole('link', { name: '通知' }))
    await waitFor(() => {
      expect(notificationSettings).toHaveBeenCalledOnce()
      expect(notificationTargets).not.toHaveBeenCalled()
      expect(notificationServices).toHaveBeenCalledOnce()
    })
    expect(notificationEmailTransport).not.toHaveBeenCalled()
    expect(notificationTelegramTransport).not.toHaveBeenCalled()
    expect(config).not.toHaveBeenCalled()
    expect(secrets).not.toHaveBeenCalled()
    expect(ignoredFeed).not.toHaveBeenCalled()
    expect(hiddenQueries.apifyActorRoutes).not.toHaveBeenCalled()
    expect(hiddenQueries.storageSummary).not.toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: '通知', level: 1 })).toBeInTheDocument()
    expect(document.querySelector('[data-settings-page="notifications"]')).toBeInTheDocument()
  })

  it('keeps the native AI page read-only without requesting workspace configuration for members', async () => {
    const config = vi.fn()
    const secrets = vi.fn()
    const feedEndMessages = vi.fn()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'member-ai-readonly', username: 'member', role: 'member', enabled: true } }),
      config,
      secrets,
      feedEndMessages,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/ai']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: 'AI', level: 1 })).toBeInTheDocument()
    expect(await screen.findByText('工作区设置只读')).toBeInTheDocument()
    await act(async () => Promise.resolve())
    expect(config).not.toHaveBeenCalled()
    expect(secrets).not.toHaveBeenCalled()
    expect(feedEndMessages).not.toHaveBeenCalled()
  })

  it('redirects members away from fetching without requesting config or ActorOps data', async () => {
    const config = vi.fn()
    const apifyActorRoutes = vi.fn()
    const apifyActorAlertSettings = vi.fn()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'member-fetching-readonly', username: 'member', role: 'member', enabled: true } }),
      config,
      apifyActorRoutes,
      apifyActorAlertSettings,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/fetching']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '概览', level: 1 })).toBeInTheDocument()
    expect(document.querySelector('[data-settings-page="fetching"]')).not.toBeInTheDocument()
    await act(async () => Promise.resolve())
    expect(config).not.toHaveBeenCalled()
    expect(apifyActorRoutes).not.toHaveBeenCalled()
    expect(apifyActorAlertSettings).not.toHaveBeenCalled()
  })

  it('redirects members away from ActorOps without requesting routes, alerts, or incidents', async () => {
    const apifyActorRoutes = vi.fn()
    const apifyActorAlertSettings = vi.fn()
    const apifyActorAlertIncidents = vi.fn()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'member-actorops-readonly', username: 'member', role: 'member', enabled: true } }),
      apifyActorRoutes,
      apifyActorAlertSettings,
      apifyActorAlertIncidents,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/actorops']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '概览', level: 1 })).toBeInTheDocument()
    expect(document.querySelector('[data-settings-page="actorops"]')).not.toBeInTheDocument()
    await act(async () => Promise.resolve())
    expect(apifyActorRoutes).not.toHaveBeenCalled()
    expect(apifyActorAlertSettings).not.toHaveBeenCalled()
    expect(apifyActorAlertIncidents).not.toHaveBeenCalled()
  })

  it('keeps legacy settings reachable inside the workspace without mounting the Feed shell', async () => {
    const config = vi.fn().mockResolvedValue({
      config: { ai: {}, filtering: {}, feed_end_messages: {} },
      taxonomy: { channels: [], topics: [] },
    })
    const secrets = vi.fn().mockResolvedValue({ secrets: [] })
    const ignoredFeed = vi.fn().mockResolvedValue({
      items: [],
      pagination: { limit: 200, offset: 0, count: 0, total: 0 },
    })
    const notificationSettings = vi.fn().mockResolvedValue({
      schema_version: 4,
      enabled: false,
      target_ids: [],
      selected_targets: [],
      channels: ['webhook'],
      channel: 'webhook',
      channel_states: notificationChannelStates({
        webhookConfigured: false,
        emailAvailable: false,
        telegramAvailable: false,
      }),
      email_configured: false,
      email_transport_ready: false,
      webhook_configured: false,
      webhook_provider: 'generic_event',
      webhook_provider_explicit: true,
      webhook_signing_secret_configured: false,
      webhook_verification_mode: 'http_status',
      webhook_provider_options: webhookProviderOptions(),
      telegram_configured: false,
      telegram_transport_ready: false,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
      updated_at: null,
    })
    const notificationTargets = vi.fn().mockResolvedValue({
      schema_version: 1,
      targets: [],
      webhook_provider_options: webhookProviderOptions(),
    })
    const notificationEmailTransport = vi.fn().mockResolvedValue({
      schema_version: 1,
      configured: false,
      provider: null,
      sender_email: null,
      sender_name: 'Inteliscope',
      region: null,
      smtp_username: null,
      enabled: false,
      credential_configured: false,
      generation: 0,
      last_test_status: null,
      last_test_generation: null,
      last_tested_at: null,
      last_test_error_code: null,
      can_enable: false,
      ready: false,
      connection: null,
      providers: [],
      updated_at: null,
    })
    const notificationTelegramTransport = vi.fn().mockResolvedValue(emptyTelegramTransport())
    const notificationServices = vi.fn().mockResolvedValue({
      schema_version: 1,
      services: [],
      channel_credentials: {
        email: {
          configured: false,
          ready: false,
          generation: 0,
          provider: null,
          sender_name: 'Inteliscope',
          region: null,
          sender_email_configured: false,
          smtp_username_configured: false,
          providers: [],
        },
        telegram: { configured: false, ready: false, generation: 0 },
        webhook: { configured: true, ready: true, generation: 0 },
      },
      webhook_provider_options: webhookProviderOptions(),
      can_manage: true,
    })
    const storageSummary = vi.fn().mockResolvedValue({
      schema_version: 1,
      policy: { feed_snapshot_days: 30, feed_snapshot_per_user: 20, source_snapshot_days: 7, completed_job_days: 14, analysis_cache_days: 30, usage_event_days: 90, archive_after_days: 90, automatic_permanent_delete: false },
      bytes: { database: 1024, media: 0, archives: 0 },
      counts: { content_total: 0, content_online: 0, content_archived: 0, feed_snapshots: 0, source_snapshots: 0, media_assets: 0, archive_batches: 0 },
      readiness: { feed_storage_v3: true, content_timeline_v11: true, ready: true },
      last_cleanup_at: null,
    })
    const storageArchives = vi.fn().mockResolvedValue({ schema_version: 1, archives: [] })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-settings-scroll', username: 'owner', role: 'owner', enabled: true } }),
      config,
      secrets,
      ignoredFeed,
      notificationSettings,
      notificationTargets,
      notificationServices,
      notificationEmailTransport,
      notificationTelegramTransport,
      storageSummary,
      storageArchives,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '概览', level: 1 })).toBeInTheDocument()
    expect(config).not.toHaveBeenCalled()
    expect(secrets).not.toHaveBeenCalled()

    await userEvent.setup().click(screen.getByRole('link', { name: 'AI' }))
    expect(await screen.findByRole('heading', { name: 'AI', level: 1 })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '保存 AI 设置' })).toBeInTheDocument()
    expect(document.querySelector('[data-settings-workspace]')).toBeInTheDocument()
    expect(screen.queryByTestId('live-workbench-shell')).not.toBeInTheDocument()
    expect(config).toHaveBeenCalledOnce()
    expect(secrets).toHaveBeenCalledOnce()
    expect(notificationSettings).not.toHaveBeenCalled()
    expect(notificationTargets).not.toHaveBeenCalled()
    expect(notificationServices).not.toHaveBeenCalled()
    expect(notificationEmailTransport).not.toHaveBeenCalled()
    expect(notificationTelegramTransport).not.toHaveBeenCalled()
    expect(ignoredFeed).not.toHaveBeenCalled()
    expect(storageSummary).not.toHaveBeenCalled()
    expect(storageArchives).not.toHaveBeenCalled()
  }, 20_000)

  it('loads each Apify quota once on first Secrets entry and honors its five-minute cache', async () => {
    const browser = userEvent.setup()
    const apifyQuota = {
      secret_id: 'apify-cached',
      provider: 'apify',
      currency: 'USD',
      cycle_start_at: '2026-07-01T00:00:00.000Z',
      cycle_end_at: '2026-07-31T23:59:59.999Z',
      checked_at: '2026-07-30T00:00:00Z',
      monthly_included_credits_usd: 5,
      monthly_usage_usd: 1,
      remaining_included_credits_usd: 4,
      max_monthly_usage_usd: 10,
      remaining_hard_limit_usd: 9,
    }
    const secrets = vi.fn().mockResolvedValue({ secrets: [
      { id: 'apify-cached', name: 'Apify Cached', kind: 'apify', provider: 'apify', env_name: 'APIFY_CACHED', is_set: true, used_by: [] },
      { id: 'ai-unsupported', name: 'AI Unsupported', kind: 'ai', provider: 'openai', env_name: 'OPENAI_API_KEY', is_set: true, used_by: [] },
    ] })
    const secretQuota = vi.fn().mockResolvedValue(apifyQuota)
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-quota-cache', username: 'owner', role: 'owner', enabled: true } }),
      secrets,
      secretQuota,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    let now = Date.parse('2026-07-30T00:00:00Z')
    const nowSpy = vi.spyOn(Date, 'now').mockImplementation(() => now)

    try {
      render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/secrets']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

      expect(await screen.findByText('套餐剩余 $4.00')).toBeInTheDocument()
      expect(secrets).toHaveBeenCalledOnce()
      expect(secretQuota).toHaveBeenCalledOnce()
      expect(secretQuota).toHaveBeenCalledWith('apify-cached')

      await browser.click(screen.getByRole('link', { name: '高级' }))
      now += (5 * 60 * 1000) - 1
      await browser.click(screen.getByRole('link', { name: '密钥' }))
      await act(async () => Promise.resolve())
      expect(secretQuota).toHaveBeenCalledOnce()

      await browser.click(screen.getByRole('link', { name: '高级' }))
      now += 2
      await browser.click(screen.getByRole('link', { name: '密钥' }))
      await waitFor(() => expect(secretQuota).toHaveBeenCalledTimes(2))
    } finally {
      nowSpy.mockRestore()
    }
  })

  it('previews storage cleanup before applying it from the owner settings area', async () => {
    const browser = userEvent.setup()
    const previewPlan = {
      id: 'storage-plan-1',
      actor_user_id: 'owner-storage',
      operation: 'cleanup' as const,
      status: 'previewed' as const,
      payload: {
        request: {},
        parameters: { planned_at: '2026-07-27T04:00:00Z' },
        preview: {
          counts: { feed_snapshots: 2, jobs: 3 },
          permanent_content_deletes: 0,
        },
      },
      result: {},
      fingerprint: 'safe-fingerprint',
      expires_at: '2026-07-27T04:10:00Z',
      created_at: '2026-07-27T04:00:00Z',
      applied_at: null,
      updated_at: '2026-07-27T04:00:00Z',
    }
    const createStoragePlan = vi.fn().mockResolvedValue(previewPlan)
    const applyStoragePlan = vi.fn().mockResolvedValue({
      ...previewPlan,
      status: 'applied',
      result: { operation: 'cleanup', content_items: 0 },
      applied_at: '2026-07-27T04:01:00Z',
    })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-storage', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      createStoragePlan,
      applyStoragePlan,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-storage']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '存储与归档' })).toBeInTheDocument()
    await browser.click(await screen.findByRole('button', { name: '预演标准清理' }))
    expect(createStoragePlan).toHaveBeenCalledWith('cleanup', {})
    expect(await screen.findByText('预计清理 5 条轻量运行记录；稳定内容永久删除数为 0。')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '执行标准清理' }))
    await waitFor(() => expect(applyStoragePlan).toHaveBeenCalledWith('storage-plan-1', ''))
    expect(await screen.findByText('数据状态已刷新；完整结果已记录到审计计划。')).toBeInTheDocument()
  })

  it('shows role-scoped live settings and clears only a failed secret value', async () => {
    const browser = userEvent.setup()
    const createSecret = vi.fn().mockRejectedValue(new ApiError(409, {
      code: 'secret_env_conflict',
      message: 'the environment name is already registered',
    }))
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-live', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({
        config: { ai: {}, filtering: {} },
        taxonomy: { channels: ['AI'], topics: ['Agent'] },
        env_status: [{ name: 'RSSHUB_ACCESS_KEY', set: true, used_by: ['rsshub.access_key'] }],
      }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      createSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-fetching']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('textbox', { name: 'RSSHub Base URL' })).toBeInTheDocument()
    expect(document.querySelector('[data-settings-page="fetching"]')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'RSSHub Base URL' })).toHaveValue('http://rsshub:1200')
    expect(screen.getByText('访问密钥已配置')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '成员管理' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('live-workbench-shell')).not.toBeInTheDocument()
    expect(document.querySelector('[data-settings-workspace]')).toBeInTheDocument()
    expect(screen.queryByText('精选阈值')).not.toBeInTheDocument()
    expect(screen.queryByText('日报阈值')).not.toBeInTheDocument()
    expect(screen.queryByText('日报条数')).not.toBeInTheDocument()

    await browser.click(screen.getByRole('link', { name: '密钥' }))
    expect(await screen.findByText('新增密钥')).toBeInTheDocument()
    expect(await screen.findByText('尚未配置 Apify Key')).toBeInTheDocument()
    expect(await screen.findByText('尚未配置 AI Key')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '新增 Key' }))
    await browser.type(await screen.findByRole('textbox', { name: 'Key 名称' }), 'DeepSeek')
    await browser.type(screen.getByRole('textbox', { name: 'Key provider' }), 'deepseek')
    await browser.type(screen.getByRole('textbox', { name: '环境变量名' }), 'DEEPSEEK_API_KEY')
    await browser.type(screen.getByLabelText('Key 值'), 'secret-value')
    await browser.click(screen.getByRole('button', { name: '安全保存 Key' }))
    const localFeedback = await screen.findByTestId('secret-form-feedback')
    expect(localFeedback).toHaveTextContent('环境变量名已被其他 Key 使用，请更换后重试。')
    expect(await screen.findByText('新增 Key 失败')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Key 名称' })).toHaveValue('DeepSeek')
    expect(screen.getByRole('textbox', { name: 'Key provider' })).toHaveValue('deepseek')
    expect(screen.getByRole('textbox', { name: '环境变量名' })).toHaveValue('DEEPSEEK_API_KEY')
    expect(screen.getByLabelText('Key 值')).toHaveValue('')
  }, 15_000)

  it('saves the RSS first-fetch window as an explicit 7 or 30 day choice', async () => {
    const browser = userEvent.setup()
    const configAction = vi.fn().mockResolvedValue({ ok: true })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-rss-window', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({
        config: {
          ai: {},
          filtering: {
            time_window_hours: 24,
            rss_initial_fetch_window_hours: 168,
            recent_item_limit: 20,
          },
        },
        taxonomy: { channels: [], topics: [] },
      }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      configAction,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries')
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/legacy#settings-fetching']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('navigation', { name: '设置导航' })).toBeInTheDocument()
    expect(document.querySelector('[data-settings-page="fetching"]')).toBeInTheDocument()

    const initialWindow = await screen.findByRole('button', { name: /RSS 首次抓取窗口/ })
    expect(initialWindow).toHaveTextContent('7 天')
    await browser.click(initialWindow)
    await browser.click(await screen.findByRole('option', { name: '30 天' }))
    expect(await screen.findByText('有尚未保存的更改')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: /RSS 首次抓取窗口/ }))
    await browser.click(await screen.findByRole('option', { name: '7 天' }))
    await waitFor(() => expect(screen.queryByText('有尚未保存的更改')).not.toBeInTheDocument())
    await browser.click(screen.getByRole('button', { name: /RSS 首次抓取窗口/ }))
    await browser.click(await screen.findByRole('option', { name: '30 天' }))
    const rsshub = screen.getByRole('textbox', { name: 'RSSHub Base URL' })
    await browser.clear(rsshub)
    await browser.type(rsshub, 'https://rsshub.example.com/private')
    expect(screen.getByText(/2 项设置待保存/)).toBeInTheDocument()
    const beforeUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)
    await browser.click(screen.getByRole('button', { name: '保存全部配置' }))

    await waitFor(() => expect(configAction).toHaveBeenCalledWith(
      'set_settings_bundle',
      expect.objectContaining({
        filtering: expect.objectContaining({
          time_window_hours: 24,
          feed_window_days: 7,
          rss_initial_fetch_window_hours: 720,
          recent_item_limit: 20,
        }),
        rsshub: { base_url: 'https://rsshub.example.com/private' },
      }),
    ))
    await waitFor(() => expect(screen.queryByText('有尚未保存的更改')).not.toBeInTheDocument())
    for (const key of [
      queryKeys.feedRoot('owner-rss-window'),
      queryKeys.historyRoot('owner-rss-window'),
      queryKeys.searchRoot('owner-rss-window'),
      queryKeys.sourceHealth('owner-rss-window'),
    ]) {
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: key })
    }
  })

  it('shows actionable local validation and network errors inside the key form', async () => {
    const browser = userEvent.setup()
    const createSecret = vi.fn().mockRejectedValue(new Error('Failed to fetch'))
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-key-validation', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      createSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/secrets']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByText('新增密钥')
    await browser.click(screen.getByRole('button', { name: '新增 Key' }))
    await browser.type(await screen.findByRole('textbox', { name: 'Key 名称' }), 'Invalid')
    await browser.type(screen.getByRole('textbox', { name: 'Key provider' }), 'unknown')
    await browser.type(screen.getByRole('textbox', { name: '环境变量名' }), '1INVALID-NAME')
    await browser.type(screen.getByLabelText('Key 值'), 'temporary-value')
    await browser.click(screen.getByRole('button', { name: '安全保存 Key' }))

    expect((await screen.findAllByText('AI Key 的 Provider 仅支持 gemini、openai、anthropic 或 deepseek。')).length).toBeGreaterThan(0)
    expect(screen.getByText('环境变量名必须以字母或下划线开头，且只能包含字母、数字和下划线。')).toBeInTheDocument()
    expect(screen.getByLabelText('Key 值')).toHaveValue('')
    expect(createSecret).not.toHaveBeenCalled()

    await browser.clear(screen.getByRole('textbox', { name: 'Key provider' }))
    await browser.type(screen.getByRole('textbox', { name: 'Key provider' }), 'openai')
    await browser.clear(screen.getByRole('textbox', { name: '环境变量名' }))
    await browser.type(screen.getByRole('textbox', { name: '环境变量名' }), 'OPENAI_API_KEY')
    await browser.type(screen.getByLabelText('Key 值'), 'temporary-value-2')
    await browser.click(screen.getByRole('button', { name: '安全保存 Key' }))

    expect(await screen.findByTestId('secret-form-feedback')).toHaveTextContent('网络请求失败：Failed to fetch。请检查连接后重试。')
    expect(screen.getByRole('textbox', { name: 'Key 名称' })).toHaveValue('Invalid')
    expect(screen.getByRole('textbox', { name: 'Key provider' })).toHaveValue('openai')
    expect(screen.getByRole('textbox', { name: '环境变量名' })).toHaveValue('OPENAI_API_KEY')
    expect(screen.getByLabelText('Key 值')).toHaveValue('')
    expect(createSecret).toHaveBeenCalledTimes(1)
  }, 15_000)

  it('keeps Apify secret maintenance available while pool rollout is disabled', async () => {
    const browser = userEvent.setup()
    const disabledPool = {
      enabled: false,
      generation: 4,
      status: 'ready',
      active_secret_id: 'legacy-primary',
      members: [
        { secret_id: 'legacy-primary', position: 0, status: 'active', blocked_until: null, cycle_end_at: null, last_checked_at: null, last_error_code: null, active_run_count: 1 },
        { secret_id: 'legacy-backup', position: 1, status: 'standby', blocked_until: null, cycle_end_at: null, last_checked_at: null, last_error_code: null, active_run_count: 0 },
      ],
    }
    const reorderApifyKeyPool = vi.fn().mockResolvedValue({
      ...disabledPool,
      generation: 5,
      members: [
        { ...disabledPool.members[1], position: 0 },
        { ...disabledPool.members[0], position: 1 },
      ],
    })
    const rotateSecret = vi.fn().mockResolvedValue({})
    const drainApifyKey = vi.fn()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-rollout-off', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [
        { id: 'legacy-primary', name: 'Legacy Primary', kind: 'apify', provider: 'apify', env_name: 'APIFY_LEGACY_PRIMARY', is_set: true, used_by: [] },
        { id: 'legacy-backup', name: 'Legacy Backup', kind: 'apify', provider: 'apify', env_name: 'APIFY_LEGACY_BACKUP', is_set: true, used_by: [] },
      ] }),
      apifyKeyPool: vi.fn().mockResolvedValue(disabledPool),
      reorderApifyKeyPool,
      drainApifyKey,
      rotateSecret,
      secretQuota: vi.fn().mockResolvedValue({
        secret_id: 'legacy-primary',
        provider: 'apify',
        currency: 'USD',
        cycle_start_at: '2026-07-01T00:00:00.000Z',
        cycle_end_at: '2026-07-31T23:59:59.999Z',
        checked_at: '2026-07-23T08:30:00+00:00',
        monthly_included_credits_usd: 49,
        monthly_usage_usd: 0,
        remaining_included_credits_usd: 49,
        max_monthly_usage_usd: 100,
        remaining_hard_limit_usd: 100,
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/secrets']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('Apify Key 池尚未启用')).toBeInTheDocument()
    const primaryItem = screen.getByText('Legacy Primary').closest<HTMLElement>('[data-settings-item]')!
    await browser.click(within(primaryItem).getByRole('button', { name: /运行详情/ }))
    const rotateTrigger = within(primaryItem).getByRole('button', { name: '轮换 Legacy Primary' })
    expect(rotateTrigger).toBeEnabled()
    expect(within(primaryItem).getByRole('button', { name: '删除 Legacy Primary' })).toBeEnabled()
    expect(within(primaryItem).getByRole('button', { name: '下移 Legacy Primary' })).toBeEnabled()
    expect(within(primaryItem).queryByRole('button', { name: '安全排空 Legacy Primary' })).not.toBeInTheDocument()

    await browser.click(within(primaryItem).getByRole('button', { name: '下移 Legacy Primary' }))
    await waitFor(() => expect(reorderApifyKeyPool).toHaveBeenCalledWith(['legacy-backup', 'legacy-primary'], 4))

    await browser.click(screen.getByRole('button', { name: '轮换 Legacy Primary' }))
    const dialog = screen.getByRole('dialog', { name: '轮换 Legacy Primary' })
    await browser.type(within(dialog).getByLabelText('新 Key 值'), 'legacy-write-only')
    await browser.click(within(dialog).getByRole('button', { name: '确认轮换' }))
    await waitFor(() => expect(rotateSecret).toHaveBeenCalledWith('legacy-primary', 'legacy-write-only'))
    expect(drainApifyKey).not.toHaveBeenCalled()
    expect(document.body.textContent).not.toContain('legacy-write-only')
  }, 10_000)

  it('manages one ordered Apify pool without exposing or mutating an active key', async () => {
    const browser = userEvent.setup()
    const quotaResponse = (secretId: string) => ({
      secret_id: secretId,
      provider: 'apify',
      currency: 'USD',
      cycle_start_at: '2026-07-01T00:00:00.000Z',
      cycle_end_at: '2026-07-31T23:59:59.999Z',
      checked_at: '2026-07-23T08:30:00+00:00',
      monthly_included_credits_usd: 49,
      monthly_usage_usd: 12.5,
      remaining_included_credits_usd: 36.5,
      max_monthly_usage_usd: 100,
      remaining_hard_limit_usd: 87.5,
    })
    const primaryRefresh = deferred<ReturnType<typeof quotaResponse>>()
    let deferPrimaryRefresh = false
    const secretQuota = vi.fn().mockImplementation((secretId: string) => deferPrimaryRefresh && secretId === 'apify-primary'
      ? primaryRefresh.promise
      : Promise.resolve(quotaResponse(secretId)))
    const pool = {
      enabled: true,
      generation: 7,
      status: 'ready',
      active_secret_id: 'apify-primary',
      members: [
        { secret_id: 'apify-primary', position: 0, status: 'active', blocked_until: null, cycle_end_at: '2026-07-31T23:59:59.999Z', last_checked_at: '2026-07-23T08:30:00+00:00', last_error_code: null, active_run_count: 1 },
        { secret_id: 'apify-backup-one', position: 1, status: 'standby', blocked_until: null, cycle_end_at: '2026-07-31T23:59:59.999Z', last_checked_at: '2026-07-23T08:30:00+00:00', last_error_code: null, active_run_count: 0 },
        { secret_id: 'apify-backup-two', position: 2, status: 'standby', blocked_until: null, cycle_end_at: '2026-07-31T23:59:59.999Z', last_checked_at: '2026-07-23T08:30:00+00:00', last_error_code: null, active_run_count: 0 },
      ],
    }
    const reorderedPool = {
      ...pool,
      generation: 8,
      members: [
        pool.members[0],
        { ...pool.members[2], position: 1 },
        { ...pool.members[1], position: 2 },
      ],
    }
    const drainingPool = {
      ...pool,
      generation: 9,
      status: 'draining',
      members: [
        { ...pool.members[0], status: 'draining' },
        pool.members[1],
        pool.members[2],
      ],
    }
    const rotateSecret = vi.fn().mockResolvedValue({})
    const apifyKeyPool = vi.fn().mockResolvedValue(pool)
    const reorderApifyKeyPool = vi.fn().mockResolvedValue(reorderedPool)
    const drainApifyKey = vi.fn().mockResolvedValue(drainingPool)
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-quota', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [
        { id: 'apify-primary', name: 'Apify Primary', kind: 'apify', provider: 'apify', env_name: 'APIFY_PRIMARY', is_set: true, used_by: [{ type: 'source', id: 'source-1', name: 'X' }] },
        { id: 'apify-backup-one', name: 'Apify Backup One', kind: 'apify', provider: 'apify', env_name: 'APIFY_BACKUP_ONE', is_set: true, used_by: [] },
        { id: 'apify-backup-two', name: 'Apify Backup Two', kind: 'apify', provider: 'apify', env_name: 'APIFY_BACKUP_TWO', is_set: true, used_by: [] },
        { id: 'ai-key', name: 'Gemini Primary', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', is_set: true, used_by: [] },
      ] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      secretQuota,
      rotateSecret,
      apifyKeyPool,
      reorderApifyKeyPool,
      drainApifyKey,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const renderSettings = () => render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/settings/secrets']}>
          <DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const firstView = renderSettings()
    expect(await screen.findByText(/当前主用：Apify Primary/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('套餐剩余 $36.50')).toHaveLength(3))
    expect(screen.getAllByText('本月已用 $12.50 · 硬上限剩余 $87.50')).toHaveLength(3)
    expect(new Set(secretQuota.mock.calls.map(([secretId]) => secretId))).toEqual(new Set([
      'apify-primary',
      'apify-backup-one',
      'apify-backup-two',
    ]))
    const primaryItem = screen.getByText('Apify Primary').closest<HTMLElement>('[data-settings-item]')!
    await browser.click(within(primaryItem).getByRole('button', { name: /运行详情/ }))
    expect(within(primaryItem).getByRole('button', { name: '轮换 Apify Primary' })).toBeDisabled()
    expect(within(primaryItem).getByRole('button', { name: '删除 Apify Primary' })).toBeDisabled()
    expect(within(primaryItem).getByRole('button', { name: '下移 Apify Primary' })).toBeDisabled()
    expect(within(primaryItem).getByRole('button', { name: '安全排空 Apify Primary' })).toBeEnabled()

    firstView.unmount()
    renderSettings()
    expect((await screen.findAllByText('套餐剩余 $36.50')).length).toBe(3)
    expect(secretQuota).toHaveBeenCalledTimes(3)
    const refreshedPrimaryItem = screen.getByText('Apify Primary').closest<HTMLElement>('[data-settings-item]')!
    await browser.click(within(refreshedPrimaryItem).getByRole('button', { name: /运行详情/ }))

    deferPrimaryRefresh = true
    await browser.click(screen.getByRole('button', { name: '刷新 Apify Primary 额度' }))
    await waitFor(() => expect(secretQuota).toHaveBeenCalledTimes(4))
    const refreshingQuota = screen.getByRole('button', { name: '正在刷新 Apify Primary 额度' })
    expect(refreshingQuota).toBeDisabled()
    expect(refreshingQuota.closest('[aria-busy]')).toHaveAttribute('aria-busy', 'true')
    expect(refreshingQuota.querySelector('svg')).toHaveClass('animate-spin', 'motion-reduce:animate-none')
    expect(within(screen.getByText('Apify Primary').closest<HTMLElement>('[data-settings-item]')!).getByText('套餐剩余 $36.50')).toBeInTheDocument()
    await act(async () => primaryRefresh.resolve(quotaResponse('apify-primary')))
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新 Apify Primary 额度' })).toBeEnabled())

    const firstBackupItem = screen.getByText('Apify Backup One').closest<HTMLElement>('[data-settings-item]')!
    expect(within(firstBackupItem).getByRole('button', { name: '上移 Apify Backup One' })).toBeDisabled()
    await browser.click(within(firstBackupItem).getByRole('button', { name: '下移 Apify Backup One' }))
    await waitFor(() => expect(reorderApifyKeyPool).toHaveBeenCalledWith(
      ['apify-primary', 'apify-backup-two', 'apify-backup-one'],
      7,
    ))

    const secondBackupItem = screen.getByText('Apify Backup Two').closest<HTMLElement>('[data-settings-item]')!
    await browser.click(within(secondBackupItem).getByRole('button', { name: /运行详情/ }))
    const rotateTrigger = within(secondBackupItem).getByRole('button', { name: '轮换 Apify Backup Two' })
    await browser.click(rotateTrigger)
    const rotateDialog = screen.getByRole('dialog', { name: '轮换 Apify Backup Two' })
    await browser.type(within(rotateDialog).getByLabelText('新 Key 值'), 'rotated-write-only')
    await browser.click(within(rotateDialog).getByRole('button', { name: '确认轮换' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '轮换 Apify Backup Two' })).not.toBeInTheDocument())
    await waitFor(() => expect(secretQuota.mock.calls.filter(([secretId]) => secretId === 'apify-backup-two')).toHaveLength(2))
    expect(rotateSecret).toHaveBeenCalledWith('apify-backup-two', 'rotated-write-only')
    expect(rotateTrigger).toHaveFocus()

    await browser.click(within(screen.getByText('Apify Primary').closest<HTMLElement>('[data-settings-item]')!).getByRole('button', { name: '安全排空 Apify Primary' }))
    await waitFor(() => expect(drainApifyKey).toHaveBeenCalledWith('apify-primary'))
    expect(await screen.findByText('正在安全排空')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('rotated-write-only')
  }, 10_000)

  it('announces deferred Apify quota retries and preserves the last trusted quota after refresh failure', async () => {
    const browser = userEvent.setup()
    const retryQuota = deferred<{
      secret_id: string
      provider: string
      currency: string
      cycle_start_at: string
      cycle_end_at: string
      checked_at: string
      monthly_included_credits_usd: number
      monthly_usage_usd: number
      remaining_included_credits_usd: number
      max_monthly_usage_usd: number
      remaining_hard_limit_usd: number
    }>()
    const backgroundRetryQuota = deferred<Awaited<typeof retryQuota.promise>>()
    const invalidationRetryQuota = deferred<Awaited<typeof retryQuota.promise>>()
    const secretQuota = vi.fn()
      .mockRejectedValueOnce(new Error('Apify 暂时不可用'))
      .mockImplementationOnce(() => retryQuota.promise)
      .mockRejectedValueOnce(new Error('Apify 刷新暂时不可用'))
      .mockImplementationOnce(() => backgroundRetryQuota.promise)
      .mockRejectedValueOnce(new Error('Apify 再次刷新失败'))
      .mockImplementationOnce(() => invalidationRetryQuota.promise)
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-quota-retry', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [
        { id: 'apify-retry', name: 'Apify Retry', kind: 'apify', provider: 'apify', env_name: 'APIFY_RETRY', is_set: true, used_by: [] },
      ] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      secretQuota,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/secrets']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    const retry = await screen.findByRole('button', { name: '重试 Apify Retry 额度' })
    await browser.click(retry)

    await waitFor(() => expect(secretQuota).toHaveBeenCalledTimes(2))

    await act(async () => retryQuota.resolve({
      secret_id: 'apify-retry',
      provider: 'apify',
      currency: 'USD',
      cycle_start_at: '2026-07-01T00:00:00.000Z',
      cycle_end_at: '2026-07-31T23:59:59.999Z',
      checked_at: '2026-07-24T08:30:00+00:00',
      monthly_included_credits_usd: 5,
      monthly_usage_usd: 1,
      remaining_included_credits_usd: 4,
      max_monthly_usage_usd: 10,
      remaining_hard_limit_usd: 9,
    }))
    expect(await screen.findByText('套餐剩余 $4.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新 Apify Retry 额度' })).toBeEnabled()

    await browser.click(screen.getByRole('button', { name: '刷新 Apify Retry 额度' }))
    const backgroundRetry = await screen.findByRole('button', { name: '重试 Apify Retry 额度' })
    expect(screen.getByText('套餐剩余 $4.00')).toBeInTheDocument()
    expect(screen.getByText('Apify 刷新暂时不可用')).toHaveAttribute('role', 'alert')

    await browser.click(backgroundRetry)
    await waitFor(() => expect(secretQuota).toHaveBeenCalledTimes(4))
    expect(screen.getByText('套餐剩余 $4.00')).toBeInTheDocument()

    await act(async () => backgroundRetryQuota.resolve({
      secret_id: 'apify-retry',
      provider: 'apify',
      currency: 'USD',
      cycle_start_at: '2026-07-01T00:00:00.000Z',
      cycle_end_at: '2026-07-31T23:59:59.999Z',
      checked_at: '2026-07-24T08:35:00+00:00',
      monthly_included_credits_usd: 5,
      monthly_usage_usd: 2,
      remaining_included_credits_usd: 3,
      max_monthly_usage_usd: 10,
      remaining_hard_limit_usd: 8,
    }))
    expect(await screen.findByText('套餐剩余 $3.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新 Apify Retry 额度' })).toBeEnabled()

    await browser.click(screen.getByRole('button', { name: '刷新 Apify Retry 额度' }))
    expect(await screen.findByRole('button', { name: '重试 Apify Retry 额度' })).toBeEnabled()
    act(() => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.secretQuota('owner-quota-retry', 'apify-retry'),
      })
    })
    await waitFor(() => expect(secretQuota).toHaveBeenCalledTimes(6))
    expect(screen.getByText('套餐剩余 $3.00')).toBeInTheDocument()

    await act(async () => invalidationRetryQuota.resolve({
      secret_id: 'apify-retry',
      provider: 'apify',
      currency: 'USD',
      cycle_start_at: '2026-07-01T00:00:00.000Z',
      cycle_end_at: '2026-07-31T23:59:59.999Z',
      checked_at: '2026-07-24T08:40:00+00:00',
      monthly_included_credits_usd: 5,
      monthly_usage_usd: 3,
      remaining_included_credits_usd: 2,
      max_monthly_usage_usd: 10,
      remaining_hard_limit_usd: 7,
    }))
    expect(await screen.findByText('套餐剩余 $2.00')).toBeInTheDocument()
  })

  it('keeps rotation failures inside the row modal and clears the submitted value', async () => {
    const browser = userEvent.setup()
    const rotateSecret = vi.fn().mockRejectedValue(new ApiError(422, {
      code: 'invalid_secret',
      message: 'secret value must be a single non-null line',
    }))
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-rotate-failure', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      secrets: vi.fn().mockResolvedValue({ secrets: [{ id: 'rotate-key', name: 'Rotate Key', kind: 'ai', provider: 'openai', env_name: 'ROTATE_KEY', is_set: true, used_by: [] }] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      rotateSecret,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings/secrets']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const item = (await screen.findByText('Rotate Key')).closest<HTMLElement>('[data-settings-item]')!
    const trigger = within(item).getByRole('button', { name: '轮换 Rotate Key' })
    await browser.click(trigger)
    const dialog = screen.getByRole('dialog', { name: '轮换 Rotate Key' })
    const input = within(dialog).getByLabelText('新 Key 值')
    await browser.type(input, 'bad-value')
    await browser.click(within(dialog).getByRole('button', { name: '确认轮换' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('secret value must be a single non-null line')
    expect(input).toHaveValue('')
    expect(dialog).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '轮换 Rotate Key' })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-secrets']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const item = (await screen.findByText('Unused Key')).closest<HTMLElement>('[data-settings-item]')!
    const trigger = within(item).getByRole('button', { name: '删除 Unused Key' })
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-secrets']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    const item = (await screen.findByText('Failed Key')).closest<HTMLElement>('[data-settings-item]')!
    await browser.click(within(item).getByRole('button', { name: '删除 Failed Key' }))
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
    expect(screen.getByRole('button', { name: '切换到白天模式' })).toBeInTheDocument()
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

    await browser.click(await screen.findByRole('button', { name: '编辑来源：Advanced RSS' }))
    const dialog = await screen.findByRole('dialog', { name: 'Advanced RSS · 来源设置' })
    expect(within(dialog).getByText('高级配置')).toBeVisible()
    expect(dialog.querySelector('details')).not.toBeInTheDocument()
  })

  it('surfaces a source capability catalog failure and supports a local retry', async () => {
    const browser = userEvent.setup()
    const sourceCapabilities = vi.fn()
      .mockRejectedValueOnce(new Error('capability catalog unavailable'))
      .mockResolvedValue({
        schema_version: 1,
        generation: 2,
        support_profiles: actorSupportProfiles,
        capabilities: [],
      })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({
        source_types: [{ type: 'rss', label: 'RSS / Atom', fields: [] }],
      }),
      sourceCapabilities,
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 },
        items: [],
      }),
      config: vi.fn().mockResolvedValue({
        config: {},
        taxonomy: { channels: [], topics: [] },
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(<QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/subscriptions']}>
        <AppRoutes api={api} />
      </MemoryRouter>
    </QueryClientProvider>)

    expect(await screen.findByText(
      'Actor Route 能力目录读取失败，付费来源创建已暂时隐藏。',
    )).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '重试能力目录' }))
    await waitFor(() => expect(sourceCapabilities).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByText(
      'Actor Route 能力目录读取失败，付费来源创建已暂时隐藏。',
    )).not.toBeInTheDocument())
  })

  it('lets a member submit an Actor support check from the source dialog', async () => {
    const browser = userEvent.setup()
    const requestApifyActorSupportCheck = vi.fn().mockResolvedValue({
      schema_version: 1,
      kind: 'discovery',
      generation: 4,
      route_generation: 1,
      route_id: 'route-instagram',
      support_status: 'pending',
      discovery_run_id: 'discovery-instagram',
      job: null,
    })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({
        authenticated: true,
        user: {
          id: 'member-actor-support',
          username: 'member',
          role: 'member',
          enabled: true,
        },
      }),
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({
        source_types: [{ type: 'rss', label: 'RSS / Atom', fields: [] }],
      }),
      sourceCapabilities: vi.fn().mockResolvedValue({
        schema_version: 1,
        generation: 23,
        support_profiles: actorSupportProfiles,
        capabilities: [],
      }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: {
          healthy: 0,
          degraded: 0,
          failing: 0,
          unknown: 0,
          total: 0,
        },
        items: [],
      }),
      config: vi.fn().mockResolvedValue({
        config: {},
        taxonomy: { channels: [], topics: [] },
      }),
      requestApifyActorSupportCheck,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    render(<QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/subscriptions']}>
        <AppRoutes api={api} />
      </MemoryRouter>
    </QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '新增来源' }))
    const dialog = screen.getByRole('dialog', { name: '新增来源' })
    await browser.click(within(dialog).getByRole('button', { name: /待检查 Profile/ }))
    await browser.click(await screen.findByRole('option', { name: /Instagram Profile/ }))
    await browser.click(within(dialog).getByRole('button', { name: '请求支持检查' }))

    await waitFor(() => expect(requestApifyActorSupportCheck).toHaveBeenCalledWith({
      platform: 'instagram',
      target_type: 'profile',
      capability: 'items',
      expected_generation: 23,
    }))
  })

  it('loads admin secrets only inside a source-secret dialog and keeps loading errors local', async () => {
    const browser = userEvent.setup()
    const firstSecretsRequest = deferred<{ secrets: [] }>()
    const secrets = vi.fn()
      .mockReturnValueOnce(firstSecretsRequest.promise)
      .mockResolvedValue({ secrets: [] })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({
        authenticated: true,
        user: { id: 'owner-source-secrets', username: 'owner', role: 'owner', enabled: true },
      }),
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [
        { type: 'rss', label: 'RSS / Atom', fields: [] },
        { type: 'apify_social', label: 'Apify 社交来源', credential_mode: 'source_secret', fields: [] },
      ] }),
      sourceCapabilities: vi.fn().mockResolvedValue({
        schema_version: 1,
        generation: 7,
        support_profiles: actorSupportProfiles,
        capabilities: [{
          profile_id: 'route-instagram-profile',
          platform: 'instagram',
          target_type: 'profile',
          capability: 'items',
          mode: 'primary',
          generation: 7,
          storage_type: 'apify_social',
          fields: [
            { name: 'profile_id', input_type: 'select', required: true },
            { name: 'target', input_type: 'text', required: true },
          ],
        }],
      }),
      sourceHealth: vi.fn().mockResolvedValue({
        schema_version: 1,
        scope: 'user',
        summary: { healthy: 0, degraded: 0, failing: 0, unknown: 0, total: 0 },
        items: [],
      }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: [], topics: [] } }),
      secrets,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '订阅与来源' })
    expect(secrets).not.toHaveBeenCalled()
    await browser.click(await screen.findByRole('button', { name: '新增来源' }))
    expect(secrets).not.toHaveBeenCalled()

    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: 'RSS / Atom' }))
    expect(await screen.findByRole('textbox', { name: '来源名称' })).toBeInTheDocument()
    expect(secrets).not.toHaveBeenCalled()

    await browser.click(screen.getByRole('button', { name: /来源类型/ }))
    await browser.click(await screen.findByRole('option', { name: 'Apify 社交来源' }))
    expect(await screen.findByRole('status', { name: '正在读取可用 Key' })).toBeInTheDocument()
    expect(secrets).toHaveBeenCalledOnce()
    expect(screen.queryByRole('textbox', { name: '来源名称' })).not.toBeInTheDocument()

    act(() => firstSecretsRequest.reject(new Error('secret registry unavailable')))
    expect(await screen.findByText('可用 Key 读取失败')).toBeInTheDocument()
    const dialog = screen.getByRole('dialog', { name: '新增来源' })
    await browser.click(within(dialog).getByRole('button', { name: '重试' }))
    expect(await within(dialog).findByRole('textbox', { name: '来源名称' })).toBeInTheDocument()
    expect(secrets).toHaveBeenCalledTimes(2)
  })

  it('blocks incomplete required Apify options and submits their real registry metadata after selection', async () => {
    const browser = userEvent.setup()
    const createSource = vi.fn().mockResolvedValue({ id: 'apify-new' })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{
        type: 'apify_social', label: 'Apify 社交来源', fields: [
          { name: 'profile_id', label: 'Actor Route', input_type: 'text', required: false, default: '' },
          { name: 'platform', label: '平台', input_type: 'select', required: true, default: '', options: [{ value: 'x', label: 'X' }] },
          { name: 'kind', label: '来源类别', input_type: 'select', required: true, default: '', options: [{ value: 'profile', label: '账号' }] },
          { name: 'target', label: '目标', input_type: 'text', required: true, default: '', help: '输入公开账号。' },
        ],
      }] }),
      sourceCapabilities: vi.fn().mockResolvedValue({
        schema_version: 1,
        generation: 11,
        support_profiles: actorSupportProfiles,
        capabilities: [{
          profile_id: 'route-x-profile',
          platform: 'x',
          target_type: 'profile',
          capability: 'items',
          mode: 'primary',
          generation: 11,
          storage_type: 'apify_social',
          fields: [
            { name: 'profile_id', input_type: 'select', required: true },
            { name: 'target', input_type: 'text', required: true },
          ],
        }],
      }),
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
    const routeControl = screen.getByLabelText('Actor Route')
    const targetControl = screen.getByLabelText('目标')
    expect(routeControl.parentElement).toHaveAttribute('data-required', 'true')
    expect(targetControl).toBeRequired()
    expect(routeControl).toHaveTextContent('X · profile · items')
    expect(screen.queryByLabelText('平台')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('来源类别')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(createSource).not.toHaveBeenCalled()
    expect(await screen.findByText('目标不能为空。')).toBeInTheDocument()

    await browser.type(targetControl, 'openai')
    expect(screen.queryByText('目标不能为空。')).not.toBeInTheDocument()
    const sourceForm = screen.getByRole('button', { name: '创建并订阅' }).closest('form') as HTMLFormElement
    expect(Array.from(sourceForm.elements).filter((element): element is HTMLInputElement => element instanceof HTMLInputElement && !element.validity.valid).map((element) => ({ name: element.name, value: element.value, required: element.required, validity: element.validity.valid }))).toEqual([])
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    await waitFor(() => expect(createSource).toHaveBeenCalledWith(expect.objectContaining({
      config: {
        profile_id: 'route-x-profile',
        target: 'openai',
      },
    })))
    expect(api.subscribe).toHaveBeenCalledWith('apify-new')
  })

  it('omits source usage lookup and confirms management transfer before sharing', async () => {
    const browser = userEvent.setup()
    const source = { id: 'private-share-source', type: 'rss', display_name: '私人研究源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'private-share-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true }
    const sourceUsage = vi.fn().mockResolvedValue({ source_id: source.id, subscriber_count: 3, enabled_subscriber_count: 2 })
    const shareSource = vi.fn().mockResolvedValue({
      source: { ...source, scope: 'public', owner_user_id: null },
      notice: '管理权已交给工作区管理员。',
    })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      sourceUsage,
      shareSource,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(screen.queryByRole('button', { name: '查看 私人研究源 引用人数' })).not.toBeInTheDocument()
    expect(sourceUsage).not.toHaveBeenCalled()
    await browser.click(await screen.findByRole('button', { name: '分享来源：私人研究源' }))
    const shareDialog = await screen.findByRole('dialog', { name: '分享 私人研究源' })
    expect(within(shareDialog).getByText('分享后管理权将发生变化')).toBeInTheDocument()
    expect(within(shareDialog).getByText(/取消订阅只影响自己/)).toBeInTheDocument()
    await browser.click(within(shareDialog).getByRole('button', { name: '确认公开并转交管理权' }))
    await waitFor(() => expect(shareSource).toHaveBeenCalledWith(source.id, 'public'))
  })

  it('requires an explicit disposition when disabling a personal subscription', async () => {
    const browser = userEvent.setup()
    const source = { id: 'disable-source', type: 'rss', display_name: '可停用来源', scope: 'private' as const, owner_user_id: 'user-live', default_channel: 'AI', enabled: true }
    const subscription = { id: 'disable-sub', user_id: 'user-live', source_id: source.id, source_display_name: source.display_name, source_type: source.type, enabled: true, schedule: { enabled: false, interval_minutes: 360 } }
    const updateSubscription = vi.fn().mockResolvedValue({ ...subscription, enabled: false })
    const updateSourceSchedule = vi.fn().mockResolvedValue({ enabled: false, interval_minutes: 360, worker_status: 'ready' })
    const api = liveApi({
      sources: vi.fn().mockResolvedValue({ sources: [source] }),
      subscriptions: vi.fn().mockResolvedValue({ subscriptions: [subscription] }),
      sourceTypes: vi.fn().mockResolvedValue({ source_types: [{ type: 'rss', fields: [] }] }),
      sourceHealth: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', summary: { healthy: 0, degraded: 0, failing: 0, unknown: 1, total: 1 }, items: [] }),
      config: vi.fn().mockResolvedValue({ config: {}, taxonomy: { channels: ['AI'], topics: [] } }),
      updateSubscription,
      updateSourceSchedule,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/subscriptions']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '配置 可停用来源 订阅' }))
    const dialog = await screen.findByRole('dialog', { name: '可停用来源 · 订阅设置' })
    await browser.click(within(dialog).getByRole('checkbox', { name: '启用订阅' }))
    await browser.click(within(dialog).getByRole('button', { name: /关闭后如何处理已有内容/ }))
    await browser.click(await screen.findByRole('option', { name: '加入收藏后从信息流移除' }))
    await browser.click(within(dialog).getByRole('button', { name: '保存' }))

    await waitFor(() => expect(updateSubscription).toHaveBeenCalledWith(subscription.id, expect.objectContaining({ enabled: false, on_disable: 'save' })))
    expect(updateSubscription.mock.calls[0]?.[1]).not.toHaveProperty('notify_on_new_items')
    expect(within(dialog).queryByRole('switch', { name: /新内容通知/ })).not.toBeInTheDocument()
    expect(updateSourceSchedule).toHaveBeenCalledWith(subscription.id, expect.objectContaining({ enabled: false }))
  })

  it('restores ignored content only from settings', async () => {
    const browser = userEvent.setup()
    const updateItemState = vi.fn().mockResolvedValue({ dismissed: false })
    const api = liveApi({
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }),
      ignoredFeed: vi.fn().mockResolvedValue({ items: [{ id: 'ignored-item', title: '被忽略的条目', source: '测试来源' }], pagination: { limit: 200, offset: 0, count: 1, total: 1 } }),
      updateItemState,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-ignored']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('被忽略的条目')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '恢复' }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledWith('ignored-item', { dismissed: false }))
  })

  it('lets every signed-in user change their own password without exposing member administration', async () => {
    const browser = userEvent.setup()
    const changePassword = vi.fn().mockResolvedValue({ changed: true })
    const api = liveApi({ changePassword } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/users']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '账户安全' })
    expect(screen.queryByRole('heading', { name: '成员管理' })).not.toBeInTheDocument()
    await browser.type(screen.getByLabelText('当前密码'), 'current-secret')
    await browser.type(screen.getByLabelText('新密码'), 'new-secret-value')
    await browser.type(screen.getByLabelText('确认新密码'), 'new-secret-value')
    await browser.click(screen.getByRole('button', { name: '更新密码' }))
    await waitFor(() => expect(changePassword).toHaveBeenCalledWith('current-secret', 'new-secret-value'))
    expect(screen.getByLabelText('当前密码')).toHaveValue('')
    expect(screen.getByLabelText('新密码')).toHaveValue('')
  })

  it('keeps member-create correction feedback in its form while global failure uses a toast', async () => {
    const browser = userEvent.setup()
    const createUser = vi.fn().mockRejectedValue(new ApiError(409, {
      code: 'username_conflict',
      message: '用户名已存在',
    }))
    const owner = { id: 'owner-users', username: 'owner', role: 'owner' as const, enabled: true }
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: owner }),
      users: vi.fn().mockResolvedValue({ users: [owner] }),
      createUser,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/users']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '成员管理' })
    await browser.type(screen.getByRole('textbox', { name: '用户名' }), 'duplicate')
    await browser.type(screen.getByLabelText('初始密码'), 'initial-secret')
    await browser.click(screen.getByRole('button', { name: '新增成员' }))

    await waitFor(() => expect(createUser).toHaveBeenCalledOnce())
    const messages = await screen.findAllByText('用户名已存在')
    expect(messages.some((message) => message.closest('form'))).toBe(true)
    expect(messages.some((message) => message.closest('[data-slot="toast-region"]'))).toBe(true)
    expect(document.querySelector('[data-page-frame="admin"]')?.querySelector(':scope > [role="alert"]')).toBeNull()
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

    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(await screen.findByText('来源名称不能为空。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.type(screen.getByRole('textbox', { name: '来源名称' }), '受限订阅')
    await browser.type(screen.getByRole('textbox', { name: 'RSS 地址' }), 'not-a-url')
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(await screen.findByText('RSS 地址必须是有效 URL。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    const url = screen.getByRole('textbox', { name: 'RSS 地址' })
    const limit = screen.getByRole('spinbutton', { name: '获取数量' })
    await browser.clear(url)
    await browser.type(url, 'https://example.com/feed.xml')
    await browser.clear(limit)
    await browser.type(limit, '11')
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(await screen.findByText('获取数量不能大于 10。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    await browser.type(limit, '0')
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(await screen.findByText('获取数量不能小于 1。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    await browser.type(limit, '1.5')
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(await screen.findByText('获取数量必须是整数。')).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    fireEvent.input(limit, { target: { value: 'NaN' } })
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
    expect(await screen.findByText(/获取数量(不能为空|必须是有效数字)。/)).toBeInTheDocument()
    expect(createSource).not.toHaveBeenCalled()

    await browser.clear(limit)
    await browser.type(limit, '4')
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))
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
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))

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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-ai']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '工作区 AI' })
    await browser.click(await screen.findByRole('button', { name: /Provider/ }))
    await browser.click(await screen.findByRole('option', { name: 'DeepSeek' }))
    expect(screen.getByRole('textbox', { name: '模型' })).toHaveValue('deepseek-v4-flash')
    expect(screen.getByLabelText('AI Key')).toHaveTextContent('DeepSeek Key')
    await browser.click(screen.getByRole('button', { name: '保存 AI 设置' }))
    expect(configAction).toHaveBeenCalledWith('set_settings_bundle', {
      ai: expect.objectContaining({ provider: 'deepseek', model: 'deepseek-v4-flash', api_key_env: 'DEEPSEEK_API_KEY' }),
    })
  })

  it('saves feed-end copy settings and exposes generation status with a queued refresh', async () => {
    const browser = userEvent.setup()
    const configAction = vi.fn().mockResolvedValue({ config: { feed_end_messages: {} } })
    const refreshFeedEndMessages = vi.fn().mockResolvedValue({
      schema_version: 1,
      source: 'ai',
      status: 'pending',
      generation: 4,
      generated_at: '2026-07-29T00:00:00Z',
      last_attempt_at: '2026-07-29T00:00:00Z',
      next_refresh_at: '2026-08-05T00:00:00Z',
      retry_at: null,
      last_error_code: null,
      scenes: {
        empty: ['空列表样例。'],
        first_end: ['首次触底样例。'],
        repeat_end: ['再次触底样例。'],
      },
    })
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'owner-copy', username: 'owner', role: 'owner', enabled: true } }),
      config: vi.fn().mockResolvedValue({
        config: {
          ai: { enabled: true, provider: 'openai', model: 'gpt-4o-mini', api_key_env: 'OPENAI_API_KEY' },
          feed_end_messages: {
            ai_generation_enabled: true,
            refresh_days: 7,
            style_preset: 'restrained',
            style_prompt: '',
            list_count: 12,
          },
          filtering: {},
        },
        taxonomy: { channels: [], topics: [] },
      }),
      secrets: vi.fn().mockResolvedValue({ secrets: [] }),
      users: vi.fn().mockResolvedValue({ users: [] }),
      feedEndMessages: vi.fn().mockResolvedValue({
        schema_version: 1,
        source: 'ai',
        status: 'ready',
        generation: 4,
        generated_at: '2026-07-29T00:00:00Z',
        last_attempt_at: '2026-07-29T00:00:00Z',
        next_refresh_at: '2026-08-05T00:00:00Z',
        retry_at: null,
        last_error_code: null,
        scenes: {
          empty: ['空列表样例一。', '空列表样例二。', '空列表样例三。', '空列表完整列表第四条。'],
          first_end: ['首次触底样例。'],
          repeat_end: ['再次触底样例。'],
        },
      }),
      configAction,
      refreshFeedEndMessages,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/settings#settings-ai']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('AI 文案可用')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '空列表完整文案列表' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '展开空列表完整文案列表' }))
    const emptyMessageList = screen.getByRole('list', { name: '空列表完整文案列表' })
    expect(within(emptyMessageList).getAllByRole('listitem')).toHaveLength(4)
    expect(within(emptyMessageList).getByText('空列表完整列表第四条。')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '隐藏空列表完整文案列表' }))
    expect(screen.queryByRole('list', { name: '空列表完整文案列表' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '展开首次触底完整文案列表' }))
    expect(within(screen.getByRole('list', { name: '首次触底完整文案列表' })).getByText('首次触底样例。')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '展开多次触底完整文案列表' }))
    expect(within(screen.getByRole('list', { name: '多次触底完整文案列表' })).getByText('再次触底样例。')).toBeInTheDocument()
    await browser.type(screen.getByRole('textbox', { name: '自定义风格补充' }), '更像编辑部')
    await browser.click(screen.getByRole('button', { name: '保存触底文案设置' }))
    expect(configAction).toHaveBeenCalledWith('set_settings_bundle', {
      feed_end_messages: {
        ai_generation_enabled: true,
        refresh_days: 7,
        style_preset: 'restrained',
        style_prompt: '更像编辑部',
        list_count: 12,
      },
    })

    await browser.click(screen.getByRole('button', { name: '立即刷新' }))
    expect(refreshFeedEndMessages).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('等待 Worker 刷新')).toBeInTheDocument()
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
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/users']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '成员管理' })
    await screen.findByText('Workspace Owner')
    const memberGrid = screen.getByRole('grid', { name: '成员列表' })
    expect(memberGrid).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map((column) => column.textContent)).toEqual(['成员', '角色', '账户状态', '操作'])
    expect(within(memberGrid).getAllByRole('row')[1]).toHaveTextContent('Editable Member')
    await browser.click(within(memberGrid).getByRole('columnheader', { name: '成员' }))
    await waitFor(() => expect(within(memberGrid).getAllByRole('row')[1]).toHaveTextContent('Workspace Owner'))
    expect(screen.queryByRole('button', { name: /角色 workspace-owner/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '切换 workspace-owner 状态' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: /角色 editable/ }))
    await browser.click(await screen.findByRole('option', { name: '只读成员' }))
    expect(updateUser).toHaveBeenCalledWith('editable-member', { role: 'viewer' })
    expect(screen.getByRole('button', { name: '切换 editable 状态' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重置 editable 密码' })).toHaveTextContent('')
  })

  it('resets a non-owner member password from the table after local validation', async () => {
    const browser = userEvent.setup()
    const workspaceOwner = { id: 'workspace-owner', username: 'workspace-owner', display_name: 'Workspace Owner', role: 'owner' as const, enabled: true }
    const editableMember = { id: 'editable-member', username: 'editable', display_name: 'Editable Member', role: 'member' as const, enabled: true }
    const updateUser = vi.fn().mockResolvedValue(editableMember)
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'actor-owner', username: 'owner', role: 'owner', enabled: true } }),
      users: vi.fn().mockResolvedValue({ users: [workspaceOwner, editableMember] }),
      updateUser,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/users']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await browser.click(await screen.findByRole('button', { name: '重置 editable 密码' }))
    const dialog = screen.getByRole('dialog', { name: '重置成员密码' })
    await browser.type(within(dialog).getByLabelText('新密码'), 'short')
    await browser.type(within(dialog).getByLabelText('确认新密码'), 'different')
    await browser.click(within(dialog).getByRole('button', { name: '确认重置' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('至少需要 8 个字符')
    expect(updateUser).not.toHaveBeenCalled()

    await browser.clear(within(dialog).getByLabelText('新密码'))
    await browser.clear(within(dialog).getByLabelText('确认新密码'))
    await browser.type(within(dialog).getByLabelText('新密码'), 'new-password')
    await browser.type(within(dialog).getByLabelText('确认新密码'), 'new-password')
    await browser.click(within(dialog).getByRole('button', { name: '确认重置' }))
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('editable-member', { password: 'new-password' }))
    expect(screen.queryByRole('dialog', { name: '重置成员密码' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重置 workspace-owner 密码' })).not.toBeInTheDocument()
  })

  it.each(['member', 'viewer'] as const)('does not expose live member administration controls to a %s', async (actorRole) => {
    const users = vi.fn()
    const api = liveApi({
      authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: `actor-${actorRole}`, username: actorRole, role: actorRole, enabled: true } }),
      config: vi.fn().mockResolvedValue({ config: { ai: {}, filtering: {} }, taxonomy: { channels: [], topics: [] } }), users,
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/users']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    await screen.findByRole('heading', { name: '账户安全' })
    expect(screen.queryByRole('heading', { name: '成员管理' })).not.toBeInTheDocument()
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
    expect(document.querySelector('[data-agent-panel-skeleton]')).toBeInTheDocument()
    expect(document.querySelectorAll('[data-agent-skeleton-block]')).toHaveLength(3)
    expect(document.querySelectorAll('[data-agent-panel-skeleton] .inteliscope-skeleton-calm')).not.toHaveLength(0)
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
    expect(screen.getByText('OpenClaw 对话')).toBeInTheDocument()
    expect(screen.getByText('未配置')).toBeInTheDocument()
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

  it('removes a proven-stale 404 deep link and falls back to top-first Feed positioning', async () => {
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
      expect(screen.getByTestId('workbench-feed-scroll').scrollTop).toBe(0)
      expect(scrollTo.mock.calls.some(([options]) => Number((options as ScrollToOptions).top) > 0)).toBe(false)
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
    expect(savedFeed).toHaveBeenCalledWith(50, 0, expect.any(AbortSignal))
    expect(latestFeed).not.toHaveBeenCalled()
  })

  it('shows only the lightweight empty message for an empty saved collection', async () => {
    const savedFeed = vi.fn().mockResolvedValue({
      schema_version: 1,
      scope: 'user',
      items: [],
      item_count: 0,
      limit: 50,
      offset: 0,
    })
    const api = liveApi({
      savedFeed,
      feedEndMessages: vi.fn().mockResolvedValue({
        schema_version: 1,
        source: 'builtin',
        status: 'disabled',
        generation: 0,
        generated_at: null,
        last_attempt_at: null,
        next_refresh_at: null,
        retry_at: null,
        last_error_code: null,
        scenes: {
          empty: ['这里暂时很安静。🌿'],
          first_end: ['这一轮先读到这里。☕'],
          repeat_end: ['又到末尾了。^_^'],
        },
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/saved']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByTestId('feed-empty-message')).toHaveTextContent('这里暂时很安静。🌿')
    expect(screen.queryByText('还没有收藏')).not.toBeInTheDocument()
    expect(screen.queryByText('在信息流中收藏的内容会出现在这里。')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '返回信息流' })).not.toBeInTheDocument()
  })

  it('keeps saved pagination explicit and shows the terminal only on the true final page', async () => {
    const browser = userEvent.setup()
    const savedItems = Array.from({ length: 51 }, (_, index) => ({
      ...basicFeedItem(`saved-page-${index}`, `分页收藏 ${index}`),
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    }))
    const savedFeed = vi.fn().mockImplementation(async (limit: number, offset: number) => ({
      schema_version: 1,
      scope: 'user',
      items: savedItems.slice(offset, offset + limit),
      item_count: savedItems.length,
      limit,
      offset,
    }))
    const api = liveApi({ savedFeed } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/saved']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('button', { name: '加载更多（已显示 50/51）' })).toBeInTheDocument()
    expect(screen.queryByText('收藏已全部显示')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '加载更多（已显示 50/51）' }))

    expect(await screen.findByText('收藏已全部显示')).toBeInTheDocument()
    const terminalMessage = screen.getByTestId('feed-end-message')
    expect(within(terminalMessage).getByText('收藏已全部显示')).toHaveClass('sr-only')
    expect(terminalMessage).toHaveTextContent('·')
    expect(terminalMessage).not.toHaveClass('card', 'rounded-xl', 'border', 'bg-surface-secondary')
    expect(savedFeed).toHaveBeenLastCalledWith(50, 50, expect.any(AbortSignal))
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
    expect(historyFeed).toHaveBeenCalledWith({
      q: undefined,
      sourceId: undefined,
      limit: 50,
      offset: 0,
    }, expect.any(AbortSignal))
    expect(latestFeed).not.toHaveBeenCalled()
  })

  it('loads durable history pages from a source deep link and keeps the source filter visible', async () => {
    const browser = userEvent.setup()
    const firstItem = basicFeedItem('history-source-first', 'tsucha 历史一')
    const secondItem = basicFeedItem('history-source-second', 'tsucha 历史二')
    const historyFeed = vi.fn().mockImplementation(async (params: { offset?: number }) => params.offset === 0
      ? {
        schema_version: 2,
        scope: 'user',
        items: [firstItem],
        featured_items: [],
        item_count: 1,
        total_count: 2,
        limit: 50,
        offset: 0,
        has_more: true,
        snapshots: [],
      }
      : {
        schema_version: 2,
        scope: 'user',
        items: [firstItem, secondItem],
        featured_items: [],
        item_count: 2,
        total_count: 2,
        limit: 50,
        offset: 1,
        has_more: false,
        snapshots: [],
      })
    const latestFeed = vi.fn().mockResolvedValue({ schema_version: 2, items: [] })
    const api = liveApi({
      historyFeed,
      latestFeed,
      sources: vi.fn().mockResolvedValue({
        sources: [{ id: 'source-tsucha', type: 'apify_social', display_name: 'tsucha_ri', scope: 'public', enabled: true }],
      }),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/history?source_id=source-tsucha&q=tsucha']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: 'tsucha 历史一' })).toBeInTheDocument()
    expect(screen.getByText('2 条内容')).toBeInTheDocument()
    expect(screen.getByText('来源：tsucha_ri')).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: '搜索历史内容' })).toHaveValue('tsucha')
    expect(historyFeed).toHaveBeenCalledWith({
      q: 'tsucha',
      sourceId: 'source-tsucha',
      limit: 50,
      offset: 0,
    }, expect.any(AbortSignal))
    expect(screen.queryByText('历史记录已全部显示')).not.toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '加载更多（已显示 1/2）' }))
    expect(await screen.findByRole('article', { name: 'tsucha 历史二' })).toBeInTheDocument()
    expect(screen.getAllByRole('article')).toHaveLength(2)
    expect(historyFeed).toHaveBeenLastCalledWith({
      q: 'tsucha',
      sourceId: 'source-tsucha',
      limit: 50,
      offset: 1,
    }, expect.any(AbortSignal))
    expect(await screen.findByText('历史记录已全部显示')).toBeInTheDocument()
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
    expect(savedFeed).toHaveBeenCalledWith(50, 0, expect.any(AbortSignal))
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

  it('rolls optimistic saves back and reports the failure in an overlay toast', async () => {
    const user = userEvent.setup()
    const api = liveApi({
      updateItemState: vi.fn().mockRejectedValue(new ApiError(500, { code: 'save_failed', message: '收藏失败' })),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><DesignSystemProvider><AppRoutes api={api} /></DesignSystemProvider></MemoryRouter></QueryClientProvider>)

    const save = await screen.findByRole('button', { name: '收藏 真实 API 条目' })
    await user.click(save)
    await waitFor(() => expect(screen.getByRole('button', { name: '收藏 真实 API 条目' })).toBeInTheDocument())
    const message = await screen.findByText('收藏失败，状态已恢复。')
    expect(message.closest('[data-slot="toast-region"]')).not.toBeNull()
    expect(message.closest('[data-page-frame]')).toBeNull()
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
