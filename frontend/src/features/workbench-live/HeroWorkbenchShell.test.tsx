import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
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

const api = {
  agentDelegations: vi.fn().mockResolvedValue({ enabled: true, connections: [], mcp_url: '/mcp', token_ttl_days: 90, max_active: 5 }),
} as unknown as ServiceApi

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-probe">{location.pathname}</output>
}

function Shell({ user, path = '/feed', onLogout = vi.fn() }: { user: User; path?: string; onLogout?: () => void }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>
    <MemoryRouter initialEntries={[path]}>
      <HeroWorkbenchShell api={api} user={user} query="" onQueryChange={vi.fn()} onLogout={onLogout} refreshState="idle">
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
    expect(screen.queryByRole('dialog', { name: '分类导航' })).not.toBeInTheDocument()

    await browser.click(trigger)
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

  it('opens account actions from the avatar and logs out only from the menu action', async () => {
    const browser = userEvent.setup()
    const onLogout = vi.fn()
    render(<Shell user={{ id: 'account-menu', username: 'alpha', display_name: 'Alpha', role: 'admin', enabled: true }} onLogout={onLogout} />)

    expect(screen.queryByRole('button', { name: '退出登录' })).not.toBeInTheDocument()
    const account = screen.getByRole('button', { name: '打开账户菜单' })
    await browser.click(account)
    expect(screen.getByText(/管理员/)).toBeInTheDocument()
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

  it('removes search and manual refresh only from the Feed header', () => {
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

  it('keeps collection header controls inside the same application typography scope', () => {
    render(<Shell path="/saved" user={{ id: 'saved-visual', username: 'saved', role: 'member', enabled: true }} />)

    expect(screen.getByPlaceholderText('搜索标题、来源或主题')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '更新信息流' })).toBeInTheDocument()
    expect(screen.getByTestId('live-workbench-shell')).toHaveAttribute('data-ui-typography', 'system')
    const collectionToggle = screen.getByRole('button', { name: '收起 Agent 面板' })
    expect(collectionToggle).not.toHaveAttribute('data-agent-toggle-visual')
    expect(screen.getByRole('heading', { name: '收藏' }).closest('header')).not.toHaveAttribute('data-header-visual')
  })
})

describe('HeroWorkbenchShell OpenClaw composer', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    window.sessionStorage.clear()
    useViewport(1440)
  })

  it('presents a handoff composer and disables copying without context', () => {
    render(<Shell user={{ id: 'composer-empty', username: 'empty', role: 'member', enabled: true }} />)

    expect(screen.getByText('交接模式')).toBeInTheDocument()
    expect(screen.queryByText('仅生成交接提示词，不在站内运行 Agent')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制交接提示词' })).toBeDisabled()
    expect(screen.getAllByText('自动 · OpenClaw 决定').length).toBeGreaterThan(0)
  })

  it('persists model guidance and copies without executing a network request', async () => {
    const browser = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    window.sessionStorage.setItem('inteliscope.agent-context.v1:composer-copy', JSON.stringify({
      userId: 'composer-copy', question: '分析机会', itemIds: ['item-1'], modelPreference: 'auto',
    }))
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<Shell user={{ id: 'composer-copy', username: 'copy', role: 'member', enabled: true }} />)

    await browser.click(screen.getByRole('button', { name: /模型偏好/ }))
    await browser.click(screen.getByRole('option', { name: '深度分析' }))
    await browser.click(screen.getByRole('button', { name: '复制交接提示词' }))

    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('模型偏好：深度分析'))
    expect(screen.getByRole('status', { name: '交接状态' })).toHaveTextContent('交接提示词已复制')
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v1:composer-copy') || '{}')).toMatchObject({ modelPreference: 'deep' })
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

    await browser.click(screen.getByRole('button', { name: '复制交接提示词' }))
    expect(screen.getByRole('status', { name: '交接状态' })).toHaveTextContent('无法写入剪贴板，请手动复制')
    expect(screen.getByRole('textbox', { name: '交给 OpenClaw 的问题' })).toHaveValue('保留问题')
    expect(JSON.parse(window.sessionStorage.getItem('inteliscope.agent-context.v1:composer-error') || '{}')).toMatchObject({ itemIds: ['item-1'], modelPreference: 'fast' })
  })
})
