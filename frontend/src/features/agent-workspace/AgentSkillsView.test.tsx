import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DesignSystemProvider } from '../../design-system'
import type { OpenClawChatController } from '../openclaw'
import { chatController } from '../openclaw/OpenClawConversation.test.support'
import { projectSkillsStatus } from '../openclaw/workspace/openclawWorkspaceProjection'
import { AgentSkillsView } from './AgentSkillsView'

const status = projectSkillsStatus({ skills: [
  { skillKey: 'read-reports', name: '阅读报告', description: '把文章整理成阅读报告', disabled: false, eligible: true, missing: {} },
  { skillKey: 'pdf', name: 'PDF 提取', disabled: true, eligible: false, missing: { env: ['PDF_TOKEN'], bins: ['pdftotext'] } },
] })

function setup(skillsStatus = vi.fn().mockResolvedValue(status), supported = true) {
  const chat = chatController({ status: 'connected', sessionKey: 'root' }) as unknown as OpenClawChatController
  chat.workspace = { ...chat.workspace, capabilities: () => ({ 'skills.status': supported }) as ReturnType<typeof chat.workspace.capabilities>,
    subscribe: () => () => undefined, skillsStatus }
  render(<MemoryRouter><DesignSystemProvider><AgentSkillsView chat={chat} /></DesignSystemProvider></MemoryRouter>)
  return skillsStatus
}

describe('Skills user scenarios', () => {
  it('reads installed skills and requirement details without admin authorization', async () => {
    const user = userEvent.setup()
    const read = setup()
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
    const read = setup(vi.fn().mockResolvedValueOnce(status).mockRejectedValueOnce(new Error('SECRET_SENTINEL')).mockResolvedValue(status))
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

  it('explains unsupported status without issuing a request or presenting an empty list', () => {
    const read = setup(vi.fn(), false)
    expect(screen.getByText('当前 Gateway 不支持 Skills 状态')).toBeVisible()
    expect(screen.queryByText('没有 Skills')).not.toBeInTheDocument()
    expect(read).not.toHaveBeenCalled()
  })
})
