import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../api/service'
import { AppRoutes } from './App'

const chatLifecycle = vi.hoisted(() => ({
  disconnect: vi.fn(),
  mounts: 0,
  unmounts: 0,
  running: true,
  runTrace: null as null | {
    runId: string
    phase: 'completed'
    status: 'completed'
    startedAt: number
    endedAt: number
    activities: []
  },
}))

vi.mock('../features/openclaw/useOpenClawChat', () => ({
  useOpenClawChat: () => {
    useEffect(() => {
      chatLifecycle.mounts += 1
      return () => {
        chatLifecycle.unmounts += 1
        chatLifecycle.disconnect()
      }
    }, [])
    return {
      gatewayUrl: 'ws://127.0.0.1:18789',
      setGatewayUrl: vi.fn(),
      status: 'connected' as const,
      toolsStatus: 'available' as const,
      messages: [],
      streamText: chatLifecycle.running ? '仍在生成的回复' : '',
      runTrace: chatLifecycle.runTrace,
      issue: null,
      runtimeIssue: null,
      modelSwitchFallback: null,
      sessionKey: 'session-live',
      isRunning: chatLifecycle.running,
      isStopping: false,
      runtimeLoading: false,
      runtimeUpdating: false,
      models: [],
      thinkingOptions: [],
      runtimeSelection: {
        modelId: null,
        thinkingLevel: null,
        defaultModelId: null,
        defaultThinkingLevel: null,
      },
      connect: vi.fn(),
      disconnect: chatLifecycle.disconnect,
      forget: vi.fn(),
      send: vi.fn(),
      retry: vi.fn(),
      takeFailedMessage: vi.fn(),
      stop: vi.fn(),
      setModel: vi.fn(),
      setThinking: vi.fn(),
      switchToBlankConversation: vi.fn(),
      newConversation: vi.fn(),
    }
  },
}))

function useViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    writable: true,
    value: width,
  })
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

function lifecycleApi(): ServiceApi {
  return {
    authStatus: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'lifecycle-user', username: 'live', role: 'member', enabled: true } }),
    latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [{ id: 'feed-item', title: '信息流条目', url: 'https://example.com/feed', published_at: '2026-07-20T00:00:00Z' }] }),
    savedFeed: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', items: [{ id: 'saved-item', title: '收藏条目', url: 'https://example.com/saved', published_at: '2026-07-20T00:00:00Z' }], item_count: 1, limit: 200, offset: 0 }),
    historyFeed: vi.fn().mockResolvedValue({ schema_version: 1, scope: 'user', items: [{ id: 'history-item', title: '历史条目', url: 'https://example.com/history', published_at: '2026-07-20T00:00:00Z' }], featured_items: [], item_count: 1, snapshots: [] }),
    agentDelegations: vi.fn().mockResolvedValue({ enabled: true, subscription_writes_enabled: false, connections: [], mcp_url: '/mcp', openclaw_chat: { enabled: true, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5 }),
    jobs: vi.fn().mockResolvedValue({ jobs: [] }),
    feedSchedule: vi.fn().mockResolvedValue({ enabled: true, interval_minutes: 60, worker_status: 'ready' }),
    updateItemState: vi.fn(),
  } as unknown as ServiceApi
}

describe('authenticated route lifecycle', () => {
  beforeEach(() => {
    chatLifecycle.disconnect.mockClear()
    chatLifecycle.mounts = 0
    chatLifecycle.unmounts = 0
    chatLifecycle.running = true
    chatLifecycle.runTrace = null
    window.localStorage.clear()
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('keeps the shell and streaming OpenClaw hook mounted across content routes', async () => {
    const browser = userEvent.setup()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/feed']}><AppRoutes api={lifecycleApi()} /></MemoryRouter></QueryClientProvider>)

    const shell = await screen.findByTestId('live-workbench-shell')
    shell.dataset.lifecycleProbe = 'preserved'
    const backgroundAgentToggle = await screen.findByRole('button', { name: '展开 Agent 面板，OpenClaw 正在处理' })
    expect(backgroundAgentToggle).toBeEnabled()
    await browser.click(backgroundAgentToggle)
    expect(await screen.findByText('仍在生成的回复')).toBeInTheDocument()
    const openAgentToggle = screen.getByRole('button', { name: '收起 Agent 面板' })
    expect(openAgentToggle).toBeEnabled()
    const agentRail = screen.getByRole('complementary', { name: 'OpenClaw 上下文' })
    await browser.click(openAgentToggle)
    expect(agentRail).toHaveAttribute('aria-hidden', 'true')
    await waitFor(() => expect(screen.queryByText('仍在生成的回复')).not.toBeInTheDocument(), { timeout: 600 })

    const desktopNavigation = screen.getByRole('navigation', { name: '工作台导航' })
    chatLifecycle.running = false
    chatLifecycle.runTrace = {
      runId: 'run-lifecycle',
      phase: 'completed',
      status: 'completed',
      startedAt: 10,
      endedAt: 20,
      activities: [],
    }
    await browser.click(within(desktopNavigation).getByRole('link', { name: '收藏' }))
    expect(await screen.findByRole('heading', { name: '收藏' })).toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-lifecycle-probe', 'preserved')
    expect(screen.getByRole('button', { name: /展开 Agent 面板/u })).toHaveAccessibleName('展开 Agent 面板，OpenClaw 已完成，结果待查看')

    await browser.click(within(desktopNavigation).getByRole('link', { name: '历史' }))
    expect(await screen.findByRole('heading', { name: '历史' })).toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-lifecycle-probe', 'preserved')
    expect(screen.getByRole('button', { name: '展开 Agent 面板，OpenClaw 已完成，结果待查看' })).toBeEnabled()

    await waitFor(() => expect(chatLifecycle.mounts).toBe(1))
    expect(chatLifecycle.unmounts).toBe(0)
    expect(chatLifecycle.disconnect).not.toHaveBeenCalled()
  })
})
