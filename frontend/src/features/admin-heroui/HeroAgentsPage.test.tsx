import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DesignSystemProvider } from '../../design-system'
import type { ServiceApi } from '../../api/service'
import type { AgentConnection } from '../../api/agentConnectionService'
import { AgentConnectionProvider } from '../agent-connection/AgentConnectionContext'
import type { OpenClawCredentialVault } from '../openclaw/openclawCredentialVault'
import { OpenClawPairingUpgradeRequiredError } from '../openclaw/openclawDevice'
import { OPENCLAW_CURRENT_SCOPES } from '../openclaw/openclawGateway'
import { oneTimeTokenWriteCommand } from '../openclaw/openclawAgentConfiguration'
import { HeroAgentsPage, OpenClawBrowserSettings } from './HeroAgentsPage'

describe('one-time token write command', () => {
  it('updates only the Inteliscope token with restrictive file permissions', () => {
    const command = oneTimeTokenWriteCommand('ih_mcp_v1_one_time_secret')

    expect(command).toContain('mkdir -p ~/.openclaw')
    expect(command).toContain('chmod 700 ~/.openclaw')
    expect(command).toContain("grep -v '^INTELISCOPE_MCP_TOKEN=' ~/.openclaw/.env || true")
    expect(command).toContain("printf '%s\\n' 'INTELISCOPE_MCP_TOKEN=ih_mcp_v1_one_time_secret'")
    expect(command).toContain('mv ~/.openclaw/.env.tmp ~/.openclaw/.env')
    expect(command).toContain('chmod 600 ~/.openclaw/.env')
  })
})

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
  it('renders managed connection without validating a direct URL or loading browser credentials', () => {
    const vault = pairedBrowserVault()
    render(<MemoryRouter><DesignSystemProvider><OpenClawBrowserSettings userId="member-1" enabled defaultUrl="/api/me/openclaw/socket" targetVersion="2026.9.2" vault={vault} /></DesignSystemProvider></MemoryRouter>)
    expect(screen.getByRole('link', { name: '打开 OpenClaw' })).toHaveAttribute('href', '/agent')
    expect(screen.queryByRole('textbox', { name: 'OpenClaw Gateway URL' })).not.toBeInTheDocument()
    expect(vault.load).not.toHaveBeenCalled()
  })

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


const unbound: AgentConnection = { state: 'unconfigured', can_connect: false, can_chat: false,
  can_manage_setup: true, setup: { available: true, state: 'idle' },
  verification: { deployment: false, chat: false, own_content: false, information_automations: false, notifications: false } }

function managedPage(api: Partial<ServiceApi>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><DesignSystemProvider>
    <AgentConnectionProvider value={{ api: api as ServiceApi, userId: 'owner' }}>
      <HeroAgentsPage />
    </AgentConnectionProvider>
  </DesignSystemProvider></MemoryRouter></QueryClientProvider>)
}

describe('one managed Agent entry', () => {
  it('shows one action and never reads manual tokens or starts setup on mount', async () => {
    const api = { agentConnection: vi.fn().mockResolvedValue(unbound), agentDelegations: vi.fn(),
      setupManagedAgentConnection: vi.fn() }
    managedPage(api)
    expect(await screen.findByRole('button', { name: '接入 Agent' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '创建连接' })).toBeNull()
    expect(screen.queryByText('高级接入')).toBeNull()
    expect(api.agentDelegations).not.toHaveBeenCalled()
    expect(api.setupManagedAgentConnection).not.toHaveBeenCalled()
  })
  it('locks rapid activation and reads the same server-owned running state', async () => {
    const browser = userEvent.setup()
    let resolve!: () => void
    const api = { agentConnection: vi.fn().mockResolvedValue(unbound),
      setupManagedAgentConnection: vi.fn(() => new Promise<NonNullable<AgentConnection['setup']>>(done => {
        resolve = () => done({ available: true, state: 'running' })
      })) }
    managedPage(api)
    const button = await screen.findByRole('button', { name: '接入 Agent' })
    await browser.dblClick(button)
    expect(api.setupManagedAgentConnection).toHaveBeenCalledTimes(1)
    expect(button).toBeDisabled()
    api.agentConnection.mockResolvedValue({ ...unbound, state: 'pending_verification',
      setup: { available: true, state: 'running', phase: 'verifying' } })
    await act(async () => resolve())
    expect(await screen.findByText('正在验证连接与数据授权')).toBeVisible()
    expect(screen.getByRole('button', { name: '正在接入' })).toBeDisabled()
  })
  it('a new browser reuses ready status without another setup request', async () => {
    const api = { agentConnection: vi.fn().mockResolvedValue({ ...unbound, state: 'ready', can_connect: true }),
      setupManagedAgentConnection: vi.fn() }
    const first = managedPage(api)
    expect(await screen.findByRole('link', { name: '进入 OpenClaw' })).toHaveAttribute('href', '/agent')
    first.unmount()
    managedPage(api)
    expect(await screen.findByRole('link', { name: '进入 OpenClaw' })).toBeVisible()
    expect(api.setupManagedAgentConnection).not.toHaveBeenCalled()
  })
  it('shows failure locally and does not recreate revoked bindings', async () => {
    managedPage({ agentConnection: vi.fn().mockResolvedValue({ ...unbound, state: 'revoked' }) })
    expect(await screen.findByText(/个人接入已解除/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '接入 Agent' })).toBeNull()
  })
  it('cancels without mutation, confirms once, then explicitly reconnects', async () => {
    const browser = userEvent.setup()
    const api = { agentConnection: vi.fn().mockResolvedValue({ ...unbound, state: 'ready', can_connect: true }),
      revokeAgentConnection: vi.fn().mockImplementation(async () => {
        const state = { ...unbound, state: 'revoked' }
        api.agentConnection.mockResolvedValue(state)
        return state
      }), reconnectManagedAgentConnection: vi.fn().mockResolvedValue({ state: 'running' }) }
    managedPage(api)
    await browser.click(await screen.findByRole('button', { name: '解除接入' }))
    await browser.click(screen.getByRole('button', { name: '取消' }))
    expect(api.revokeAgentConnection).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '解除接入' }))
    await browser.dblClick(screen.getByRole('button', { name: '确认解除' }))
    expect(api.revokeAgentConnection).toHaveBeenCalledTimes(1)
    const reconnect = await screen.findByRole('button', { name: '重新接入' })
    expect(api.reconnectManagedAgentConnection).not.toHaveBeenCalled()
    await browser.click(reconnect)
    expect(api.reconnectManagedAgentConnection).toHaveBeenCalledTimes(1)
  })
})
