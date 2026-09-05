import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { DesignSystemProvider } from '../../design-system'
import type { OpenClawWorkspaceController } from '../openclaw'
import { AgentWorktreeDialog } from './AgentWorktreeDialog'

function workspace(result: { runStarted: boolean }) {
  return {
    listProjects: vi.fn().mockResolvedValue([{ id: 'project', displayName: 'InfoHub', repoRoot: '/repo', source: 'configured' }]),
    listBranches: vi.fn().mockResolvedValue({ branches: [{ name: 'main', kind: 'local' }], defaultBranch: 'main' }),
    createWorktreeSession: vi.fn().mockResolvedValue({ sessionKey: 'child', ...result, ...(result.runStarted ? { runId: 'run' } : {}) }),
    retryWorktreeRun: vi.fn().mockRejectedValueOnce(new Error('lost receipt')).mockResolvedValue({ runId: 'retry-run' }),
  } as unknown as OpenClawWorkspaceController
}

function Harness({ controller, inline = false }: { controller: OpenClawWorkspaceController; inline?: boolean }) {
  const [open, setOpen] = useState(true)
  return <MemoryRouter><DesignSystemProvider>
    <button type="button" onClick={() => setOpen(true)}>重新打开</button>
    <AgentWorktreeDialog inline={inline} open={open} onOpenChange={setOpen} workspace={controller} onCreated={vi.fn()} />
  </DesignSystemProvider></MemoryRouter>
}

async function fillAndCreate(browser: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('button', { name: /main.*基础分支/u })
  await browser.type(screen.getByLabelText('任务标题'), 'UI task')
  await browser.type(screen.getByLabelText('完整提示词'), 'Implement it')
  await browser.click(screen.getByRole('button', { name: '确认创建' }))
}

describe('Agent Worktree dialog state machine', () => {
  it('resets a completed task and creates a fresh idempotency key when reopened', async () => {
    const browser = userEvent.setup()
    const controller = workspace({ runStarted: true })
    render(<Harness controller={controller} />)
    await fillAndCreate(browser)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '在新 Worktree 中执行' })).not.toBeInTheDocument())
    await browser.click(screen.getByRole('button', { name: '重新打开' }))
    expect(await screen.findByLabelText('任务标题')).toHaveValue('')
    await fillAndCreate(browser)
    const calls = vi.mocked(controller.createWorktreeSession).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0][0].idempotencyKey).not.toBe(calls[1][0].idempotencyKey)
  })

  it('reuses one retry idempotency key after a lost retry receipt', async () => {
    const browser = userEvent.setup()
    const controller = workspace({ runStarted: false })
    render(<Harness controller={controller} />)
    await fillAndCreate(browser)
    const retry = await screen.findByRole('button', { name: '在原 Session 重试' })
    await browser.click(retry)
    await screen.findByText('OpenClaw 暂时无法完成此操作，请重试。')
    await browser.click(screen.getByRole('button', { name: '在原 Session 重试' }))
    await waitFor(() => expect(vi.mocked(controller.retryWorktreeRun)).toHaveBeenCalledTimes(2))
    const calls = vi.mocked(controller.retryWorktreeRun).mock.calls
    expect(calls[0][2]).toBe(calls[1][2])
    expect(vi.mocked(controller.createWorktreeSession)).toHaveBeenCalledOnce()
  })
})

it('creates inline without a dialog and retains the form and one request during pending', async () => {
  const browser = userEvent.setup()
  const controller = workspace({ runStarted: true })
  let resolve!: (value: { sessionKey: string; runStarted: boolean; runId: string }) => void
  vi.mocked(controller.createWorktreeSession).mockImplementation(() => new Promise((done) => { resolve = done }))
  render(<Harness controller={controller} inline />)
  await screen.findByRole('button', { name: /main.*基础分支/u })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  const title = screen.getByLabelText('任务标题')
  await browser.type(title, 'Inline task')
  await browser.type(screen.getByLabelText('完整提示词'), 'Implement it')
  await browser.dblClick(screen.getByRole('button', { name: '确认创建' }))
  expect(controller.createWorktreeSession).toHaveBeenCalledOnce()
  expect(screen.getByLabelText('任务标题')).toBe(title)
  expect(screen.getByRole('button', { name: '取消' })).toBeDisabled()
  resolve({ sessionKey: 'child', runStarted: true, runId: 'run' })
  await waitFor(() => expect(screen.queryByLabelText('任务标题')).not.toBeInTheDocument())
})
