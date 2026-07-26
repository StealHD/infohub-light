import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { AgentDelegation, AgentDelegationsResponse, User } from '../../api/types'
import { queryKeys } from '../../api/queryKeys'
import type { AppOutletContext } from '../../app/AppContext'
import { DesignSystemProvider } from '../../design-system'
import type { OpenClawCredentialVault } from '../openclaw/openclawCredentialVault'
import { OpenClawPairingUpgradeRequiredError } from '../openclaw/openclawDevice'
import { OPENCLAW_CURRENT_SCOPES } from '../openclaw/openclawGateway'
import { HeroAgentsPage, OpenClawBrowserSettings } from './HeroAgentsPage'

const member: User = {
  id: 'member-1',
  username: 'member',
  display_name: '普通成员',
  role: 'member',
  enabled: true,
}

const viewer: User = {
  id: 'viewer-1',
  username: 'viewer',
  display_name: '只读成员',
  role: 'viewer',
  enabled: true,
}

const readTools = [
  'get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job',
  'get_source_setup_guide', 'search_bilibili_users', 'list_available_sources', 'diagnose_source', 'diagnose_job',
  'query_operation_logs',
]

const writeTools = [
  'get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job',
  'get_source_setup_guide', 'search_bilibili_users', 'list_available_sources', 'diagnose_source', 'diagnose_job',
  'query_operation_logs',
  'prepare_create_subscription', 'prepare_update_subscription', 'prepare_delete_subscription',
  'apply_subscription_change',
]

const listing: AgentDelegationsResponse = {
  enabled: true,
  subscription_writes_enabled: true,
  mcp_url: 'https://example.test/mcp',
  token_ttl_days: 90,
  max_active: 5,
  connections: [{
    id: 'agent-1',
    name: 'Office Mac',
    client_type: 'openclaw',
    access: 'read',
    scopes: ['inteliscope:read'],
    token_prefix: 'ih_mcp_v1_abcd1234',
    created_at: '2026-07-16T00:00:00Z',
    expires_at: '2026-10-14T00:00:00Z',
    last_used_at: null,
    revoked_at: null,
    status: 'active',
  }],
}

function includedTools(configuration: string): string[] {
  const command = configuration.split('\n')[0]
  const prefix = "openclaw mcp set inteliscope '"
  return JSON.parse(command.slice(prefix.length, -1)).toolFilter.include as string[]
}

function renderPage(response: AgentDelegationsResponse = listing, currentUser: User = member) {
  const api = {
    agentDelegations: vi.fn().mockResolvedValue(response),
    createAgentDelegation: vi.fn().mockResolvedValue({
      connection: { ...response.connections[0], id: 'agent-new', name: 'Write Mac', access: 'subscriptions_write' },
      token: 'ih_mcp_v1_one_time_secret',
    }),
    renameAgentDelegation: vi.fn().mockResolvedValue({ ...response.connections[0], name: 'Renamed Mac' }),
    revokeAgentDelegation: vi.fn().mockResolvedValue({ revoked: true }),
    deleteAgentDelegationRecord: vi.fn().mockResolvedValue({ deleted: true }),
  } as unknown as ServiceApi
  const context: AppOutletContext = {
    api,
    user: currentUser,
    query: '',
    setQuery: vi.fn(),
    activity: { state: 'idle', retryable: false, terminal: true },
    refresh: vi.fn(),
    reloadFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [] }),
    beginAction: () => ({ userId: currentUser.id, generation: 0 }),
    isActionCurrent: () => true,
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const Layout = () => <Outlet context={context} />
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/agents']}>
        <DesignSystemProvider>
          <Routes><Route element={<Layout />}><Route path="/agents" element={<HeroAgentsPage />} /></Route></Routes>
        </DesignSystemProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { api, client, ...rendered }
}

function pairedBrowserVault() {
  return {
    load: vi.fn().mockResolvedValue({
      identity: {
        deviceId: 'browser-device',
        publicKey: 'browser-public',
        privateKey: {} as CryptoKey,
      },
      deviceToken: 'browser-token',
      scopes: [...OPENCLAW_CURRENT_SCOPES],
      sessionKey: 'browser-session',
    }),
  } as unknown as OpenClawCredentialVault
}

