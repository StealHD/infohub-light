import { describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, OpenClawActivityTrace, OpenClawConversation, gatewayOriginSetupCommands, contextValue, chatController } from './OpenClawConversation.test.support'

describe('OpenClaw conversation surface', () => {


  it('lists every retained completed step with its status and duration', async () => {
    const browser = userEvent.setup()
    render(<OpenClawActivityTrace
      running={false}
      trace={{
        runId: 'run-fast',
        phase: 'completed',
        status: 'completed',
        startedAt: 1_000,
        endedAt: 3_000,
        activities: [
          { id: 'tool-fast', label: '读取任务详情', status: 'completed', startedAt: 1_100, endedAt: 1_300 },
          { id: 'tool-slow', label: '检查来源健康', status: 'completed', startedAt: 1_400, endedAt: 2_200 },
        ],
      }}
    />)

    const toggle = screen.getByRole('button', { name: /已完成 2 个步骤/u })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await browser.click(toggle)
    expect(screen.getByText('读取任务详情').parentElement).toHaveTextContent(/读取任务详情\s*· 已完成 · 0\.2秒/u)
    expect(screen.getByText('检查来源健康').parentElement).toHaveTextContent(/检查来源健康\s*· 已完成 · 0\.8秒/u)
    expect(screen.queryByText(/快速步骤/u)).not.toBeInTheDocument()
  })


  it('states clearly when a run is stopped before any answer text arrives', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      runTrace: {
        runId: 'run-aborted-empty',
        phase: 'aborted',
        status: 'aborted',
        startedAt: 1_000,
        endedAt: 2_000,
        activities: [],
      },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByText('已停止，未生成回答')).toBeInTheDocument()
  })


  it('offers suggestions without auto-sending and exposes reconnect recovery next to the composer', async () => {
    const browser = userEvent.setup()
    const value = contextValue()
    const chat = chatController({
      status: 'reconnecting',
      sessionKey: 'session-1',
      reconnectAttempt: 2,
    })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    await browser.click(screen.getByRole('button', { name: '排查采集链路' }))
    expect(value.setQuestion).toHaveBeenCalledWith('请检查我最近失败的采集任务和异常来源，结合任务诊断、来源健康与可用的操作记录，按影响范围列出可能原因、证据和下一步；证据不足时明确说明，先不要修改配置或重试。')
    expect(chat.send).not.toHaveBeenCalled()
    expect(screen.getByLabelText('进阶建议任务')).toHaveClass('prompt-suggestion__items')
    expect(screen.getByRole('button', { name: '研判近期信号' })).toHaveClass('prompt-suggestion__item')
    expect(screen.getByText('连接中断，正在重连 · 第 2 次')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '立即重试' }))
    expect(chat.retryConnection).toHaveBeenCalledTimes(1)
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

    expect(screen.getByTestId('agent-scroll-region')).toHaveClass('flex-1', 'overflow-y-auto', 'overscroll-contain')
    expect(screen.getByTestId('openclaw-composer-dock')).toHaveClass('shrink-0', 'overflow-hidden')
    expect(screen.getByRole('textbox', { name: '发送给 OpenClaw 的问题' })).toHaveClass('overflow-y-auto', 'overscroll-y-contain')
  })


  it('uses a right-aligned user bubble while keeping assistant messages flat and links safe', async () => {
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
    await screen.findByText('执行')

    const timeline = screen.getByTestId('openclaw-timeline')
    expect(timeline).toHaveClass('grid-cols-[12px_minmax(0,1fr)]')
    expect(timeline.querySelectorAll('[data-chat-marker]')).toHaveLength(2)
    expect(timeline.querySelector('[class*="bg-accent/12"]')).toBeNull()
    expect(timeline.querySelector('[class*="bg-surface-secondary"]')).toBeNull()
    for (const body of timeline.querySelectorAll('[data-chat-message-body]')) {
      expect(body).toHaveClass('type-chat')
    }

    const userMessage = screen.getByRole('article', { name: '你的消息' })
    expect(userMessage).toHaveClass('col-span-2', 'items-end')
    expect(userMessage.querySelector('[data-chat-message-bubble]')).toHaveClass('max-w-[85%]', 'rounded-2xl', 'bg-default')
    expect(screen.queryByText('你')).not.toBeInTheDocument()
    const userTime = userMessage.querySelector('time')
    expect(userTime).toHaveTextContent('14:32')
    expect(userTime).toHaveAttribute('title', '2026-07-22 14:32:00')
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
    expect(timeline).toHaveTextContent('执行 <b>plain</b>')
    expect(timeline.querySelector('b')).toBeNull()
  })


  it('keeps full-workspace user and assistant turns in one vertical grid column', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      messages: [
        { id: 'user-1', role: 'user', text: '检查任务', status: 'sent', createdAt: 1_000 },
        { id: 'assistant-1', role: 'assistant', text: '第一步', status: 'sent', createdAt: 2_000 },
        { id: 'assistant-2', role: 'assistant', text: '第二步', status: 'sent', createdAt: 3_000 },
      ],
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} variant="workspace" />)

    const timeline = screen.getByTestId('openclaw-timeline')
    expect(timeline).toHaveClass('grid-cols-1')
    expect(screen.getByRole('article', { name: '你的消息' })).not.toHaveClass('col-span-2')
    const articles = timeline.querySelectorAll('article')
    expect(articles).toHaveLength(3)
    expect(Array.from(articles).every((article) => !article.classList.contains('border-b'))).toBe(true)
    expect(timeline.querySelectorAll('[data-chat-marker]')).toHaveLength(2)
  })


  it('explains unavailable thinking inside the shared runtime picker', async () => {
    const browser = userEvent.setup()
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [{ id: 'local/quick', name: 'Quick', provider: 'local', reasoning: false }],
      thinkingOptions: [],
      runtimeSelection: { modelId: 'local/quick', thinkingLevel: null, defaultModelId: 'local/quick', defaultThinkingLevel: null },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    await browser.click(screen.getByRole('button', { name: 'OpenClaw 模型：Quick，思考程度：选择思考' }))
    expect(screen.getByText('此模型未提供推理档位。')).toBeVisible()
    expect(screen.getByRole('slider', { name: '思考程度' })).toBeDisabled()
    expect(screen.queryByRole('option', { name: '速度优先' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '深度分析' })).not.toBeInTheDocument()
  })


  it('does not invent thinking choices when OpenClaw returns no model-level options', async () => {
    const browser = userEvent.setup()
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      models: [{ id: 'openai/plain', name: 'Plain', provider: 'openai', reasoning: true }],
      thinkingOptions: [],
      runtimeSelection: { modelId: 'openai/plain', thinkingLevel: null, defaultModelId: 'openai/plain', defaultThinkingLevel: null },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    await browser.click(screen.getByRole('button', { name: 'OpenClaw 模型：Plain，思考程度：选择思考' }))
    expect(screen.getByText('OpenClaw 未返回此模型的可选推理档位。')).toBeVisible()
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
    expect(value.restoreComposer).toHaveBeenCalledWith('分析机会', snapshot.contextItems, undefined, undefined)
  })


  it('builds Origin repair commands that append without a wildcard', () => {
    const commands = gatewayOriginSetupCommands('https://rb.jiefs.top')
    expect(commands.shell).toContain('new Set([...xs, process.argv[2]])')
    expect(commands.powershell).toContain('Sort-Object -Unique')
    expect(`${commands.shell}\n${commands.powershell}`).not.toContain('allowedOrigins:["*"]')
    expect(`${commands.shell}\n${commands.powershell}`).not.toContain('allowedOrigins ["*"]')
  })
})
