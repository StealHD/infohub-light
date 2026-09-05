import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, userEvent, chatController } from '../OpenClawConversation.test.support'
import { OpenClawWorkbenchPanel } from '../adapters/OpenClawConversation'
import { createWorkbenchAgentValue } from '../../workbench-live/createWorkbenchAgentValue'
import type { AgentContextDraftV6 } from '../../workbench-live/agentContext'
import type { OpenClawChatController } from '../openclawContracts'

const skill = { key: 'weather', name: 'weather', description: '天气查询', enabled: true, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true, missingBins: [], missingEnv: [], installOptions: [] }
function setup(initial: Partial<AgentContextDraftV6> = {}) {
  const skillsStatus = vi.fn().mockResolvedValue({ skills: [skill] })
  const chat = chatController({ status: 'connected', sessionKey: 'root', workspace: {
    skillScope: () => ({ agentId: 'main', generation: 1 }), capabilities: () => ({ 'skills.status': true }),
    subscribe: () => () => {}, skillsStatus,
  } }) as unknown as OpenClawChatController
  function Harness() {
    const [draft, setDraft] = useState<AgentContextDraftV6>({ userId: 'test', items: [], question: '', ...initial })
    const value = { ...createWorkbenchAgentValue(draft, setDraft), openComposer: vi.fn() }
    return <OpenClawWorkbenchPanel chat={chat} value={value} />
  }
  render(<Harness />)
  return { chat, skillsStatus, input: screen.getByRole('textbox', { name: '发送给 OpenClaw 的问题' }) as HTMLTextAreaElement, user: userEvent.setup() }
}
describe('shared Composer shortcuts', () => {
  it('selects a Skill without sending and retains focus, then sends one explicit reference', async () => {
    const { chat, input, user, skillsStatus } = setup()
    expect(skillsStatus).not.toHaveBeenCalled()
    await user.type(input, '@天气')
    await screen.findByRole('option', { name: /weather/u })
    await user.keyboard('{Enter}')
    expect(await screen.findByText('Skill：weather')).toBeInTheDocument()
    expect(chat.send).not.toHaveBeenCalled()
    await waitFor(() => expect(input).toHaveFocus())
    await user.type(input, '查天气')
    await user.keyboard('{Enter}')
    await waitFor(() => expect(chat.send).toHaveBeenCalledTimes(1))
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({ gatewayPrompt: expect.stringContaining('\n$weather\n'), selectedSkill: expect.objectContaining({ name: 'weather' }) }))
  })
  it('references a material at the caret without adding a duplicate', async () => {
    const { input, user, chat } = setup({ items: [{ articleId: 'one', title: '阅读材料', sourceName: '测试' }] })
    await user.type(input, '总结 @阅读')
    await screen.findByRole('option', { name: /阅读材料/u })
    await user.keyboard('{Enter}')
    expect(input).toHaveValue('总结 「阅读材料」')
    expect(chat.send).not.toHaveBeenCalled()
    expect(screen.getByLabelText('已附带 1 条信息')).toBeInTheDocument()
  })
  it('does not intercept IME Enter, closes with Escape, preserves Tab, and sends unknown text ordinarily', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/unknown')
    fireEvent.compositionStart(input)
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229, isComposing: true })
    expect(chat.send).not.toHaveBeenCalled()
    expect(input).toHaveValue('/unknown')
    fireEvent.compositionEnd(input)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('listbox', { name: 'Agent 快捷候选' })).not.toBeInTheDocument())
    await user.keyboard('{Enter}')
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({ displayText: '/unknown', gatewayPrompt: expect.stringMatching(/^\[INTELISCOPE_HANDOFF_V8\]/u) }))
    await user.type(input, '/help')
    await user.tab()
    expect(input).not.toHaveFocus()
    expect(screen.queryByRole('listbox', { name: 'Agent 快捷候选' })).not.toBeInTheDocument()
  })
  it('new conversation cancellation has no creation and preserves the pending question', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '待发送 /new')
    await user.keyboard('{Enter}')
    await screen.findByRole('dialog')
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(chat.newConversation).not.toHaveBeenCalled()
    expect(input).toHaveValue('待发送 ')
  })
  it('help and status are local reads and help documents the shortcuts', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/status'); await user.keyboard('{Enter}')
    expect(await screen.findByText('当前对话状态')).toBeInTheDocument()
    expect(screen.getByText('暂无可信用量')).toBeInTheDocument()
    expect(chat.send).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '关闭' }))
    await user.type(input, '/help'); await user.keyboard('{Enter}')
    expect(await screen.findByText('OpenClaw 使用示例')).toBeInTheDocument()
    expect(chat.newConversation).not.toHaveBeenCalled()
  })
  it('reopens the same command after dismissing and retyping it', async () => {
    const { input, user } = setup()
    await user.type(input, '/status'); await user.keyboard('{Escape}')
    await user.clear(input); await user.type(input, '/status')
    await expect(screen.findByRole('option', { name: /\/status/u })).resolves.toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(await screen.findByText('当前对话状态')).toBeInTheDocument()
  })
  it('opens Skills from slash and mouse selection restores the caret', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/skills'); await user.keyboard('{Enter}')
    expect(screen.queryByRole('option', { name: /\/new/u })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('option', { name: /weather/u }))
    await waitFor(() => expect(input).toHaveFocus())
    expect(input.selectionStart).toBe(0)
    expect(chat.send).not.toHaveBeenCalled()
  })
  it('disables Skill candidates for tool-free source snapshots', async () => {
    const { input, user, chat } = setup({ sourceSnapshot: { sourceName: '只读来源', itemCount: 1, windowLabel: '今日', items: [] } as never })
    await user.type(input, '@天气')
    const option = await screen.findByRole('option', { name: /weather/u })
    expect(option).toHaveAttribute('aria-disabled', 'true')
    expect(option).toHaveTextContent('来源快照禁止调用工具')
    await user.click(option)
    expect(screen.queryByText('Skill：weather')).not.toBeInTheDocument()
    expect(chat.send).not.toHaveBeenCalled()
  })
})