describe('OpenClaw browser pairing settings', () => {
  it('requires confirmation and locks server removal before showing local deletion', async () => {
    const browser = userEvent.setup()
    const vault = pairedBrowserVault()
    let resolveForget: ((value: 'removed') => void) | undefined
    const pendingForget = new Promise<'removed'>((resolve) => { resolveForget = resolve })
    const forgetBrowser = vi.fn(() => pendingForget)
    render(<MemoryRouter><DesignSystemProvider><OpenClawBrowserSettings
      userId="member-1"
      enabled
      defaultUrl="ws://127.0.0.1:18789"
      targetVersion="2026.7.1"
      vault={vault}
      forgetBrowser={forgetBrowser}
    /></DesignSystemProvider></MemoryRouter>)

    await screen.findByText('此浏览器已配对')
    const forgetTrigger = screen.getByRole('button', { name: '忘记此浏览器' })
    expect(forgetTrigger).not.toHaveTextContent('忘记此浏览器')
    await browser.hover(forgetTrigger)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('忘记此浏览器')
    await browser.click(forgetTrigger)
    let dialog = screen.getByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })
    expect(forgetBrowser).not.toHaveBeenCalled()
    await browser.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })).not.toBeInTheDocument()
    expect(forgetBrowser).not.toHaveBeenCalled()
    await waitFor(() => expect(forgetTrigger).toHaveFocus())

    await browser.click(screen.getByRole('button', { name: '忘记此浏览器' }))
    dialog = screen.getByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })
    await browser.click(within(dialog).getByRole('button', { name: '确认移除并忘记' }))
    expect(forgetBrowser).toHaveBeenCalledWith(expect.objectContaining({
      userId: 'member-1',
      gatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clearTranscripts: expect.any(Function),
    }))
    expect(within(dialog).getByRole('button', { name: '正在移除…' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '取消' })).toBeDisabled()
    await browser.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })).toBeInTheDocument()

    await act(async () => { resolveForget?.('removed') })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '忘记此浏览器' })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '保存地址' })).toHaveFocus())
    expect(screen.getByText('此浏览器未配对')).toBeInTheDocument()
    const success = screen.getByText('OpenClaw 服务端设备和当前浏览器配对已删除')
    expect(success.closest('[data-slot="toast-region"]')).not.toBeNull()
  })

  it('keeps the pairing and shows the exact approval command for a legacy scope upgrade', async () => {
    const browser = userEvent.setup()
    const vault = pairedBrowserVault()
    const forgetBrowser = vi.fn().mockRejectedValue(new OpenClawPairingUpgradeRequiredError('request-upgrade-1'))
    render(<MemoryRouter><DesignSystemProvider><OpenClawBrowserSettings
      userId="member-1"
      enabled
      defaultUrl="ws://127.0.0.1:18789"
      targetVersion="2026.7.1"
      vault={vault}
      forgetBrowser={forgetBrowser}
    /></DesignSystemProvider></MemoryRouter>)

    await screen.findByText('此浏览器已配对')
    await browser.click(screen.getByRole('button', { name: '忘记此浏览器' }))
    const dialog = screen.getByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })
    await browser.click(within(dialog).getByRole('button', { name: '确认移除并忘记' }))

    expect(await screen.findByText(/已创建设备权限升级请求/)).toHaveTextContent(
      'openclaw devices approve request-upgrade-1',
    )
    expect(screen.getByText('此浏览器已配对')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: '移除 OpenClaw 浏览器配对' })).toBeInTheDocument()
  })
})

