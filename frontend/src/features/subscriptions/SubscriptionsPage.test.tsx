import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { CatalogSource, Job, Subscription, User } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { ActionFeedbackProvider } from '../../app/ActionFeedback'
import { SubscriptionsPage } from './SubscriptionsPage'

const member: User = { id: 'user-1', username: 'member', display_name: '成员', role: 'member', enabled: true }
const sources: CatalogSource[] = [
  { id: 'public-1', type: 'rss', display_name: 'Apple Developer News', scope: 'public', default_channel: '工作/项目', enabled: true },
  { id: 'workspace-1', type: 'github_release', display_name: 'Claude Code Releases', scope: 'workspace', default_channel: 'AI', enabled: true },
  { id: 'private-1', type: 'apify_social', display_name: 'X · @example', scope: 'private', owner_user_id: member.id, default_channel: '朋友动态', enabled: true },
]
const subscriptions: Subscription[] = sources.map((source, index) => ({
  id: `sub-${index + 1}`, user_id: member.id, source_id: source.id, source_display_name: source.display_name,
  source_type: source.type, enabled: true, priority: 80,
  schedule: { enabled: false, interval_minutes: 360, worker_status: 'ready' },
}))
const jobs: Job[] = [
  { id: 'job-1', user_id: member.id, job_type: 'user_feed_refresh', status: 'queued', created_at: '2026-07-14T06:00:00Z' },
  { id: 'job-2', user_id: member.id, job_type: 'source_fetch', source_id: 'public-1', status: 'succeeded', result: { item_count: 2 }, created_at: '2026-07-14T05:00:00Z', finished_at: '2026-07-14T05:01:00Z' },
]

function renderPage(user: User = member, options: { workerStatus?: string; createSourceFetch?: ServiceApi['createSourceFetch'] } = {}) {
  const api = {
    sources: vi.fn().mockResolvedValue({ sources }),
    sourceTypes: vi.fn().mockResolvedValue({ source_types: sources.map((source) => ({ type: source.type, label: source.type, fields: [] })) }),
    subscriptions: vi.fn().mockResolvedValue({ subscriptions }),
    sourceHealth: vi.fn().mockResolvedValue({
      schema_version: 1, scope: 'user', summary: { healthy: 3, degraded: 0, failing: 0, unknown: 0, total: 3 },
      items: subscriptions.map((subscription, index) => ({ subscription_id: subscription.id, source_id: subscription.source_id, status: 'healthy', consecutive_failures: 0, last_fetched_count: index + 1 })),
    }),
    feedSchedule: vi.fn().mockResolvedValue({ enabled: false, interval_minutes: 360, allowed_intervals: [60, 360], worker_status: options.workerStatus ?? 'stale' }),
    config: vi.fn().mockResolvedValue({
      config: { tags: ['AI Agent', 'AI 编程'] },
      taxonomy: { channels: ['AI', '工作/项目', '朋友动态', '其他'], topics: ['AI Agent', 'AI 编程'] },
    }),
    jobs: vi.fn().mockResolvedValue({ jobs }),
    subscribe: vi.fn(), unsubscribe: vi.fn(), updateSubscription: vi.fn(), updateSourceSchedule: vi.fn(),
    createSourceTest: vi.fn(), createSourceFetch: options.createSourceFetch ?? vi.fn().mockResolvedValue({ id: 'job-new', user_id: user.id, job_type: 'source_fetch', status: 'queued' }), updateFeedSchedule: vi.fn(), createSource: vi.fn(), updateSource: vi.fn(), retryJob: vi.fn(),
  } as unknown as ServiceApi
  const context: AppOutletContext = {
    api, user, query: '', setQuery: vi.fn(), activity: { state: 'idle', retryable: false, terminal: true },
    refresh: vi.fn(), beginAction: () => ({ userId: user.id, generation: 0 }), isActionCurrent: () => true,
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const Layout = ({ children }: { children?: ReactNode }) => <>{children}<Outlet context={context} /></>
  render(
    <QueryClientProvider client={client}>
      <ActionFeedbackProvider userId={user.id}><MemoryRouter initialEntries={['/subscriptions']}>
        <Routes><Route element={<Layout />}><Route path="/subscriptions" element={<SubscriptionsPage />} /></Route></Routes>
      </MemoryRouter></ActionFeedbackProvider>
    </QueryClientProvider>,
  )
  return { api }
}

describe('SubscriptionsPage', () => {
  it('organizes subscriptions, source discovery and run history into readable tabs', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('tab', { name: '我的订阅' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'AI' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '工作/项目' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '朋友动态' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '来源库' }))
    expect(screen.getAllByText('按来源默认频道归类；可见范围和来源类型保留为标签。')).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /编辑 Apple Developer News 来源/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '运行记录' }))
    expect(screen.getByText('更新整个信息流')).toBeInTheDocument()
    expect(screen.getByText('等待后台处理')).toBeInTheDocument()
    expect(screen.getByText('抓取单个来源')).toBeInTheDocument()
    expect(screen.queryByText('user_feed_refresh')).not.toBeInTheDocument()
    expect(screen.queryByText('source_fetch')).not.toBeInTheDocument()
    expect(screen.queryByText('queued')).not.toBeInTheDocument()
  }, 10_000)

  it('runs one subscribed source immediately when the worker is ready', async () => {
    const user = userEvent.setup()
    const { api } = renderPage(member, { workerStatus: 'ready' })

    await screen.findByRole('heading', { name: 'Apple Developer News' })
    await user.click(screen.getByRole('button', { name: '立即获取 Apple Developer News' }))

    expect(api.createSourceFetch).toHaveBeenCalledWith('public-1', 'sub-1')
  })

  it('does not queue a source fetch when the worker is stale', async () => {
    const user = userEvent.setup()
    const { api } = renderPage(member, { workerStatus: 'stale' })

    await screen.findByRole('heading', { name: 'Apple Developer News' })
    await user.click(screen.getByRole('button', { name: '立即获取 Apple Developer News' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('后台获取服务当前不可用')
    expect(api.createSourceFetch).not.toHaveBeenCalled()
  })

  it('shows pending feedback only on the source being submitted', async () => {
    const user = userEvent.setup()
    let resolveFetch: ((job: Job) => void) | undefined
    const createSourceFetch = vi.fn(() => new Promise<Job>((resolve) => { resolveFetch = resolve })) as ServiceApi['createSourceFetch']
    renderPage(member, { workerStatus: 'ready', createSourceFetch })

    await screen.findByRole('heading', { name: 'Apple Developer News' })
    await user.click(screen.getByRole('button', { name: '立即获取 Apple Developer News' }))

    expect(await screen.findByRole('button', { name: '提交中 Apple Developer News' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '立即获取 Claude Code Releases' })).toBeEnabled()

    resolveFetch?.({ id: 'job-new', user_id: member.id, job_type: 'source_fetch', status: 'queued' })
  })

  it('filters sources and automatically reveals matches inside a collapsed channel', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByRole('heading', { name: 'Apple Developer News' })
    await user.click(screen.getByRole('button', { name: '收起 工作/项目' }))
    expect(screen.queryByRole('heading', { name: 'Apple Developer News' })).not.toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: '搜索来源' }), 'Apple')
    expect(screen.getByRole('heading', { name: 'Apple Developer News' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Claude Code Releases' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'X · @example' })).not.toBeInTheDocument()
  })
})
