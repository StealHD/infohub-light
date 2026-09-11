import { fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DesignSystemProvider } from '../../design-system'
import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
import type { OpenClawChatController } from '../openclaw'
import { chatController } from '../openclaw/OpenClawConversation.test.support'
import { projectSkillsStatus } from '../openclaw/workspace/openclawWorkspaceDetails'
import { AgentSkillsView } from './AgentSkillsView'

const status = projectSkillsStatus({ skills: [
  { skillKey: 'read-reports', name: '阅读报告', description: '把文章整理成阅读报告', disabled: false, eligible: true, missing: {} },
  { skillKey: 'pdf', name: 'PDF 提取', disabled: true, eligible: false, missing: { env: ['PDF_TOKEN'], bins: ['pdftotext'] } },
] })

function setup(skillsStatus = vi.fn().mockResolvedValue(status), supported = true, managed = false,
  role: User['role'] = 'member', api: Partial<ServiceApi> = {}) {
  const chat = chatController({ status: 'connected', sessionKey: 'root' }) as unknown as OpenClawChatController
  if (managed) chat.gatewayUrl = '/api/me/openclaw/socket'
  const invalidateSkills = vi.fn()
  chat.workspace = { ...chat.workspace, capabilities: () => ({ 'skills.status': supported }) as ReturnType<typeof chat.workspace.capabilities>,
    subscribe: () => () => undefined, skillsStatus, invalidateSkills }
  const service = {
    agentSkills: vi.fn().mockResolvedValue({ policy: { revision: 1, allowed_skill_keys: [], sync_state: 'synced', sync_in_progress: false, sync_error_code: null, updated_at: '', synced_at: '' }, skills: [] }),
    updateAgentSkillPolicy: vi.fn(), ...api,
  } as unknown as ServiceApi
  const user = { id: 'user-1', username: 'user', role, enabled: true }
  render(<MemoryRouter><DesignSystemProvider><AgentSkillsView chat={chat} api={service} user={user} /></DesignSystemProvider></MemoryRouter>)
  return { read: skillsStatus, invalidateSkills }
}

describe('Skills user scenarios', () => {
  it('reads installed skills and requirement details without admin authorization', async () => {
    const user = userEvent.setup()
    const { read } = setup()
    expect(await screen.findByText('阅读报告')).toBeVisible()
    expect(screen.getByText('已停用')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '查看 PDF 提取 详情' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('pdftotext')).toBeVisible()
    expect(within(dialog).getByText('PDF_TOKEN')).toBeVisible()
    expect(within(dialog).queryByLabelText('Gateway admin token')).not.toBeInTheDocument()
    expect(read).toHaveBeenCalledOnce()
    await user.click(within(dialog).getByRole('button', { name: '关闭' }))
    await user.click(screen.getByRole('button', { name: '启用' }))
    expect(screen.getByRole('heading', { name: '临时管理授权' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: '确认 Gateway 写操作' })).not.toBeInTheDocument()
  })

  it('preserves trusted rows after a refresh failure and retries without displaying raw errors', async () => {
    const user = userEvent.setup()
    const { read } = setup(vi.fn().mockResolvedValueOnce(status).mockRejectedValueOnce(new Error('SECRET_SENTINEL')).mockResolvedValue(status))
    await screen.findByText('阅读报告')
    await user.click(screen.getByRole('button', { name: '刷新 Skills' }))
    expect(await screen.findByText(/无法读取 Skills/)).toBeVisible()
    expect(screen.getByText('阅读报告')).toBeVisible()
    expect(screen.queryByText(/SECRET_SENTINEL/)).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新 Skills' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: '刷新 Skills' }))
    await waitFor(() => expect(read).toHaveBeenCalledTimes(3))
    await waitFor(() => expect(screen.queryByText(/无法读取 Skills/)).not.toBeInTheDocument())
  })

  it('offers only reading in server-managed mode', async () => {
    setup(vi.fn().mockResolvedValue(status), true, true)
    await screen.findByText('阅读报告')
    expect(screen.getByText('管理员统一开放')).toBeVisible()
    expect(screen.queryByRole('button', { name: '临时授权' })).toBeNull()
    expect(screen.queryByRole('button', { name: '启用' })).toBeNull()
    expect(screen.queryByRole('button', { name: '停用' })).toBeNull()
    expect(screen.getByRole('button', { name: '查看 PDF 提取 详情' })).toBeEnabled()
  })

  it('lets an owner select the shared allowlist and confirms before saving', async () => {
    const user = userEvent.setup()
    const agentSkills = vi.fn().mockResolvedValue({
      policy: { revision: 3, allowed_skill_keys: ['read-reports'], sync_state: 'synced', sync_in_progress: false, sync_error_code: null, updated_at: '', synced_at: '' },
      skills: [
        { skillKey: 'read-reports', name: '阅读报告', eligible: true, disabled: false, missing: {} },
        { skillKey: 'pdf', name: 'PDF 提取', eligible: false, disabled: false, missing: { bins: ['pdftotext'] } },
      ],
    })
    const update = vi.fn().mockResolvedValue({ policy: { revision: 4, allowed_skill_keys: ['pdf', 'read-reports'], sync_state: 'synced', sync_in_progress: false, sync_error_code: null, updated_at: '', synced_at: '' } })
    const { invalidateSkills } = setup(undefined, true, true, 'owner', { agentSkills, updateAgentSkillPolicy: update })
    await screen.findByText('阅读报告')
    await user.click(screen.getByRole('button', { name: '管理开放范围' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('PDF 提取')).toBeVisible()
    await user.click(within(dialog).getByRole('checkbox', { name: '开放 PDF 提取' }))
    await user.click(within(dialog).getByRole('button', { name: '保存开放范围' }))
    expect(within(dialog).getByText('确认统一开放范围')).toBeVisible()
    expect(update).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: '确认并同步' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith(3, ['pdf', 'read-reports']))
    expect(invalidateSkills).toHaveBeenCalledOnce()
  })

  it('closes an open detail when the allowed directory is invalidated', async () => {
    const user = userEvent.setup()
    setup(vi.fn().mockResolvedValueOnce(status).mockResolvedValueOnce(projectSkillsStatus({ skills: [] })), true, true)
    await user.click(await screen.findByRole('button', { name: '查看 PDF 提取 详情' }))
    expect(screen.getByRole('dialog')).toBeVisible()
    fireEvent.click(document.querySelector('[data-refresh-button-content]')!.parentElement!)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByText('管理员尚未开放 Skills')).toBeVisible()
  })

  it('explains unsupported status without issuing a request or presenting an empty list', () => {
    const { read } = setup(vi.fn(), false)
    expect(screen.getByText('当前 Gateway 不支持 Skills 状态')).toBeVisible()
    expect(screen.queryByText('没有 Skills')).not.toBeInTheDocument()
    expect(read).not.toHaveBeenCalled()
  })
})
