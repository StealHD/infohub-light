import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AgentConnectionProvider } from './AgentConnectionContext'
import { PersonalAgentConnection } from './PersonalAgentConnection'
import type { AgentConnection } from '../../api/agentConnectionService'
import type { ServiceApi } from '../../api/service'
import type { OpenClawChatController } from '../openclaw/openclawContracts'

const ready: AgentConnection = { state: 'ready', agent_id: 'personal-alice', can_connect: true,
  can_chat: true, verification: { deployment: true, chat: false, own_content: true,
    information_automations: false, notifications: false } }

function fixture(api: Partial<ServiceApi>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const connect = vi.fn()
  const view = (userId: string) => <QueryClientProvider client={client}><MemoryRouter>
    <AgentConnectionProvider value={{ api: api as ServiceApi, userId }}>
      <PersonalAgentConnection chat={{ status: 'idle', connect } as unknown as OpenClawChatController} />
    </AgentConnectionProvider>
  </MemoryRouter></QueryClientProvider>
  return { view, connect, client }
}

describe('personal connection status', () => {
  it('does not equate deployment with live chat or notification acceptance', async () => {
    const { view } = fixture({ agentConnection: vi.fn().mockResolvedValue(ready) })
    render(view('alice'))
    expect(await screen.findByText(/个人 Agent 已接入/)).toBeVisible()
    expect(screen.queryByText(/通知.*已验证/)).toBeNull()
    expect(screen.getByRole('button', { name: '连接' })).toBeEnabled()
  })
  it('discards an old account response while the next account remains unbound', async () => {
    let resolveAlice!: (value: AgentConnection) => void
    const api = { agentConnection: vi.fn()
      .mockImplementationOnce(() => new Promise<AgentConnection>(resolve => { resolveAlice = resolve }))
      .mockResolvedValue({ ...ready, state: 'unconfigured', agent_id: null, can_connect: false }) }
    const { view } = fixture(api)
    const mounted = render(view('alice'))
    await waitFor(() => expect(api.agentConnection).toHaveBeenCalledTimes(1))
    mounted.rerender(view('bob'))
    await screen.findByText(/请管理员为当前账号完成个人接入/)
    resolveAlice(ready)
    await waitFor(() => expect(screen.queryByText('当前 Agent：personal-alice')).toBeNull())
    expect(screen.queryByRole('button', { name: '连接' })).toBeNull()
    expect(screen.getByRole('link', { name: '前往 Agent 接入' })).toHaveAttribute('href', '/agents')
  })
})
