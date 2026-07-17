import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentType, ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import type { ServiceApi } from '../api/service'
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

  it('temporarily inserts a deep-linked item returned by feedItem', async () => {
    const feedItem = vi.fn().mockResolvedValue({ id: 'deep', title: '深链条目', url: 'https://example.com/deep', published_at: '2026-07-17T01:00:00Z' })
    const api = liveApi({ feedItem } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=deep']}><AppRoutes api={api} /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('article', { name: '深链条目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起 深链条目' })).toHaveAttribute('aria-expanded', 'true')
    expect(feedItem).toHaveBeenCalledWith('deep', expect.any(AbortSignal))
  })

  it('removes a stale 404 deep link and leaves the Feed usable', async () => {
    const api = liveApi({
      feedItem: vi.fn().mockRejectedValue(new ApiError(404, { code: 'not_found', message: '不存在' })),
    } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/__preview/workbench-live?item=missing']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText(/这条信息已不可用/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('article', { name: '真实 API 条目' })).toBeInTheDocument())
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('/__preview/workbench-live')
    expect(screen.getByLabelText('当前位置')).not.toHaveTextContent('item=')
  })

  it('redirects later to saved while preserving the item parameter', async () => {
    const api = liveApi({ savedFeed: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', items: [], item_count: 0, limit: 200, offset: 0 }) } as Partial<ServiceApi>)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/later?item=live-1']}><AppRoutes api={api} /><LocationProbe /></MemoryRouter></QueryClientProvider>)

    await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/saved?item=live-1'))
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