describe('HeroAgentsPage delegation access', () => {
  it('creates a subscription-management connection with the sixteen-tool configuration', async () => {
    const browser = userEvent.setup()
    const { api } = renderPage()

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.type(within(dialog).getByRole('textbox', { name: '连接名称' }), 'Write Mac')
    await browser.click(within(dialog).getByRole('button', { name: /访问权限/ }))
    await browser.click(screen.getByRole('option', { name: '可管理订阅' }))
    await browser.click(within(dialog).getByRole('button', { name: '生成一次性令牌' }))

    expect(api.createAgentDelegation).toHaveBeenCalledWith('Write Mac', 'subscriptions_write')
    const tokenDialog = await screen.findByRole('dialog', { name: '保存一次性 MCP token' })
    const configuration = within(tokenDialog).getByLabelText('OpenClaw 配置命令').textContent || ''
    expect(includedTools(configuration)).toEqual(writeTools)
    expect(configuration).toContain('${INTELISCOPE_MCP_TOKEN}')
    expect(configuration).not.toContain('ih_mcp_v1_one_time_secret')
  })

  it('keeps the default page configuration read-only with twelve tools', async () => {
    renderPage()

    const configuration = (await screen.findByLabelText('OpenClaw 配置命令')).textContent || ''
    expect(includedTools(configuration)).toEqual(readTools)
  })

  it('exposes diagnostics only in the generated config without a log UI', async () => {
    renderPage()

    const configuration = (await screen.findByLabelText('OpenClaw 配置命令')).textContent || ''
    expect(configuration).toContain('query_operation_logs')
    expect(configuration).not.toContain('/api/log')
    expect(screen.queryByText('操作日志')).not.toBeInTheDocument()
    expect(screen.queryByText('日志正文')).not.toBeInTheDocument()
    expect(document.querySelector('[data-testid="operation-log-list"]')).toBeNull()
  })

  it('aligns both configuration cards and wraps long commands without horizontal scrolling', async () => {
    renderPage()

    const readConfiguration = await screen.findByLabelText('OpenClaw 配置命令')
    const writeConfiguration = screen.getByLabelText('订阅管理 OpenClaw 配置命令')
    expect(screen.getByText('读取并诊断信息流、订阅、来源健康和任务。')).toHaveClass('min-h-10')
    expect(screen.getByText('变更仍需 prepare、准确确认和 apply。')).toHaveClass('min-h-10')
    for (const configuration of [readConfiguration, writeConfiguration]) {
      expect(configuration).toHaveClass(
        'max-h-56',
        'min-w-0',
        'max-w-full',
        'overflow-x-hidden',
        'overflow-y-auto',
        'whitespace-pre-wrap',
        'break-words',
        '[overflow-wrap:anywhere]',
      )
      expect(configuration).not.toHaveClass('overflow-auto')
    }
  })

  it('never offers subscription-management access to a viewer', async () => {
    const browser = userEvent.setup()
    renderPage(listing, viewer)

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.click(within(dialog).getByRole('button', { name: /访问权限/ }))
    expect(screen.queryByRole('option', { name: '可管理订阅' })).not.toBeInTheDocument()
  })

  it('disables subscription-management access and explains the server flag', async () => {
    const browser = userEvent.setup()
    renderPage({ ...listing, subscription_writes_enabled: false })

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.click(within(dialog).getByRole('button', { name: /访问权限/ }))
    expect(screen.getByRole('option', { name: '可管理订阅' })).toHaveAttribute('aria-disabled', 'true')
    expect(within(dialog).getByText('管理员尚未启用订阅管理连接；你仍可创建只读连接。')).toBeInTheDocument()
  })

  it('resets the create-dialog access to read every time it opens', async () => {
    const browser = userEvent.setup()
    renderPage()

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    let dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.click(within(dialog).getByRole('button', { name: /访问权限/ }))
    await browser.click(screen.getByRole('option', { name: '可管理订阅' }))
    await browser.click(within(dialog).getByRole('button', { name: '取消' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '创建助手连接' })).not.toBeInTheDocument())

    await browser.click(screen.getByRole('button', { name: '创建连接' }))
    dialog = screen.getByRole('dialog', { name: '创建助手连接' })
    expect(within(dialog).getByRole('button', { name: /访问权限/ })).toHaveTextContent('只读')
  })

  it('copies an existing connection configuration using its persisted access', async () => {
    const browser = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
    const writeConnection: AgentDelegation = {
      ...listing.connections[0],
      id: 'agent-write',
      name: 'Write Mac',
      access: 'subscriptions_write',
      scopes: ['inteliscope:read', 'inteliscope:subscriptions:write'],
    }
    renderPage({ ...listing, connections: [...listing.connections, writeConnection] })

    await screen.findByRole('heading', { name: 'Write Mac' })
    await browser.click(screen.getByRole('button', { name: '更多操作：Write Mac' }))
    await browser.click(within(screen.getByRole('dialog', { name: 'Write Mac 连接操作' })).getByRole('button', { name: '复制配置' }))
    const configuration = String(writeText.mock.calls[0][0])
    expect(includedTools(configuration)).toEqual(writeTools)
    expect(configuration).toContain('${INTELISCOPE_MCP_TOKEN}')
    expect(configuration).not.toContain('ih_mcp_v1_one_time_secret')
    expect(screen.getByText('可管理订阅')).toBeInTheDocument()
    expect(screen.getByText('可管理订阅不包括密钥、共享来源、任务、Feed 条目状态或刷新操作。')).toBeInTheDocument()
  })

  it('keeps the one-time token in a non-dismissible dialog and clears it explicitly', async () => {
    const browser = userEvent.setup()
    const { api, client } = renderPage()

    await browser.click(await screen.findByRole('button', { name: '创建连接' }))
    const createDialog = screen.getByRole('dialog', { name: '创建助手连接' })
    await browser.type(within(createDialog).getByRole('textbox', { name: '连接名称' }), 'Personal Mac')
    await browser.click(within(createDialog).getByRole('button', { name: '生成一次性令牌' }))

    const tokenDialog = await screen.findByRole('dialog', { name: '保存一次性 MCP token' })
    expect(within(tokenDialog).getByText('ih_mcp_v1_one_time_secret')).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '保存一次性 MCP token' })).toBeInTheDocument()
    await browser.click(screen.getByTestId('one-time-token-backdrop'))
    expect(screen.getByRole('dialog', { name: '保存一次性 MCP token' })).toBeInTheDocument()

    await browser.click(within(tokenDialog).getByRole('button', { name: '我已保存' }))
    expect(screen.queryByText('ih_mcp_v1_one_time_secret')).not.toBeInTheDocument()
    expect(JSON.stringify(client.getQueryData(queryKeys.agentDelegations(member.id)))).not.toContain('ih_mcp_v1_one_time_secret')
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain('ih_mcp_v1_one_time_secret')
    expect(api.createAgentDelegation).toHaveBeenCalledWith('Personal Mac', 'read')
  })

  it('supports rename, revoke, refresh and connection creation limits', async () => {
    const browser = userEvent.setup()
    const { api, unmount } = renderPage()
    await screen.findByRole('heading', { name: 'Office Mac' })

    const more = screen.getByRole('button', { name: '更多操作：Office Mac' })
    await browser.click(more)
    await browser.click(within(screen.getByRole('dialog', { name: 'Office Mac 连接操作' })).getByRole('button', { name: '重命名' }))
    const renameDialog = screen.getByRole('dialog', { name: '重命名助手连接' })
    const input = within(renameDialog).getByRole('textbox', { name: '连接名称' })
    await browser.clear(input)
    await browser.type(input, 'Renamed Mac')
    await browser.click(within(renameDialog).getByRole('button', { name: '保存名称' }))
    expect(api.renameAgentDelegation).toHaveBeenCalledWith('agent-1', 'Renamed Mac')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '重命名助手连接' })).not.toBeInTheDocument())
    await waitFor(() => expect(more).toHaveFocus())

    await browser.click(more)
    await browser.click(within(screen.getByRole('dialog', { name: 'Office Mac 连接操作' })).getByRole('button', { name: '吊销连接' }))
    const revokeDialog = screen.getByRole('dialog', { name: '吊销助手连接' })
    await browser.click(within(revokeDialog).getByRole('button', { name: '确认吊销' }))
    expect(api.revokeAgentDelegation).toHaveBeenCalledWith('agent-1')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '吊销助手连接' })).not.toBeInTheDocument())

    await browser.click(screen.getByRole('button', { name: '刷新最近使用时间' }))
    expect(api.agentDelegations).toHaveBeenCalled()
    unmount()

    const disabledView = renderPage({ ...listing, enabled: false })
    expect(await screen.findByRole('button', { name: '创建连接' })).toBeDisabled()
    disabledView.unmount()

    renderPage({
      ...listing,
      connections: Array.from({ length: 5 }, (_, index) => ({ ...listing.connections[0], id: `agent-${index}`, name: `Device ${index}` })),
    })
    expect(await screen.findByText('已达到 5 个有效连接上限。')).toBeInTheDocument()
  })

  it('deletes only the selected revoked connection after confirmation', async () => {
    const browser = userEvent.setup()
    const activeConnection = { ...listing.connections[0], name: 'Active Mac' }
    const revokedConnection: AgentDelegation = {
      ...listing.connections[0],
      id: 'agent-revoked',
      name: 'Revoked Mac',
      status: 'revoked',
      revoked_at: '2026-07-22T12:00:00Z',
    }
    const expiredConnection: AgentDelegation = {
      ...listing.connections[0],
      id: 'agent-expired',
      name: 'Expired Mac',
      status: 'expired',
      expires_at: '2026-07-01T00:00:00Z',
    }
    const { api } = renderPage({
      ...listing,
      connections: [revokedConnection, expiredConnection, activeConnection],
    })
    let resolveDelete: ((result: { deleted: boolean }) => void) | undefined
    vi.mocked(api.deleteAgentDelegationRecord).mockReturnValueOnce(
      new Promise((resolve) => { resolveDelete = resolve }),
    )

    await screen.findByRole('heading', { name: 'Revoked Mac' })
    const activeMore = screen.getByRole('button', { name: '更多操作：Active Mac' })
    const revokedMore = screen.getByRole('button', { name: '更多操作：Revoked Mac' })
    const expiredMore = screen.getByRole('button', { name: '更多操作：Expired Mac' })
    await browser.click(activeMore)
    let actionDialog = screen.getByRole('dialog', { name: 'Active Mac 连接操作' })
    expect(within(actionDialog).getByRole('button', { name: '吊销连接' })).toBeInTheDocument()
    expect(within(actionDialog).queryByRole('button', { name: '删除记录' })).not.toBeInTheDocument()
    await browser.keyboard('{Escape}')
    await browser.click(expiredMore)
    actionDialog = screen.getByRole('dialog', { name: 'Expired Mac 连接操作' })
    expect(within(actionDialog).queryByRole('button', { name: '吊销连接' })).not.toBeInTheDocument()
    expect(within(actionDialog).queryByRole('button', { name: '删除记录' })).not.toBeInTheDocument()
    await browser.keyboard('{Escape}')
    await browser.click(revokedMore)
    actionDialog = screen.getByRole('dialog', { name: 'Revoked Mac 连接操作' })
    expect(within(actionDialog).queryByRole('button', { name: '吊销连接' })).not.toBeInTheDocument()
    await browser.click(within(actionDialog).getByRole('button', { name: '删除记录' }))
    let dialog = screen.getByRole('dialog', { name: '删除已吊销连接' })
    expect(within(dialog).getByText(/只会删除这一条已吊销连接记录/)).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(api.deleteAgentDelegationRecord).not.toHaveBeenCalled()
    await waitFor(() => expect(revokedMore).toHaveFocus())

    await browser.click(revokedMore)
    await browser.click(within(screen.getByRole('dialog', { name: 'Revoked Mac 连接操作' })).getByRole('button', { name: '删除记录' }))
    dialog = screen.getByRole('dialog', { name: '删除已吊销连接' })
    await browser.click(within(dialog).getByRole('button', { name: '确认删除' }))
    expect(api.deleteAgentDelegationRecord).toHaveBeenCalledOnce()
    expect(api.deleteAgentDelegationRecord).toHaveBeenCalledWith('agent-revoked')
    expect(api.revokeAgentDelegation).not.toHaveBeenCalledWith('agent-revoked')
    expect(within(dialog).getByRole('button', { name: '正在删除…' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '取消' })).toBeDisabled()
    await browser.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '删除已吊销连接' })).toBeInTheDocument()

    await act(async () => { resolveDelete?.({ deleted: true }) })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '删除已吊销连接' })).not.toBeInTheDocument())
    const success = screen.getByText('已删除连接记录')
    expect(success.closest('[data-slot="toast-region"]')).not.toBeNull()
  })
})
