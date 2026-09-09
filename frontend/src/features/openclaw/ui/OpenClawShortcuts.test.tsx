import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, userEvent, chatController } from '../OpenClawConversation.test.support'
import { OpenClawWorkbenchPanel } from '../adapters/OpenClawConversation'
import { createWorkbenchAgentValue } from '../../workbench-live/createWorkbenchAgentValue'
import type { AgentContextDraftV6 } from '../../workbench-live/agentContext'
import type { OpenClawChatController } from '../openclawContracts'

const skill = { key: 'weather', name: 'weather', description: '天气查询', enabled: true, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true, missingBins: [], missingEnv: [], installOptions: [] }
function setup(initial: Partial<AgentContextDraftV6> = {}, overrides: Partial<OpenClawChatController> = {}) {
  const skillsStatus = vi.fn().mockResolvedValue({ skills: [skill] })
  const chat = chatController({ status: 'connected', sessionKey: 'root', workspace: {
    skillScope: () => ({ agentId: 'main', generation: 1 }), capabilities: () => ({ 'skills.status': true }),
    subscribe: () => () => {}, skillsStatus,
  }, ...overrides }) as unknown as OpenClawChatController
  function Harness() {
    const [draft, setDraft] = useState<AgentContextDraftV6>({ userId: 'test', items: [], question: '', ...initial })
    const value = { ...createWorkbenchAgentValue(draft, setDraft), openComposer: vi.fn() }
    return <OpenClawWorkbenchPanel chat={chat} value={value} />
  }
  render(<Harness />)
  return { chat, skillsStatus, input: screen.getByRole('textbox', { name: '发送给 OpenClaw 的问题' }) as HTMLTextAreaElement, user: userEvent.setup() }
}
describe('shared Composer shortcuts', () => {
  it('shows readable actions and rejects the retired Worktree command locally', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/')
    expect(await screen.findByRole('option', { name: /选择技能/ })).toBeVisible()
    expect(screen.queryByRole('option', { name: /worktree/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /\/skills/ })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: /\/help/ })).toBeVisible()
    expect(screen.queryByText('快捷选择')).not.toBeInTheDocument()
    expect(screen.getByRole('listbox')).toHaveAccessibleDescription('↑↓ 选择 · Enter 确认 · Esc 关闭')
    await user.clear(input); await user.type(input, '/worktree'); await user.keyboard('{Escape}{Enter}')
    expect(await screen.findByText('此工作区用于聊天与 Skill 调用，不提供 Worktree 任务。')).toBeVisible()
    expect(chat.send).not.toHaveBeenCalled()
    expect(chat.newConversation).not.toHaveBeenCalled()
  })
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
  it('groups Skills and attached materials only when both are present', async () => {
    const { input, user, chat } = setup({ items: [{ articleId: 'one', title: '阅读材料', sourceName: '测试' }] })
    await user.type(input, '总结 @')
    await screen.findByRole('option', { name: /weather/u })
    expect(screen.getByText('Skills', { selector: 'p' })).not.toHaveClass('sr-only')
    expect(screen.getByText('已附带材料', { selector: 'p' })).not.toHaveClass('sr-only')
    await user.keyboard('{Escape}')
    expect(input).toHaveFocus()
    expect(input).toHaveValue('总结 @')
    expect(chat.send).not.toHaveBeenCalled()
  })
  it('dismisses slash and at-sign suggestions when pressing outside', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/')
    expect(await screen.findByRole('listbox', { name: 'Agent 快捷候选' })).toBeVisible()
    await user.click(document.body)
    expect(screen.queryByRole('listbox', { name: 'Agent 快捷候选' })).not.toBeInTheDocument()
    expect(input).toHaveValue('/')
    expect(chat.send).not.toHaveBeenCalled()
    await user.click(input); await user.clear(input); await user.type(input, '@')
    expect(await screen.findByRole('listbox', { name: 'Agent 快捷候选' })).toBeVisible()
    await user.click(document.body)
    expect(screen.queryByRole('listbox', { name: 'Agent 快捷候选' })).not.toBeInTheDocument()
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
    expect(await screen.findByRole('region', { name: '/new 命令结果' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(chat.newConversation).not.toHaveBeenCalled()
    expect(input).toHaveValue('待发送 ')
  })
  it('help and status are local reads and help documents the shortcuts', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/status'); await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/status 命令结果' })).toHaveTextContent('当前对话状态')
    expect(screen.getByRole('region', { name: '/status 命令结果' })).toHaveTextContent('暂无可信用量')
    expect(chat.send).not.toHaveBeenCalled()
    await user.type(input, '/help'); await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/help 命令结果' })).toHaveTextContent('快捷输入')
    expect(chat.newConversation).not.toHaveBeenCalled()
  })
  it('dismisses a command panel when pressing outside without sending', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/help'); await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/help 命令结果' })).toBeVisible()
    await user.click(document.body)
    expect(screen.queryByRole('region', { name: '/help 命令结果' })).not.toBeInTheDocument()
    expect(chat.send).not.toHaveBeenCalled()
  })
  it('reopens the same command after dismissing and retyping it', async () => {
    const { input, user } = setup()
    await user.type(input, '/status'); await user.keyboard('{Escape}')
    await user.clear(input); await user.type(input, '/status')
    await expect(screen.findByRole('option', { name: /查看状态/u })).resolves.toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/status 命令结果' })).toHaveTextContent('当前对话状态')
  })
  it('opens Skills from slash and mouse selection restores the caret', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/skills'); await user.keyboard('{Enter}')
    expect(screen.queryByRole('option', { name: /\/new/u })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: '使用 weather' }))
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

