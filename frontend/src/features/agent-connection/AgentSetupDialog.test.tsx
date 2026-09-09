import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DesignSystemProvider } from '../../design-system'
import type { ServiceApi } from '../../api/service'
import { ApiError } from '../../api/client'
import type { AgentConnection } from '../../api/agentConnectionService'
import { AgentConnectionProvider } from './AgentConnectionContext'
import { AgentSetupDialog } from './AgentSetupDialog'

const state: AgentConnection = { state: 'unconfigured', can_manage_setup: true, can_connect: false,
  can_chat: false, verification: { deployment: false, chat: false, own_content: false,
    information_automations: false, notifications: false } }

function mount(api: Partial<ServiceApi>, pending = false) {
  const onClose = vi.fn(), onRefresh = vi.fn().mockResolvedValue(undefined)
  const view = render(<MemoryRouter><DesignSystemProvider><AgentConnectionProvider value={{ api: api as ServiceApi, userId: 'owner' }}>
    <AgentSetupDialog state={{ ...state, state: pending ? 'pending_verification' : 'unconfigured' }} onClose={onClose} onRefresh={onRefresh} />
  </AgentConnectionProvider></DesignSystemProvider></MemoryRouter>)
  return { ...view, onClose, onRefresh, user: userEvent.setup() }
}

describe('personal Agent setup', () => {
  it('shows the actionable server error without automatically retrying', async () => {
    const prepareAgentConnection = vi.fn().mockRejectedValue(new ApiError(409, {
      code: 'remote_mcp_disabled', message: '管理员需先配置本站 Remote MCP 地址。',
    }))
    const { user } = mount({ prepareAgentConnection })
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: '准备个人接入' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('管理员需先配置本站 Remote MCP 地址。')
    expect(prepareAgentConnection).toHaveBeenCalledTimes(1)
  })
  it('opening is read-only and preparation requires confirmation with a single in-flight request', async () => {
    let resolve!: (value: AgentConnection) => void
    const prepareAgentConnection = vi.fn(() => new Promise<AgentConnection>(done => { resolve = done }))
    const { user } = mount({ prepareAgentConnection })
    expect(prepareAgentConnection).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '准备个人接入' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox'))
    await user.dblClick(screen.getByRole('button', { name: '准备个人接入' }))
    expect(prepareAgentConnection).toHaveBeenCalledTimes(1)
    await act(async () => resolve({ ...state, state: 'pending_verification' }))
    expect(await screen.findByRole('button', { name: '下载配置包' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '验证并完成接入' })).toBeDisabled()
  })

  it('resumes a pending binding and only activates after explicitly uploading a receipt', async () => {
    const activateAgentConnection = vi.fn().mockResolvedValue({ ...state, state: 'ready' })
    const { user } = mount({ activateAgentConnection }, true)
    await user.click(screen.getByRole('checkbox'))
    const file = new File(['{"proof":"fixture"}'], 'receipt.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: async () => '{"proof":"fixture"}' })
    await user.upload(screen.getByLabelText(/选择刚生成的/), file)
    await user.click(screen.getByRole('button', { name: '验证并完成接入' }))
    await waitFor(() => expect(activateAgentConnection).toHaveBeenCalledWith('{"proof":"fixture"}'))
    expect(await screen.findByRole('status')).toHaveTextContent('个人绑定已验证')
  })

  it('does not download credentials when the account dialog unmounts during export', async () => {
    let resolve!: (value: { archive_base64: string }) => void
    const agentConnectionBundle = vi.fn(() => new Promise<{ archive_base64: string }>(done => { resolve = done }))
    const { user, unmount } = mount({ agentConnectionBundle }, true)
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: '下载配置包' }))
    unmount()
    const create = vi.spyOn(URL, 'createObjectURL')
    await act(async () => resolve({ archive_base64: 'YQ==' }))
    expect(create).not.toHaveBeenCalled()
    create.mockRestore()
  })
})
