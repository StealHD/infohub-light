import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import { OpenClawContextUsageIndicator, OpenClawConversation, gatewayOriginSetupCommands } from './OpenClawConversation'

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
    streamCreatedAt: null,
    issue: null,
    runtimeIssue: null,
    modelSwitchFallback: null,
    contextUsage: null,
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
    switchToBlankConversation: vi.fn().mockResolvedValue(true),
    newConversation: vi.fn(),
    ...overrides,
  }
}

describe('OpenClaw conversation surface', () => {
  it('shows only trustworthy current-session context usage beside the runtime controls', async () => {
    const browser = userEvent.setup()
    render(<OpenClawContextUsageIndicator
      usage={{
        sessionKey: 'session-usage',
        usedTokens: 42_000,
        contextTokens: 200_000,
        percent: 21,
        modelId: 'openai/gpt-5.4',
      }}
    />)

    const trigger = screen.getByRole('button', { name: '上下文占用 21%' })
    expect(screen.getByRole('progressbar', { name: '上下文占用' })).toHaveAttribute('aria-valuenow', '21')
    await browser.hover(trigger)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(/42[,.]?000 \/ 200[,.]?000 · 21%/u)
    expect(screen.queryByText('openai/gpt-5.4')).not.toBeInTheDocument()
    expect(screen.queryByText('背景信息')).not.toBeInTheDocument()
  })

  it('renders an accessible neutral ring when current-session usage is not trustworthy', async () => {
    const browser = userEvent.setup()
    render(<OpenClawContextUsageIndicator usage={null} />)

    const progress = screen.getByRole('progressbar', { name: '上下文占用' })
    expect(progress).not.toHaveAttribute('aria-valuenow')
    expect(progress).toHaveAttribute('aria-valuetext', '暂无可信用量')
    await browser.hover(screen.getByRole('button', { name: '上下文占用暂无可信用量' }))
    expect(await screen.findByRole('tooltip')).toHaveTextContent('暂无可信用量')
  })

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

  it('keeps both setup actions in one bounded two-column row', () => {
    const chat = chatController()
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    const actions = screen.getByTestId('openclaw-setup-actions')
    expect(actions).toHaveClass('grid', 'min-w-0', 'grid-cols-2')
    expect(screen.getByRole('button', { name: '连接并授权' })).toHaveClass(
      'min-w-0',
      'whitespace-normal',
      '[overflow-wrap:anywhere]',
    )
    expect(screen.getByRole('button', { name: '使用已配对设备重连' })).toHaveClass(
      'min-w-0',
      'whitespace-normal',
      '[overflow-wrap:anywhere]',
    )
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

  it('keeps the send and stop actions in one stable tooltip trigger slot', () => {
    const idleChat = chatController({ status: 'connected', sessionKey: 'session-1' })
    const view = render(<OpenClawConversation chat={idleChat as never} value={contextValue({ question: '继续' })} />)
    const toolbar = screen.getByTestId('openclaw-composer-toolbar')
    const sendButton = screen.getByRole('button', { name: '发送给 OpenClaw' })

    expect(toolbar.lastElementChild).toBe(sendButton)
    expect(sendButton).toHaveAttribute('data-slot', 'tooltip-trigger')
    expect(sendButton).toHaveClass('size-9', 'shrink-0', 'rounded-full', 'bg-accent', 'text-accent-foreground')
    expect(sendButton).not.toHaveClass('bg-transparent')

    const runningChat = chatController({ status: 'connected', sessionKey: 'session-1', isRunning: true })
    view.rerender(<OpenClawConversation chat={runningChat as never} value={contextValue()} />)
    const stopButton = screen.getByRole('button', { name: '停止生成' })

    expect(stopButton).toBe(sendButton)
    expect(toolbar.lastElementChild).toBe(stopButton)
    expect(stopButton).toHaveAttribute('data-slot', 'tooltip-trigger')
    expect(stopButton).toHaveClass('size-9', 'shrink-0', 'rounded-full')
  })

  it('uses separate model and thinking selectors with verified runtime actions', async () => {
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
      contextUsage: { sessionKey: 'session-1', usedTokens: 10_000, contextTokens: 200_000, percent: 5 },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.queryByRole('button', { name: /OpenClaw 运行设置/ })).not.toBeInTheDocument()
    const runtime = screen.getByTestId('openclaw-runtime-controls')
    expect(runtime.firstElementChild).toBe(screen.getByRole('button', { name: '上下文占用 5%' }))
    await browser.click(screen.getByRole('button', { name: 'OpenClaw 模型：GPT-5.4' }))
    expect(screen.getByText('openai')).toBeInTheDocument()
    expect(screen.getByText('local')).toBeInTheDocument()
    const selectedModel = screen.getByRole('option', { name: /GPT-5.4/ })
    expect(selectedModel).toHaveAttribute('aria-selected', 'true')
    expect(selectedModel.querySelector('[data-slot="list-box-item-indicator"][data-visible]')).toBeInTheDocument()
    await browser.click(screen.getByRole('option', { name: /Quick/ }))
    expect(chat.setModel).toHaveBeenCalledWith('local/quick')

    await browser.click(screen.getByRole('button', { name: 'OpenClaw 思考程度：高' }))
    const selectedThinking = screen.getByRole('option', { name: '高' })
    expect(selectedThinking).toHaveAttribute('aria-selected', 'true')
    expect(selectedThinking.querySelector('[data-slot="list-box-item-indicator"][data-visible]')).toBeInTheDocument()
    await browser.click(screen.getByRole('option', { name: '低' }))
    expect(chat.setThinking).toHaveBeenCalledWith('low')
  })

  it('keeps the connected composer input and actions in stable grid tracks', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [{ id: 'provider/long-model', name: 'A deliberately long model name', provider: 'provider', reasoning: true }],
      thinkingOptions: [{ id: 'high', label: '深度分析' }],
      runtimeSelection: { modelId: 'provider/long-model', thinkingLevel: 'high', defaultModelId: null, defaultThinkingLevel: null },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByTestId('openclaw-composer')).toHaveClass('grid', 'grid-rows-[minmax(96px,auto)_36px]', 'gap-2')
    expect(screen.getByLabelText('发送给 OpenClaw 的问题')).toHaveClass('min-h-24')
    expect(screen.getByTestId('openclaw-composer-toolbar')).toHaveClass('grid', 'grid-cols-[minmax(0,1fr)_36px]')
    expect(screen.getByTestId('openclaw-composer-toolbar')).not.toHaveClass('mt-2')
    expect(screen.getByRole('button', { name: '发送给 OpenClaw' })).toHaveClass('size-9', 'shrink-0')
    expect(screen.getByTestId('openclaw-runtime-controls')).toHaveClass('grid', 'grid-cols-[auto_minmax(0,1fr)_auto]')
    expect(screen.getByRole('button', { name: 'OpenClaw 模型：A deliberately long model name' })).toHaveClass('w-full', 'min-w-0')
    expect(screen.getByRole('button', { name: 'OpenClaw 思考程度：深度分析' })).toHaveClass('shrink-0')
  })

  it('keeps a long connected transcript scrolling above an unshrunk composer', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      messages: Array.from({ length: 24 }, (_, index) => ({
        id: `message-${index}`,
        role: index % 2 === 0 ? 'user' : 'assistant',
        text: `long transcript message ${index}`,
        status: 'completed',
        contextCount: 0,
      })),
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByTestId('agent-scroll-region')).toHaveClass('flex-1')
    expect(screen.getByTestId('openclaw-composer-dock')).toHaveClass('shrink-0')
  })

  it('uses the approved flat C2 timeline with inline local times and safe http links', () => {
    const now = new Date(2026, 6, 22, 15, 0, 0).getTime()
    vi.spyOn(Date, 'now').mockReturnValue(now)
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      messages: [
        {
          id: 'user-1',
          role: 'user',
          text: '打开 https://example.com/docs。',
          status: 'sent',
          createdAt: new Date(2026, 6, 22, 14, 32, 0).getTime(),
        },
        {
          id: 'assistant-1',
          role: 'assistant',
          text: '参考 [研究资料](https://example.com/research)，但保留 [执行](javascript:alert(1)) <b>plain</b>。',
          status: 'sent',
          createdAt: new Date(2026, 6, 21, 9, 5, 0).getTime(),
        },
        { id: 'assistant-2', role: 'assistant', text: '没有有效时间', status: 'sent', createdAt: Number.NaN },
      ],
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    const timeline = screen.getByTestId('openclaw-timeline')
    expect(timeline).toHaveClass('grid-cols-[12px_minmax(0,1fr)]')
    expect(timeline.querySelectorAll('[data-chat-marker]')).toHaveLength(3)
    expect(timeline.querySelector('.rounded-2xl')).toBeNull()
    expect(timeline.querySelector('[class*="bg-accent/12"]')).toBeNull()
    expect(timeline.querySelector('[class*="bg-surface-secondary"]')).toBeNull()
    for (const body of timeline.querySelectorAll('[data-chat-message-body]')) {
      expect(body).toHaveClass('type-chat')
    }

    const userRole = screen.getByText('你')
    expect(userRole.nextElementSibling?.tagName).toBe('TIME')
    expect(userRole.nextElementSibling).toHaveTextContent('14:32')
    expect(userRole.nextElementSibling).toHaveAttribute('title', '2026-07-22 14:32:00')
    expect(screen.getByText('07-21 09:05')).toBeInTheDocument()
    expect(timeline.querySelectorAll('time')).toHaveLength(2)
    expect(screen.getAllByText('OpenClaw')).toHaveLength(2)

    const bareLink = screen.getByRole('link', { name: 'https://example.com/docs' })
    const labelledLink = screen.getByRole('link', { name: '研究资料' })
    for (const link of [bareLink, labelledLink]) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
      expect(link).toHaveClass('text-accent')
    }
    expect(screen.getAllByRole('link')).toHaveLength(2)
    expect(timeline).toHaveTextContent('[执行](javascript:alert(1)) <b>plain</b>')
    expect(timeline.querySelector('b')).toBeNull()
  })

  it('disables thinking at automatic when the selected model does not reason', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [{ id: 'local/quick', name: 'Quick', provider: 'local', reasoning: false }],
      thinkingOptions: [],
      runtimeSelection: { modelId: 'local/quick', thinkingLevel: null, defaultModelId: 'local/quick', defaultThinkingLevel: null },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByRole('button', { name: 'OpenClaw 模型：Quick' })).toBeInTheDocument()
    const thinking = screen.getByRole('button', { name: 'OpenClaw 思考程度：自动' })
    expect(thinking).toBeDisabled()
    expect(document.getElementById(thinking.getAttribute('aria-describedby') ?? '')).toHaveTextContent('此模型未提供推理档位。')
    expect(thinking.closest('[title]')).toHaveAttribute('title', '此模型未提供推理档位。')
    expect(screen.queryByRole('option', { name: '速度优先' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '深度分析' })).not.toBeInTheDocument()
  })

  it('does not invent thinking choices when OpenClaw returns no model-level options', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [{ id: 'openai/plain', name: 'Plain', provider: 'openai', reasoning: true }],
      thinkingOptions: [],
      runtimeSelection: { modelId: 'openai/plain', thinkingLevel: null, defaultModelId: 'openai/plain', defaultThinkingLevel: null },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    const thinking = screen.getByRole('button', { name: 'OpenClaw 思考程度：自动' })
    expect(thinking).toBeDisabled()
    expect(document.getElementById(thinking.getAttribute('aria-describedby') ?? '')).toHaveTextContent(
      'OpenClaw 未返回此模型的可选推理档位。',
    )
    expect(thinking.closest('[title]')).toHaveAttribute('title', 'OpenClaw 未返回此模型的可选推理档位。')
  })

  it('offers an explicit blank-conversation fallback without exposing Gateway scope errors', async () => {
    const browser = userEvent.setup()
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      runtimeIssue: '当前对话过长，无法在保留上下文的同时切换模型。',
      modelSwitchFallback: { modelId: 'openai/gpt-5.4', modelName: 'GPT-5.4' },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(document.body.textContent).not.toContain('operator.admin')
    await browser.click(screen.getByRole('button', { name: '新建空白对话并切换到 GPT-5.4' }))
    expect(chat.switchToBlankConversation).toHaveBeenCalledTimes(1)
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
