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
      modelPreference: 'auto',
      ...overrides,
    },
    toggleItem: vi.fn(),
    removeItem: vi.fn(),
    openComposer: vi.fn(),
    setQuestion: vi.fn(),
    setModelPreference: vi.fn(),
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
    sessionKey: null,
    isRunning: false,
    connect: vi.fn().mockResolvedValue(true),
    disconnect: vi.fn(),
    forget: vi.fn(),
    send: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn(),
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

  it('sends only the user question and selected article ids to OpenClaw', async () => {
    const browser = userEvent.setup()
    const chat = chatController({ status: 'connected', toolsStatus: 'available', sessionKey: 'session-1' })
    const value = contextValue({
      question: '比较这两篇文章',
      modelPreference: 'deep',
      items: [
        { articleId: 'article-1', title: '标题一', sourceName: '来源一' },
        { articleId: 'article-2', title: '标题二', sourceName: '来源二' },
      ],
    })
    render(<OpenClawConversation chat={chat as never} value={value} />)

    expect(screen.getByLabelText('附带 2 篇文章')).toHaveTextContent('标题一 · 来源一')
    await browser.click(screen.getByRole('button', { name: '发送给 OpenClaw' }))
    expect(chat.send).toHaveBeenCalledWith(expect.stringContaining('article_id="article-1"'), 'deep')
    const sent = chat.send.mock.calls[0][0] as string
    expect(sent).toContain('article_id="article-2"')
    expect(sent).not.toContain('标题一')
  })

  it('builds Origin repair commands that append without a wildcard', () => {
    const commands = gatewayOriginSetupCommands('https://rb.jiefs.top')
    expect(commands.shell).toContain('new Set([...xs, process.argv[2]])')
    expect(commands.powershell).toContain('Sort-Object -Unique')
    expect(`${commands.shell}\n${commands.powershell}`).not.toContain('allowedOrigins:["*"]')
    expect(`${commands.shell}\n${commands.powershell}`).not.toContain('allowedOrigins ["*"]')
  })
})
