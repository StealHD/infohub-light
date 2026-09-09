import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import type { OpenClawChatController, OpenClawWorkspaceCapabilityMap } from '../openclaw'
import { chatController, contextValue } from '../openclaw/OpenClawConversation.test.support'
import { OpenClawWorkspaceRuntimeProvider } from '../openclaw/workspace/OpenClawWorkspaceRuntimeProvider'
import { WorkbenchAgentContext } from '../workbench-live/workbenchAgentContext'
import { AgentWorkspacePage } from './AgentWorkspacePage'

const methodNames = ['projects.list', 'sessions.create', 'sessions.list', 'sessions.preview', 'sessions.send', 'worktrees.branches', 'tasks.list', 'tasks.get', 'tasks.cancel', 'artifacts.list', 'artifacts.get', 'artifacts.download', 'skills.status'] as const
function workspaceCapabilities(enabled = false): OpenClawWorkspaceCapabilityMap {
  return Object.fromEntries(methodNames.map((method) => [method, enabled])) as OpenClawWorkspaceCapabilityMap
}

function renderPage(path: string, width = 1440) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  const workspace = {
    capabilities: () => workspaceCapabilities(),
    subscribe: () => () => undefined,
    listSessions: vi.fn().mockResolvedValue([]),
  }
  const chat = chatController({ status: 'disabled', workspace, openSession: vi.fn() }) as unknown as OpenClawChatController
  const context = contextValue({ question: '保留中的 Feed 草稿', items: [{ articleId: 'item-1', title: 'Feed 上下文条目' }] })
  render(<MemoryRouter initialEntries={[path]}><DesignSystemProvider><OpenClawWorkspaceRuntimeProvider chat={chat}><WorkbenchAgentContext.Provider value={context}><AgentWorkspacePage /></WorkbenchAgentContext.Provider></OpenClawWorkspaceRuntimeProvider></DesignSystemProvider></MemoryRouter>)
  return { chat, context }
}

describe('Agent Workspace page', () => {
  beforeEach(() => window.localStorage.clear())

  it('renders one OpenClaw workspace layer with a fixed desktop session sidebar and closed inspector', async () => {
    const { context } = renderPage('/agent')
    expect(screen.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveClass('w-[var(--inteliscope-width-agent-sidebar)]')
    expect(screen.getByRole('navigation', { name: 'OpenClaw 工作区' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: /检查器/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('separator', { name: /调整/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '在新 Worktree 中执行' })).not.toBeInTheDocument()
    expect(await screen.findByText('站内 OpenClaw 对话尚未启用；仍可复制交接提示词到自己的 OpenClaw。')).toBeInTheDocument()
    expect(context.draft.question).toBe('保留中的 Feed 草稿')
    expect(screen.getByRole('heading', { name: 'OpenClaw 对话' }).closest('header')).toHaveAttribute('data-page-header-appearance', 'inset')
  })

  it('explains every feature without sending, creating a task or clearing the draft', async () => {
    const browser = userEvent.setup()
    const { chat, context } = renderPage('/agent')
    await browser.click(screen.getByRole('link', { name: '使用示例' }))
    for (const feature of ['对话', '上下文', 'Tasks', 'Artifacts', 'Skills', 'Automations']) {
      expect(screen.getByRole('heading', { name: new RegExp(`^${feature}：`) })).toBeInTheDocument()
    }
    expect(chat.openSession).not.toHaveBeenCalled()
    expect(context.draft.question).toBe('保留中的 Feed 草稿')
    expect(screen.getByRole('heading', { name: /^使用示例$/u })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps the conversation mounted while a deep-linked Tasks inspector is open', () => {
    renderPage('/agent/tasks')
    expect(screen.getByTestId('agent-scroll-region')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Tasks检查器' })).toHaveClass('disclosure-panel')
    expect(screen.getByRole('heading', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByText('连接 Gateway 后查看 Tasks')).toBeInTheDocument()
  })

  it('keeps the same conversation DOM and draft while switching resource inspectors', async () => {
    const browser = userEvent.setup()
    const { context } = renderPage('/agent')
    const conversation = screen.getByTestId('agent-scroll-region')
    conversation.scrollTop = 37
    await browser.click(screen.getByRole('button', { name: '打开Tasks' }))
    expect(screen.getByTestId('agent-scroll-region')).toBe(conversation)
    await browser.click(screen.getByRole('button', { name: '打开Artifacts' }))
    expect(screen.getByTestId('agent-scroll-region')).toBe(conversation)
    expect(conversation.scrollTop).toBe(37)
    expect(context.draft.question).toBe('保留中的 Feed 草稿')
  })

  it('moves the session sidebar and context inspector into bottom sheets on mobile', async () => {
    const browser = userEvent.setup()
    renderPage('/agent', 390)
    expect(screen.queryByRole('complementary', { name: 'OpenClaw 会话' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '打开 OpenClaw 会话' }))
    expect(screen.getByRole('dialog', { name: 'OpenClaw 会话' })).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    await browser.click(screen.getByRole('button', { name: '打开上下文' }))
    expect(screen.getByRole('dialog', { name: '上下文' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Feed 上下文' })).toBeInTheDocument()
  })
})
