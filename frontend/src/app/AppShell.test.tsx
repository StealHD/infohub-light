import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppShell } from './AppShell'

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
      return {
        matches,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }
    }),
  })
}

describe('AppShell', () => {
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() })
    useViewport(1440)
  })

  it('renders the product navigation, search, account and acquisition action', () => {
    render(
      <MemoryRouter initialEntries={['/feed']}>
        <AppShell
          user={{ id: 'user-1', username: 'owner', display_name: 'Owner', role: 'owner', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          onRefresh={vi.fn()}
          refreshState="idle"
        >
          <div>content</div>
        </AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByText('Inteliscope')).toBeInTheDocument()
    const navigation = within(screen.getByRole('navigation', { name: '主导航' }))
    expect(navigation.getByRole('link', { name: '信息流' })).toHaveAttribute('href', '/feed')
    expect(navigation.getByRole('link', { name: '稍后读' })).toHaveAttribute('href', '/later')
    expect(navigation.getByRole('link', { name: '收藏' })).toHaveAttribute('href', '/saved')
    expect(navigation.getByRole('link', { name: '历史' })).toHaveAttribute('href', '/history')
    expect(navigation.getByRole('link', { name: '订阅' })).toHaveAttribute('href', '/subscriptions')
    expect(navigation.getByRole('link', { name: '助手' })).toHaveAttribute('href', '/agents')
    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute('href', '/settings')
    expect(screen.queryByRole('navigation', { name: '移动端主导航' })).not.toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: '搜索信息流' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '更新信息流' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '账户 Owner' })).toBeInTheDocument()
  })

  it('aligns the account control with navigation and toggles its menu from the same button', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <AppShell
          user={{ id: 'user-1', username: 'admin', role: 'admin', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          refreshState="idle"
          onLogout={vi.fn()}
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    const account = screen.getByRole('button', { name: '账户 admin' })
    expect(account).toHaveClass('MuiListItemButton-root')
    await user.click(account)
    expect(screen.getByRole('menu')).toBeVisible()
    expect(account).toHaveAttribute('aria-expanded', 'true')
    await user.click(account)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(account).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders the current bottom navigation on mobile', () => {
    useViewport(390)
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <AppShell
          user={{ id: 'user-1', username: 'owner', display_name: 'Owner', role: 'owner', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          onRefresh={vi.fn()}
          refreshState="idle"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    const navigation = within(screen.getByRole('navigation', { name: '移动端主导航' }))
    expect(navigation.getByRole('link', { name: '设置' })).toHaveAttribute('href', '/settings')
    expect(navigation.queryByRole('link', { name: '助手' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
  })

  it('keeps acquisition disabled for a viewer', () => {
    render(
      <MemoryRouter>
        <AppShell
          user={{ id: 'viewer-1', username: 'viewer', role: 'viewer', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          refreshState="idle"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: '更新信息流' })).toBeDisabled()
  })

  it('shows immediate submit feedback while a refresh request is being created', () => {
    render(
      <MemoryRouter>
        <AppShell
          user={{ id: 'user-1', username: 'owner', role: 'owner', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          refreshState="pending"
          onRefresh={vi.fn()}
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: '提交更新中' })).toBeDisabled()
  })

  it('keeps failed-source navigation and retry in the task alert', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <AppShell
          user={{ id: 'user-1', username: 'owner', role: 'owner', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          refreshState="failed"
          refreshMessage="获取失败"
          refreshEventKey="job-1:failed"
          onRetry={onRetry}
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('获取失败')
    expect(screen.getByRole('link', { name: '失败来源' })).toHaveAttribute('href', '/subscriptions?health=problem')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('auto-hides short task notices and keeps the same event dismissed across polling renders', () => {
    vi.useFakeTimers()
    const owner = { id: 'user-1', username: 'owner', role: 'owner' as const, enabled: true }
    const view = render(
      <MemoryRouter>
        <AppShell
          user={owner}
          query=""
          onQueryChange={vi.fn()}
          refreshState="queued"
          refreshMessage="更新任务已开始"
          refreshEventKey="job-1:queued"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('更新任务已开始')
    act(() => vi.advanceTimersByTime(5_000))
    expect(screen.getByRole('alert', { hidden: true })).not.toBeVisible()

    view.rerender(
      <MemoryRouter>
        <AppShell
          user={owner}
          query=""
          onQueryChange={vi.fn()}
          refreshState="queued"
          refreshMessage="更新任务已开始"
          refreshEventKey="job-1:queued"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )
    expect(screen.getByRole('alert', { hidden: true })).not.toBeVisible()
  })

  it('lets users dismiss long task notices without polling reopening them', () => {
    const owner = { id: 'user-1', username: 'owner', role: 'owner' as const, enabled: true }
    const view = render(
      <MemoryRouter>
        <AppShell
          user={owner}
          query=""
          onQueryChange={vi.fn()}
          refreshState="blocked"
          refreshMessage="后台获取服务不可用，未创建任务。"
          refreshEventKey="blocked-1"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: '关闭通知' }))
    expect(screen.getByRole('alert', { hidden: true })).not.toBeVisible()
    view.rerender(
      <MemoryRouter>
        <AppShell
          user={owner}
          query=""
          onQueryChange={vi.fn()}
          refreshState="blocked"
          refreshMessage="后台获取服务不可用，未创建任务。"
          refreshEventKey="blocked-1"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )
    expect(screen.getByRole('alert', { hidden: true })).not.toBeVisible()
  })

  it('defaults to a collapsed sidebar and remembers expansion per user', async () => {
    const user = userEvent.setup()
    const owner = { id: 'user-1', username: 'owner', display_name: 'Owner', role: 'owner' as const, enabled: true }
    const view = render(
      <MemoryRouter>
        <AppShell user={owner} query="" onQueryChange={vi.fn()} refreshState="idle"><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: '展开侧栏' })).toHaveAttribute('aria-expanded', 'false')
    const footer = screen.getByRole('group', { name: '账户与设置' })
    expect(within(footer).getByRole('button', { name: '账户 Owner' })).toBeInTheDocument()
    expect(within(footer).queryByRole('button', { name: '展开侧栏' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '展开侧栏' }))
    expect(screen.getByRole('button', { name: '收起侧栏' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('group', { name: '账户与设置' })).toHaveTextContent('所有者')
    expect(window.localStorage.getItem('inteliscope.ui.sidebar.v1:user-1')).toBe('expanded')

    view.unmount()
    render(
      <MemoryRouter>
        <AppShell user={owner} query="" onQueryChange={vi.fn()} refreshState="idle"><div>content</div></AppShell>
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: '收起侧栏' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('does not reuse another user sidebar preference', () => {
    window.localStorage.setItem('inteliscope.ui.sidebar.v1:user-1', 'expanded')
    render(
      <MemoryRouter>
        <AppShell
          user={{ id: 'user-2', username: 'member', role: 'member', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          refreshState="idle"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: '展开侧栏' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('ignores invalid stored sidebar values', () => {
    window.localStorage.setItem('inteliscope.ui.sidebar.v1:user-1', 'wide')
    render(
      <MemoryRouter>
        <AppShell
          user={{ id: 'user-1', username: 'owner', role: 'owner', enabled: true }}
          query=""
          onQueryChange={vi.fn()}
          refreshState="idle"
        ><div>content</div></AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: '展开侧栏' })).toHaveAttribute('aria-expanded', 'false')
  })
})
