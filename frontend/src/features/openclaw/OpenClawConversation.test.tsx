import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import { OpenClawConversation, gatewayOriginSetupCommands } from './OpenClawConversation'

function contextValue(overrides: Partial<WorkbenchAgentContextValue['draft']> = {}): WorkbenchAgentContextValue {
  return {
    draft: {
      userId: 'user-a',
      question: '',
      items: [],
      ...overrides,
    },
    toggleItem: vi.fn(),
    removeItem: vi.fn(),
    openComposer: vi.fn(),
    setQuestion: vi.fn(),
    clearComposer: vi.fn(),
    restoreComposer: vi.fn(),
  }
}

function chatController(overrides: Record<string, unknown> = {}) {
  return {
    gatewayUrl: 'ws://127.0.0.1:18789',
    setGatewayUrl: vi.fn(),
    status: 'idle',
    toolsStatus: 'unknown',
    messages: [],
    streamText: '',
    issue: null,
    runtimeIssue: null,
    sessionKey: null,
    isRunning: false,
    isStopping: false,
    runtimeLoading: false,
    runtimeUpdating: false,
    models: [],
    thinkingOptions: [],
    runtimeSelection: { modelId: null, thinkingLevel: null, defaultModelId: null, defaultThinkingLevel: null },
    connect: vi.fn().mockResolvedValue(true),
    disconnect: vi.fn(),
    forget: vi.fn(),
    send: vi.fn().mockResolvedValue(true),
    retry: vi.fn().mockResolvedValue(true),
    takeFailedMessage: vi.fn(),
    stop: vi.fn(),
    setModel: vi.fn().mockResolvedValue(true),
    setThinking: vi.fn().mockResolvedValue(true),
    newConversation: vi.fn(),
    ...overrides,
  }
}

