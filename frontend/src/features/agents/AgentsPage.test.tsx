import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitForElementToBeRemoved, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { AgentDelegationsResponse, User } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { queryKeys } from '../../api/queryKeys'
import { AgentsPage } from './AgentsPage'

const user: User = {
  id: 'viewer-1',
  username: 'viewer',
  display_name: '只读成员',
  role: 'viewer',
  enabled: true,
}

const listing: AgentDelegationsResponse = {
  enabled: true,
  mcp_url: 'https://rb.jiefs.top/mcp',
  token_ttl_days: 90,
  max_active: 5,
  connections: [{
    id: 'agent-1', name: 'Office Mac', client_type: 'openclaw', scopes: ['inteliscope:read'],
    token_prefix: 'ih_mcp_v1_abcd1234', created_at: '2026-07-16T00:00:00Z',
    expires_at: '2026-10-14T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active',
  }],
}

function renderPage(response: AgentDelegationsResponse = listing) {
  const api = {
    agentDelegations: vi.fn().mockResolvedValue(response),
    createAgentDelegation: vi.fn().mockResolvedValue({
      connection: { ...response.connections[0], id: 'agent-new', name: 'Personal Mac' },
      token: 'ih_mcp_v1_one_time_secret',
    }),
    renameAgentDelegation: vi.fn().mockResolvedValue({ ...response.connections[0], name: 'Renamed Mac' }),
    revokeAgentDelegation: vi.fn().mockResolvedValue({ revoked: true }),
  } as unknown as ServiceApi
  const context: AppOutletContext = {
    api, user, query: '', setQuery: vi.fn(), activity: { state: 'idle', retryable: false, terminal: true },
    refresh: vi.fn(), beginAction: () => ({ userId: user.id, generation: 0 }), isActionCurrent: () => true,
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const Layout = ({ children }: { children?: ReactNode }) => <>{children}<Outlet context={context} /></>
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/agents']}>
        <Routes><Route element={<Layout />}><Route path="/agents" element={<AgentsPage />} /></Route></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { api, client, ...rendered }
}

describe('AgentsPage', () => {
  it('shows connection status without claiming the local agent is online', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Office Mac' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '助手连接' })).toBeInTheDocument()
    expect(screen.getByText(/^从未使用/)).toBeInTheDocument()
    expect(screen.queryByText(/^在线$/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建连接' })).toBeEnabled()
  })

  it('keeps the one-time token only in a non-dismissible dialog and clears it explicitly', async () => {
    const browser = userEvent.setup()
    const { api, client } = renderPage()
    window.localStorage.clear()
    window.sessionStorage.clear()

    await screen.findByRole('heading', { name: 'Office Mac' })
    await browser.click(screen.getByRole('button', { name: '创建连接' }))
    const createDialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.type(within(createDialog).getByRole('textbox', { name: '连接名称' }), 'Personal Mac')
    await browser.click(within(createDialog).getByRole('button', { name: '生成一次性令牌' }))

    const tokenDialog = await screen.findByRole('dialog', { name: '保存一次性令牌' })
    expect(within(tokenDialog).getByText('ih_mcp_v1_one_time_secret')).toBeInTheDocument()
    const configuration = within(tokenDialog).getByTestId('openclaw-config')
    expect(configuration).toHaveTextContent('${INTELISCOPE_MCP_TOKEN}')
    expect(configuration).not.toHaveTextContent('ih_mcp_v1_one_time_secret')
    await browser.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '保存一次性令牌' })).toBeInTheDocument()
    const backdrop = document.querySelector('.MuiBackdrop-root')
    expect(backdrop).not.toBeNull()
    await browser.click(backdrop!)
    expect(screen.getByRole('dialog', { name: '保存一次性令牌' })).toBeInTheDocument()

    await browser.click(within(tokenDialog).getByRole('button', { name: '我已保存' }))
    expect(screen.queryByText('ih_mcp_v1_one_time_secret')).not.toBeInTheDocument()
    expect(JSON.stringify(client.getQueryData(queryKeys.agentDelegations(user.id)))).not.toContain('ih_mcp_v1_one_time_secret')
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain('ih_mcp_v1_one_time_secret')
    expect(window.localStorage.getItem('INTELISCOPE_MCP_TOKEN')).toBeNull()
    expect(window.sessionStorage.getItem('INTELISCOPE_MCP_TOKEN')).toBeNull()
    expect(window.location.href).not.toContain('ih_mcp_v1_one_time_secret')
    expect(api.createAgentDelegation).toHaveBeenCalledWith('Personal Mac')
  })

  it('supports rename, revoke and manual refresh', async () => {
    const browser = userEvent.setup()
    const { api } = renderPage()
    await screen.findByRole('heading', { name: 'Office Mac' })

    await browser.click(screen.getByRole('button', { name: '重命名 Office Mac' }))
    const renameDialog = screen.getByRole('dialog', { name: '重命名助手连接' })
    const input = within(renameDialog).getByRole('textbox', { name: '连接名称' })
    await browser.clear(input)
    await browser.type(input, 'Renamed Mac')
    await browser.click(within(renameDialog).getByRole('button', { name: '保存名称' }))
    expect(api.renameAgentDelegation).toHaveBeenCalledWith('agent-1', 'Renamed Mac')
    await waitForElementToBeRemoved(renameDialog)

    await browser.click(screen.getByRole('button', { name: '吊销 Office Mac' }))
    const revokeDialog = screen.getByRole('dialog', { name: '吊销助手连接' })
    await browser.click(within(revokeDialog).getByRole('button', { name: '确认吊销' }))
    expect(api.revokeAgentDelegation).toHaveBeenCalledWith('agent-1')
    await waitForElementToBeRemoved(revokeDialog)

    await browser.click(screen.getByRole('button', { name: '刷新最近使用时间' }))
    expect(api.agentDelegations).toHaveBeenCalledTimes(4)
  })

  it('disables creation when the feature is off or five active connections exist', async () => {
    const { unmount } = renderPage({ ...listing, enabled: false })
    expect(await screen.findByRole('button', { name: '创建连接' })).toBeDisabled()
    expect(screen.getByText('管理员尚未启用 Remote MCP。')).toBeInTheDocument()
    unmount()

    renderPage({
      ...listing,
      connections: Array.from({ length: 5 }, (_, index) => ({
        ...listing.connections[0], id: `agent-${index}`, name: `Device ${index}`,
      })),
    })
    expect(await screen.findByRole('button', { name: '创建连接' })).toBeDisabled()
    expect(screen.getByText('已达到 5 个有效连接上限。')).toBeInTheDocument()
  })
})