describe('temporary slash command panels', () => {
  it('opens Skills above the composer and leaves slash in command mode with the surrounding draft intact', async () => {
    const { input, user, chat } = setup({ question: '前文 /skills 后文' })
    input.focus(); input.setSelectionRange(10, 10); fireEvent.select(input)
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/skills 命令结果' })).toBeVisible()
    expect(input).toHaveValue('前文  后文')
    expect(input.selectionStart).toBe(3)
    expect(input).toHaveFocus()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await user.keyboard('/')
    expect(screen.getByRole('option', { name: /查看状态/u })).toBeVisible()
    expect(screen.queryByRole('option', { name: /weather/u })).not.toBeInTheDocument()
    expect(chat.send).not.toHaveBeenCalled()
  })

  it('only reads Skills on explicit invocation and allows another command without dismissing a submenu', async () => {
    const { input, user, skillsStatus, chat } = setup()
    await user.type(input, '/')
    expect(skillsStatus).not.toHaveBeenCalled()
    await user.keyboard('skills{Enter}')
    await screen.findByRole('button', { name: '使用 weather' })
    await user.type(input, '/status'); await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/status 命令结果' })).toBeVisible()
    expect(screen.queryByRole('region', { name: '/skills 命令结果' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(chat.send).not.toHaveBeenCalled()
  })

  it('dispatches a known command through the send button even after Escape and trailing whitespace', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/status '); await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))
    expect(await screen.findByRole('region', { name: '/status 命令结果' })).toBeVisible()
    expect(input).toHaveValue('')
    expect(chat.send).not.toHaveBeenCalled()
  })

  it('reports an empty Skill directory inside the conversation and leaves the composer usable', async () => {
    const { input, user, skillsStatus, chat } = setup()
    skillsStatus.mockResolvedValue({ skills: [] })
    await user.type(input, '/skills'); await user.keyboard('{Enter}')
    expect(await screen.findByText('没有匹配的 Skills。')).toBeVisible()
    expect(input).toHaveValue('')
    await user.type(input, '/help'); await user.keyboard('{Enter}')
    expect(await screen.findByRole('region', { name: '/help 命令结果' })).toBeVisible()
    expect(chat.send).not.toHaveBeenCalled()
  })
})

describe('inline command write guards', () => {
  it('keeps model selection inline, preserves the draft on failure and locks repeated activation', async () => {
    let resolve!: (value: boolean) => void
    const setModel = vi.fn().mockImplementation(() => new Promise<boolean>((done) => { resolve = done }))
    const { input, user, chat } = setup({}, {
      models: [{ id: 'provider/a', name: 'Model A', provider: 'provider', supportsImages: false }, { id: 'provider/b', name: 'Model B', provider: 'provider', supportsImages: false }],
      runtimeSelection: { modelId: 'provider/a', thinkingLevel: null, defaultModelId: null, defaultThinkingLevel: null }, setModel,
    })
    await user.type(input, '保留草稿 /model'); await user.keyboard('{Enter}')
    const choose = await screen.findByRole('button', { name: '选择 Model B' })
    await user.dblClick(choose)
    expect(setModel).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(input).toHaveValue('保留草稿 ')
    resolve(false)
    await screen.findByText(/设置未完成，当前会话和草稿仍保留/u)
    expect(input).toHaveValue('保留草稿 ')
    await waitFor(() => expect(choose).toBeEnabled())
    expect(chat.send).not.toHaveBeenCalled()
  })

  it('cancels old confirmations when a later command is issued and never includes local output in chat', async () => {
    const { input, user, chat } = setup()
    await user.type(input, '/new'); await user.keyboard('{Enter}')
    await screen.findByRole('button', { name: '确认新建' })
    await user.type(input, '/help'); await user.keyboard('{Enter}')
    expect(screen.queryByRole('button', { name: '确认新建' })).not.toBeInTheDocument()
    await user.type(input, '普通问题'); await user.keyboard('{Enter}')
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({ displayText: '普通问题' }))
    const request = vi.mocked(chat.send).mock.calls[0][0]
    expect(request.gatewayPrompt).not.toContain('快捷输入')
    expect(request.gatewayPrompt).not.toContain('新建对话？')
    expect(chat.newConversation).not.toHaveBeenCalled()
  })
})

it('runs read-only slash commands even when a conflicting Skill and source snapshot block chat sending', async () => {
  const { input, user, chat } = setup({
    sourceSnapshot: { sourceName: '快照', itemCount: 1, windowLabel: '今日', items: [] } as never,
    selectedSkill: { key: 'weather', name: 'weather', gatewayUrl: 'ws://127.0.0.1:18789', agentId: 'main' },
  })
  await user.type(input, '/status')
  await user.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))
  expect(await screen.findByRole('region', { name: '/status 命令结果' })).toBeVisible()
  expect(screen.getByText('Skill：weather')).toBeInTheDocument()
  expect(chat.send).not.toHaveBeenCalled()
})
