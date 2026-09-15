import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DesignSystemProvider } from '../../design-system'
import { AgentSessionRow } from './AgentSessionRow'
import type { OpenClawWorkspaceController, OpenClawWorkspaceSession } from '../openclaw'

const session: OpenClawWorkspaceSession = { key: 'session-1', label: '历史会话', hasActiveRun: false }
const deleteSession = vi.fn().mockResolvedValue(undefined)
const workspace = { capabilities: () => ({ 'sessions.delete': true }), deleteSession } as unknown as OpenClawWorkspaceController

beforeEach(() => vi.clearAllMocks())

it('uses a reserved X delete control instead of a details menu and does not open the session', async () => {
  const onOpen = vi.fn()
  render(<MemoryRouter><DesignSystemProvider><AgentSessionRow workspace={workspace} session={session} current={false} disabled={false} onOpen={onOpen} /></DesignSystemProvider></MemoryRouter>)
  expect(screen.queryByRole('button', { name: /会话详情/ })).not.toBeInTheDocument()
  const remove = screen.getByRole('button', { name: '删除会话：历史会话' })
  expect(remove).toHaveClass('opacity-0')
  await userEvent.setup().click(remove)
  expect(screen.getByRole('dialog', { name: '删除会话' })).toBeVisible()
  expect(screen.getByRole('checkbox', { name: '下次不再提醒' })).not.toBeChecked()
  expect(onOpen).not.toHaveBeenCalled()
})

it('stores the skip preference only after a confirmed deletion succeeds', async () => {
  deleteSession.mockResolvedValueOnce(undefined)
  const onPreferenceChange = vi.fn()
  render(<MemoryRouter><DesignSystemProvider><AgentSessionRow workspace={workspace} session={session} current={false} disabled={false} onOpen={vi.fn()} onConfirmBeforeDeleteChange={onPreferenceChange} /></DesignSystemProvider></MemoryRouter>)
  const browser = userEvent.setup()

  await browser.click(screen.getByRole('button', { name: '删除会话：历史会话' }))
  await browser.click(screen.getByRole('checkbox', { name: '下次不再提醒' }))
  await browser.click(screen.getByRole('button', { name: '确认删除' }))

  await waitFor(() => expect(deleteSession).toHaveBeenCalledWith('session-1'))
  expect(onPreferenceChange).toHaveBeenCalledWith(false)
})

it('deletes directly when confirmation is disabled without allowing duplicate submissions', async () => {
  let resolveDelete: (() => void) | undefined
  deleteSession.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveDelete = resolve }))
  render(<MemoryRouter><DesignSystemProvider><AgentSessionRow workspace={workspace} session={session} current={false} disabled={false} onOpen={vi.fn()} confirmBeforeDelete={false} /></DesignSystemProvider></MemoryRouter>)
  const remove = screen.getByRole('button', { name: '删除会话：历史会话' })

  act(() => { remove.click(); remove.click() })
  expect(screen.queryByRole('dialog', { name: '删除会话' })).not.toBeInTheDocument()
  expect(deleteSession).toHaveBeenCalledTimes(1)
  resolveDelete?.()
  await waitFor(() => expect(remove).not.toHaveAttribute('aria-busy', 'true'))
})

it('keeps an unavailable delete target disabled with its specific reason', () => {
  render(<MemoryRouter><DesignSystemProvider><AgentSessionRow workspace={workspace} session={session} current disabled={false} onOpen={vi.fn()} /></DesignSystemProvider></MemoryRouter>)
  const unavailable = screen.getByLabelText('无法删除会话：请先切换后删除')
  expect(unavailable).toHaveAttribute('role', 'button')
  expect(unavailable).toHaveAttribute('aria-disabled', 'true')
  expect(unavailable).toHaveAttribute('tabindex', '0')
  expect(unavailable.querySelector('button')).toBeDisabled()
  expect(unavailable.querySelector('button')).toHaveAccessibleName('删除会话不可用：请先切换后删除')
})