describe('OpenClaw conversation surface', () => {
  it('keeps the disabled mode local and never asks for a Gateway credential', () => {
    const chat = chatController({ status: 'disabled' })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByText('站内 OpenClaw 对话尚未启用；仍可复制交接提示词到自己的 OpenClaw。')).toBeInTheDocument()
    expect(screen.queryByLabelText('OpenClaw Gateway token')).not.toBeInTheDocument()
    expect(chat.connect).not.toHaveBeenCalled()
  })

  it('clears the bootstrap token field immediately after a successful connection', async () => {
    const browser = userEvent.setup()
    const chat = chatController()
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    const token = screen.getByLabelText('OpenClaw Gateway token')
    await browser.type(token, 'gateway-secret')
    await browser.click(screen.getByRole('button', { name: '连接并授权' }))

    await waitFor(() => expect(chat.connect).toHaveBeenCalledWith('gateway-secret', 'ws://127.0.0.1:18789'))
    expect(token).toHaveValue('')
    expect(document.body.textContent).not.toContain('gateway-secret')
  })

  it('can reconnect with a stored browser pairing without asking for the token again', async () => {
    const browser = userEvent.setup()
    const chat = chatController()
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    await browser.click(screen.getByRole('button', { name: '使用已配对设备重连' }))

    expect(chat.connect).toHaveBeenCalledWith(undefined, 'ws://127.0.0.1:18789')
    expect(screen.getByLabelText('OpenClaw Gateway token')).toHaveValue('')
  })

  it('sends a concise visible message, keeps the MCP prompt private and clears the composer immediately', async () => {
    const browser = userEvent.setup()
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    const value = contextValue({
      question: '比较这两篇文章',
      items: [
        { articleId: 'article-1', title: '标题一', sourceName: '来源一' },
        { articleId: 'article-2', title: '标题二', sourceName: '来源二' },
        { articleId: 'article-3', title: '标题三', sourceName: '来源三' },
      ],
    })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    expect(screen.getByLabelText('已附带 3 条信息')).toHaveTextContent('来源一 · 标题一')
    expect(document.querySelectorAll('[data-composer-context-item]')).toHaveLength(2)
    await browser.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))

    expect(value.clearComposer).toHaveBeenCalledTimes(1)
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({
      displayText: '比较这两篇文章',
      gatewayPrompt: expect.stringContaining('article_id="article-1"'),
      contextItems: value.draft.items,
    }))
    const request = chat.send.mock.calls[0][0]
    expect(request.gatewayPrompt).toContain('article_id="article-3"')
    expect(request.displayText).not.toContain('article_id=')
  })

  it('uses an attachment-count fallback when the user sends without a question', async () => {
    const browser = userEvent.setup()
    const chat = chatController({ status: 'connected', sessionKey: 'session-1' })
    const value = contextValue({ items: [{ articleId: 'article-1', title: '标题一' }] })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    await browser.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({ displayText: '分析已附带的 1 条信息' }))
  })

  it('uses an in-place icon-only stop action and keeps runtime controls disabled while generating', () => {
    const chat = chatController({ status: 'connected', sessionKey: 'session-1', isRunning: true })
    render(<OpenClawConversation chat={chat as never} value={contextValue({ question: '继续' })} />)

    expect(screen.getByRole('button', { name: '停止生成' })).toBeInTheDocument()
    expect(screen.queryByText(/^停止$/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '新对话' })).toBeDisabled()
  })

  it('renders configured Gateway models and patches the selected model for this conversation', async () => {
    const browser = userEvent.setup()
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [
        { id: 'openai/gpt-5.4', name: 'GPT-5.4', provider: 'openai', contextWindow: 200_000, reasoning: true },
        { id: 'local/quick', name: 'Quick', provider: 'local', contextWindow: 32_000, reasoning: false },
      ],
      thinkingOptions: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }],
      runtimeSelection: { modelId: 'openai/gpt-5.4', thinkingLevel: 'high', defaultModelId: 'openai/gpt-5.4', defaultThinkingLevel: 'low' },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByLabelText('OpenClaw 模型')).toHaveValue('GPT-5.4 openai')
    await browser.click(screen.getByRole('button', { name: '选择 OpenClaw 模型' }))
    await browser.click(screen.getByRole('option', { name: /Quick/ }))
    expect(chat.setModel).toHaveBeenCalledWith('local/quick')
  })

  it('shows only the OpenClaw default thinking choice when the selected model does not reason', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [{ id: 'local/quick', name: 'Quick', provider: 'local', reasoning: false }],
      thinkingOptions: [],
      runtimeSelection: { modelId: 'local/quick', thinkingLevel: null, defaultModelId: 'local/quick', defaultThinkingLevel: null },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    const thinking = screen.getByRole('button', { name: /OpenClaw 推理档位$/ })
    expect(thinking).toBeDisabled()
    expect(thinking).toHaveTextContent('自动 · OpenClaw 默认')
    expect(screen.queryByText('速度优先')).not.toBeInTheDocument()
    expect(screen.queryByText('深度分析')).not.toBeInTheDocument()
  })

  it('offers retry and restore actions for a failed visible message', async () => {
    const browser = userEvent.setup()
    const snapshot = { displayText: '分析机会', gatewayPrompt: 'private prompt', contextItems: [{ articleId: 'a', title: 'A' }], idempotencyKey: 'send-1' }
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      messages: [{ id: 'send-1', role: 'user', text: '分析机会', status: 'failed', contextCount: 1, sendSnapshot: snapshot }],
      takeFailedMessage: vi.fn().mockReturnValue(snapshot),
    })
    const value = contextValue()
    render(<OpenClawConversation chat={chat as never} value={value} />)

    expect(screen.getByText('分析机会')).toBeInTheDocument()
    expect(screen.queryByText('private prompt')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '重试' }))
    expect(chat.retry).toHaveBeenCalledWith('send-1')
    await browser.click(screen.getByRole('button', { name: '重新编辑' }))
    expect(value.restoreComposer).toHaveBeenCalledWith('分析机会', snapshot.contextItems)
  })

  it('builds Origin repair commands that append without a wildcard', () => {
    const commands = gatewayOriginSetupCommands('https://rb.jiefs.top')
    expect(commands.shell).toContain('new Set([...xs, process.argv[2]])')
    expect(commands.powershell).toContain('Sort-Object -Unique')
    expect(`${commands.shell}\n${commands.powershell}`).not.toContain('allowedOrigins:["*"]')
    expect(`${commands.shell}\n${commands.powershell}`).not.toContain('allowedOrigins ["*"]')
  })
})
