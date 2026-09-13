import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DesignSystemProvider } from '../../design-system'
import { AgentSessionRow } from './AgentSessionRow'
import type { OpenClawWorkspaceController, OpenClawWorkspaceSession } from '../openclaw'

const session: OpenClawWorkspaceSession = { key: 'session-1', label: '历史会话', hasActiveRun: false }
const workspace = { capabilities: () => ({ 'sessions.delete': true }) } as unknown as OpenClawWorkspaceController

it('uses a reserved X delete control instead of a details menu and does not open the session', async () => {
  const onOpen = vi.fn()
  render(<MemoryRouter><DesignSystemProvider><AgentSessionRow workspace={workspace} session={session} current={false} disabled={false} onOpen={onOpen} /></DesignSystemProvider></MemoryRouter>)
  expect(screen.queryByRole('button', { name: /会话详情/ })).not.toBeInTheDocument()
  const remove = screen.getByRole('button', { name: '删除会话：历史会话' })
  expect(remove).toHaveClass('opacity-0')
  await userEvent.setup().click(remove)
  expect(screen.getByRole('dialog', { name: '删除会话' })).toBeVisible()
  expect(onOpen).not.toHaveBeenCalled()
})

it('keeps an unavailable delete target disabled with its specific reason', () => {
  render(<MemoryRouter><DesignSystemProvider><AgentSessionRow workspace={workspace} session={session} current disabled={false} onOpen={vi.fn()} /></DesignSystemProvider></MemoryRouter>)
  const unavailable = screen.getByLabelText('无法删除会话：请先切换后删除')
  expect(unavailable).toHaveAttribute('tabindex', '0')
  expect(unavailable.querySelector('button')).toBeDisabled()
})
