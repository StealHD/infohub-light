import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitForElementToBeRemoved, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { AgentDelegation, AgentDelegationsResponse, User } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { queryKeys } from '../../api/queryKeys'
import { AgentsPage } from './AgentsPage'

const viewer: User = {
  id: 'viewer-1',
  username: 'viewer',
  display_name: '只读成员',
  role: 'viewer',
  enabled: true,
}

const member: User = {
  id: 'member-1',
  username: 'member',
  display_name: '普通成员',
  role: 'member',
  enabled: true,
}

const readTools = [
  'get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job',
  'get_source_setup_guide', 'list_available_sources', 'diagnose_source', 'diagnose_job',
]

const writeTools = [
  'get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job',
  'get_source_setup_guide', 'list_available_sources', 'prepare_create_subscription',
  'prepare_update_subscription', 'prepare_delete_subscription', 'apply_subscription_change',
  'diagnose_source', 'diagnose_job',
]

function includedTools(configuration: string): string[] {
  const command = configuration.split('\n')[0]
  const prefix = "openclaw mcp set inteliscope '"
  return JSON.parse(command.slice(prefix.length, -1)).toolFilter.include as string[]
}

const listing: AgentDelegationsResponse = {
  enabled: true,
  subscription_writes_enabled: true,
  mcp_url: 'https://rb.jiefs.top/mcp',
  token_ttl_days: 90,
  max_active: 5,
  connections: [{
    id: 'agent-1', name: 'Office Mac', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'],
    token_prefix: 'ih_mcp_v1_abcd1234', created_at: '2026-07-16T00:00:00Z',
    expires_at: '2026-10-14T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active',
  }],
}

function renderPage(response: AgentDelegationsResponse = listing, currentUser: User = member) {
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
    api, user: currentUser, query: '', setQuery: vi.fn(), activity: { state: 'idle', retryable: false, terminal: true },
    refresh: vi.fn(), beginAction: () => ({ userId: currentUser.id, generation: 0 }), isActionCurrent: () => true,
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
    const browser = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Office Mac' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '助手连接' })).toBeInTheDocument()
    expect(screen.getByText(/^从未使用/)).toBeInTheDocument()
    expect(screen.queryByText(/^在线$/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建连接' })).toBeEnabled()
    expect(screen.getByText('只读')).toBeInTheDocument()
    const pageConfiguration = screen.getByTestId('openclaw-config-page').textContent || ''
    expect(includedTools(pageConfiguration)).toEqual(readTools)
    expect(pageConfiguration).toContain('${INTELISCOPE_MCP_TOKEN}')
    expect(pageConfiguration).not.toContain('ih_mcp_v1_abcd1234')
    await browser.click(screen.getByRole('button', { name: '创建连接' }))
    expect(within(screen.getByRole('dialog', { name: '创建助手连接' })).getByText(/只读连接可读取并诊断/)).toBeInTheDocument()
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
    expect(JSON.stringify(client.getQueryData(queryKeys.agentDelegations(member.id)))).not.toContain('ih_mcp_v1_one_time_secret')
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain('ih_mcp_v1_one_time_secret')
    expect(window.localStorage.getItem('INTELISCOPE_MCP_TOKEN')).toBeNull()
    expect(window.sessionStorage.getItem('INTELISCOPE_MCP_TOKEN')).toBeNull()
    expect(window.location.href).not.toContain('ih_mcp_v1_one_time_secret')
    expect(api.createAgentDelegation).toHaveBeenCalledWith('Personal Mac', 'read')
  })

  it('creates an explicit subscription-management connection and uses fourteen tools', async () => {
    const browser = userEvent.setup()
    const { api } = renderPage()

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.type(within(dialog).getByRole('textbox', { name: '连接名称' }), 'Write Mac')
    await browser.click(within(dialog).getByRole('combobox', { name: '访问权限' }))
    await browser.click(screen.getByRole('option', { name: '可管理订阅' }))
    await browser.click(within(dialog).getByRole('button', { name: '生成一次性令牌' }))

    expect(api.createAgentDelegation).toHaveBeenCalledWith('Write Mac', 'subscriptions_write')
    const config = await screen.findByTestId('openclaw-config')
    const configuration = config.textContent || ''
    expect(includedTools(configuration)).toEqual(writeTools)
    expect(configuration).toContain('${INTELISCOPE_MCP_TOKEN}')
    expect(configuration).not.toContain('ih_mcp_v1_one_time_secret')
  })

  it('never offers write access to a viewer', async () => {
    const browser = userEvent.setup()
    renderPage(listing, viewer)

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.click(within(dialog).getByRole('combobox', { name: '访问权限' }))
    expect(screen.queryByRole('option', { name: '可管理订阅' })).not.toBeInTheDocument()
  })

  it('disables write access with explanatory copy when subscription writes are off', async () => {
    const browser = userEvent.setup()
    renderPage({ ...listing, subscription_writes_enabled: false })

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.click(within(dialog).getByRole('combobox', { name: '访问权限' }))
    expect(screen.getByRole('option', { name: '可管理订阅' })).toHaveAttribute('aria-disabled', 'true')
    expect(within(dialog).getByText('管理员尚未启用订阅管理连接；你仍可创建只读连接。')).toBeInTheDocument()
  })

  it('defaults access back to read each time the create dialog opens', async () => {
    const browser = userEvent.setup()
    renderPage()

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    let dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.click(within(dialog).getByRole('combobox', { name: '访问权限' }))
    await browser.click(screen.getByRole('option', { name: '可管理订阅' }))
    await browser.click(within(dialog).getByRole('button', { name: '取消' }))
    await waitForElementToBeRemoved(dialog)
    await browser.click(screen.getByRole('button', { name: '创建连接' }))
    dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    expect(within(dialog).getByRole('combobox', { name: '访问权限' })).toHaveTextContent('只读')
  })

  it('copies configuration for an existing connection using its own access', async () => {
    const browser = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
    const writeConnection: AgentDelegation = {
      ...listing.connections[0],
      id: 'agent-write',
      name: 'Write Mac',
      access: 'subscriptions_write' as const,
      scopes: ['inteliscope:read', 'inteliscope:subscriptions:write'],
    }
    renderPage({ ...listing, connections: [...listing.connections, writeConnection] })

    await screen.findByRole('heading', { name: 'Write Mac' })
    await browser.click(screen.getByRole('button', { name: '复制 Write Mac 配置' }))
    const copiedConfiguration = writeText.mock.calls[0][0]
    expect(includedTools(copiedConfiguration)).toEqual(writeTools)
    expect(copiedConfiguration).toContain('${INTELISCOPE_MCP_TOKEN}')
    expect(copiedConfiguration).not.toContain('ih_mcp_v1_one_time_secret')
    expect(screen.getByText('可管理订阅')).toBeInTheDocument()
    expect(screen.getByText('可管理订阅不包括密钥、共享来源、任务、Feed 条目状态或刷新操作。')).toBeInTheDocument()
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
