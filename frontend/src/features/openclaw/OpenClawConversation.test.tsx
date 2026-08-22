import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen, waitFor, userEvent, OpenClawContextUsageIndicator, OpenClawConversation, contextValue, chatController } from './OpenClawConversation.test.support'

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

    const trigger = screen.getByRole('button', { name: '上下文占用 42k / 200k，21%' })
    expect(screen.getByRole('progressbar', { name: '上下文占用' })).toHaveAttribute('aria-valuenow', '21')
    await browser.hover(trigger)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('42k / 200k · 21%')
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
    expect(document.querySelectorAll('[data-composer-context-item]')).toHaveLength(3)
    expect(document.querySelector('[aria-hidden="true"][inert]')).toContainElement(screen.getByText('来源三 · 标题三'))
    await browser.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))

    expect(value.clearComposer).toHaveBeenCalledTimes(1)
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({
      displayText: '比较这两篇文章',
      gatewayPrompt: expect.stringContaining('article_id="article-1"'),
      contextItems: value.draft.items,
    }))
    const request = chat.send.mock.calls[0][0]
    expect(request.gatewayPrompt).toContain('"mode":"context_readonly"')
    expect(request.gatewayPrompt).toContain('article_id="article-3"')
    expect(request.gatewayPrompt).toContain('不得执行任何写操作')
    expect(request.displayText).not.toContain('article_id=')
  })


  it('shows clickable Chat Sources before send and beneath the sent user message', async () => {
    const browser = userEvent.setup()
    const source = { title: '标题一', sourceName: '来源一', url: 'https://example.com/article-1', sourceAvatarUrl: '/api/media/med_source_1' }
    const value = contextValue({
      items: [{ articleId: 'article-1', title: source.title, sourceName: source.sourceName, sourceUrl: source.url }],
    })
    const chat = chatController({
      status: 'connected',
      toolsStatus: 'available',
      sessionKey: 'session-1',
      messages: [{
        id: 'message-1',
        role: 'user',
        text: '分析这个来源',
        status: 'sent',
        contextCount: 1,
        contextSources: [source],
      }],
    })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    const sourceLinks = screen.getAllByRole('link', { name: '打开来源：标题一' })
    expect(sourceLinks).toHaveLength(2)
    expect(sourceLinks.every((link) => link.getAttribute('href') === source.url)).toBe(true)
    expect(sourceLinks.every((link) => link.classList.contains('flex-1'))).toBe(true)
    expect(document.querySelector('img[src="/api/media/med_source_1"]')).toBeInTheDocument()
    expect(sourceLinks[0].querySelector('.type-label')).not.toHaveClass('max-w-[220px]')
    expect(screen.queryByText('附带 1 条信息')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '移除来源：标题一' }))
    expect(value.removeItem).toHaveBeenCalledWith('article-1')
  })


  it('stretches the original summary upward for remaining attachments without a popover or duplicates', async () => {
    const browser = userEvent.setup()
    const value = contextValue({
      items: Array.from({ length: 3 }, (_, index) => ({
        articleId: `article-${index + 1}`,
        title: `标题 ${index + 1}`,
        sourceName: `来源 ${index + 1}`,
        sourceUrl: `https://example.com/article-${index + 1}`,
        sourceAvatarUrl: `/api/media/med_source_${index + 1}`,
      })),
    })
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    const summary = screen.getByLabelText('已附带 3 条信息')
    expect(summary).toHaveAttribute('data-context-summary-expanded', 'false')
    expect(document.querySelectorAll('[data-composer-context-item]')).toHaveLength(3)
    expect(document.querySelectorAll('img[src^="/api/media/med_source_"]')).toHaveLength(3)
    const expandRemaining = screen.getByRole('button', { name: '向上展开剩余 1 条信息' })
    expect(expandRemaining.querySelector('svg')).toBeInTheDocument()
    expect(expandRemaining).toHaveTextContent('已附带 3 条')
    expect(expandRemaining).toHaveClass('w-full', 'min-h-8', 'justify-start', 'pointer-coarse:min-h-11')
    expect(expandRemaining.firstElementChild?.textContent).toBe('已附带 3 条')
    expect(expandRemaining.lastElementChild?.tagName).toBe('svg')
    expect(screen.getByRole('button', { name: '移除全部 3 条信息' })).toHaveClass('size-8', 'pointer-coarse:size-11')
    expect(screen.queryByText('查看全部')).not.toBeInTheDocument()
    expect(Array.from(document.querySelectorAll('[data-composer-context-item] [data-chat-source]'))
      .every((source) => source.classList.contains('w-full'))).toBe(true)
    await browser.click(expandRemaining)

    expect(summary).toHaveAttribute('data-context-summary-expanded', 'true')
    expect(screen.getByRole('button', { name: '收起剩余 1 条信息' })).toHaveAttribute('aria-expanded', 'true')
    const remainder = document.getElementById(expandRemaining.getAttribute('aria-controls')!)!
    expect(remainder).toHaveAttribute('aria-hidden', 'false')
    expect(remainder).toHaveClass('grid-rows-[1fr]', 'duration-[var(--inteliscope-motion-deliberate)]')
    expect(remainder).toHaveTextContent('标题 3')
    expect(remainder).not.toHaveTextContent('标题 1')
    expect(remainder.querySelectorAll('[data-composer-context-item]')).toHaveLength(1)
    expect(document.querySelector('.context-summary-popover')).not.toBeInTheDocument()
  })


  it('removes every attachment without changing the pending question or sending a message', async () => {
    const browser = userEvent.setup()
    const value = contextValue({
      question: '保留这条问题',
      items: Array.from({ length: 3 }, (_, index) => ({ articleId: `article-${index + 1}`, title: `标题 ${index + 1}` })),
    })
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    await browser.click(screen.getByRole('button', { name: '移除全部 3 条信息' }))

    expect(value.clearItems).toHaveBeenCalledTimes(1)
    expect(value.setQuestion).not.toHaveBeenCalled()
    expect(value.clearComposer).not.toHaveBeenCalled()
    expect(chat.send).not.toHaveBeenCalled()
  })


  it('omits the upward all-context action when both visible rows already show every attachment', () => {
    const value = contextValue({
      items: Array.from({ length: 2 }, (_, index) => ({
        articleId: `article-${index + 1}`,
        title: `标题 ${index + 1}`,
        sourceUrl: `https://example.com/article-${index + 1}`,
      })),
    })
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    expect(screen.queryByRole('button', { name: /向上展开剩余/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '移除全部 2 条信息' })).toBeInTheDocument()
  })


  it('does not send while an IME composition is being confirmed', () => {
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    const value = contextValue({ question: 'english' })
    render(<OpenClawConversation chat={chat as never} value={value} />)
    const composer = screen.getByLabelText('发送给 OpenClaw 的问题')

    fireEvent.compositionStart(composer)
    const composingEnter = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      key: 'Enter',
      isComposing: true,
    })
    composer.dispatchEvent(composingEnter)
    expect(composingEnter.defaultPrevented).toBe(false)
    expect(chat.send).not.toHaveBeenCalled()

    fireEvent.compositionEnd(composer)
    const sendEnter = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      key: 'Enter',
    })
    composer.dispatchEvent(sendEnter)
    expect(sendEnter.defaultPrevented).toBe(true)
    expect(chat.send).toHaveBeenCalledTimes(1)
  })


  it('ignores the WebKit keyCode 229 Enter after composition end', () => {
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    const value = contextValue({ question: 'english' })
    render(<OpenClawConversation chat={chat as never} value={value} />)
    const composer = screen.getByLabelText('发送给 OpenClaw 的问题')

    fireEvent.compositionStart(composer)
    fireEvent.compositionEnd(composer)
    const webkitEnter = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      key: 'Enter',
    })
    Object.defineProperty(webkitEnter, 'keyCode', { value: 229 })
    composer.dispatchEvent(webkitEnter)
    expect(webkitEnter.defaultPrevented).toBe(false)
    expect(chat.send).not.toHaveBeenCalled()

    const sendEnter = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      key: 'Enter',
    })
    Object.defineProperty(sendEnter, 'keyCode', { value: 13 })
    composer.dispatchEvent(sendEnter)
    expect(sendEnter.defaultPrevented).toBe(true)
    expect(chat.send).toHaveBeenCalledTimes(1)
  })


  it('keeps Shift+Enter as a newline without sending', () => {
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    const value = contextValue({ question: 'first line' })
    render(<OpenClawConversation chat={chat as never} value={value} />)
    const composer = screen.getByLabelText('发送给 OpenClaw 的问题')
    const newline = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      key: 'Enter',
      shiftKey: true,
    })

    composer.dispatchEvent(newline)
    expect(newline.defaultPrevented).toBe(false)
    expect(chat.send).not.toHaveBeenCalled()
  })


  it('sends a direct subscription request through the controlled proposal flow', async () => {
    const browser = userEvent.setup()
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    const value = contextValue({ question: '创建食贫道的 Bilibili 订阅' })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    await browser.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))

    const request = chat.send.mock.calls[0][0]
    expect(request).toMatchObject({
      displayText: '创建食贫道的 Bilibili 订阅',
      contextItems: [],
    })
    expect(request.gatewayPrompt).toContain('[INTELISCOPE_HANDOFF_V8]')
    expect(request.gatewayPrompt).toContain('"mode":"direct"')
    expect(request.gatewayPrompt).toContain('prepare → preview → exact confirmation → apply')
    expect(request.gatewayPrompt).not.toContain('不得执行任何写操作')
  })


  it('uses an attachment-count fallback when the user sends without a question', async () => {
    const browser = userEvent.setup()
    const chat = chatController({ status: 'connected', sessionKey: 'session-1' })
    const value = contextValue({ items: [{ articleId: 'article-1', title: '标题一' }] })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    await browser.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))
    expect(chat.send).toHaveBeenCalledWith(expect.objectContaining({ displayText: '分析已附带的 1 条信息' }))
  })


  it('allows image selection with stock Gateway attachments even without an output media ticket', () => {
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      imageInputAvailable: true,
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.getByRole('button', { name: '添加图片' })).toBeEnabled()
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
        {
          id: 'openai/gpt-5.4',
          name: 'GPT-5.4',
          provider: 'openai',
          contextWindow: 200_000,
          reasoning: true,
          thinkingLevels: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }],
        },
        { id: 'local/quick', name: 'Quick', provider: 'local', contextWindow: 32_000, reasoning: false },
      ],
      thinkingOptions: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }],
      runtimeSelection: { modelId: 'openai/gpt-5.4', thinkingLevel: 'high', defaultModelId: 'openai/gpt-5.4', defaultThinkingLevel: 'low' },
      contextUsage: { sessionKey: 'session-1', usedTokens: 10_000, contextTokens: 200_000, percent: 5 },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    expect(screen.queryByRole('button', { name: /OpenClaw 运行设置/ })).not.toBeInTheDocument()
    const runtime = screen.getByTestId('openclaw-runtime-controls')
    expect(runtime.firstElementChild).toBe(screen.getByRole('button', { name: '上下文占用 10k / 200k，5%' }))
    await browser.click(screen.getByRole('button', { name: 'OpenClaw 模型：GPT-5.4' }))
    expect(screen.getByRole('listbox', { name: /OpenClaw 模型/u })).toHaveClass(
      'max-h-[min(360px,calc(100dvh-24px))]',
      'overflow-y-auto',
      'overscroll-contain',
    )
    expect(screen.getByText('openai')).toBeInTheDocument()
    expect(screen.getByText('local')).toBeInTheDocument()
    expect(screen.getByText('200k 上下文 · 思考：低、高')).toBeInTheDocument()
    expect(screen.getByText('32k 上下文 · 不支持思考档位')).toBeInTheDocument()
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

    expect(screen.getByTestId('openclaw-composer')).toHaveClass(
      'grid',
      'grid-rows-[minmax(80px,auto)_36px]',
      'gap-2',
      'border',
      'focus-within:border-focus',
    )
    const composerInput = screen.getByLabelText('发送给 OpenClaw 的问题')
    expect(composerInput).toHaveClass('!min-h-20', '!max-h-[180px]', '!border-0', '!bg-transparent', '!shadow-none', 'focus:!ring-0', 'focus:!ring-offset-0', '[field-sizing:content]')
    expect(screen.getByTestId('openclaw-composer-dock')).toHaveClass('p-2')
    expect(screen.getByTestId('openclaw-composer-dock')).not.toHaveClass('border-t', 'border-separator')
    expect(screen.getByTestId('openclaw-composer-toolbar')).toHaveClass('grid', 'grid-cols-[36px_minmax(0,1fr)_36px]')
    expect(screen.getByTestId('openclaw-composer-toolbar')).not.toHaveClass('mt-2')
    expect(screen.getByRole('button', { name: '发送给 OpenClaw' })).toHaveClass('size-9', 'shrink-0')
    expect(screen.getByTestId('openclaw-runtime-controls')).toHaveClass('flex')
    expect(screen.getByRole('button', { name: 'OpenClaw 模型：A deliberately long model name' })).toHaveClass('w-fit', 'min-w-0', 'max-w-[180px]')
    expect(screen.getByRole('button', { name: 'OpenClaw 思考程度：深度分析' })).toHaveClass('shrink-0')
  })


  it('shows a sanitized collapsible run trace before the first answer text', async () => {
    const browser = userEvent.setup()
    const chat = chatController({
      status: 'connected',
      sessionKey: 'session-1',
      isRunning: true,
      runTrace: {
        runId: 'run-1',
        phase: 'using_tool',
        status: 'running',
        startedAt: Date.now() - 3000,
        activities: [
          { id: 'context', label: '接收 2 条上下文', status: 'completed', startedAt: Date.now() - 3000, endedAt: Date.now() - 2900 },
          { id: 'tool-1', label: '检查来源健康', status: 'running', startedAt: Date.now() - 2000 },
        ],
      },
    })
    render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

    await waitFor(() => expect(screen.getAllByText('正在检查来源健康')).not.toHaveLength(0))
    expect(screen.getByText('已接收 2 条上下文')).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /正在检查来源健康/u })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await browser.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })
})
