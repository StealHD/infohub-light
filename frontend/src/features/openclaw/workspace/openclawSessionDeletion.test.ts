import { expect, it, vi } from 'vitest'
import { createOpenClawLifecycleRefs } from '../lifecycle/openclawLifecycleRefs'
import { createOpenClawWorkspaceRuntime } from './openclawWorkspaceRuntime'
import { sessionDeleteReason, verifySessionDeleted } from './openclawSessionDeletion'

it('blocks current, main, running, and unsupported sessions', () => {
  const row = { key: 'old', label: 'Old', hasActiveRun: false }
  expect(sessionDeleteReason(row, 'old', true)).toContain('切换')
  expect(sessionDeleteReason({ ...row, key: 'agent:own:main' }, 'other', true)).toContain('主会话')
  expect(sessionDeleteReason({ ...row, hasActiveRun: true }, 'other', true)).toContain('运行')
  expect(sessionDeleteReason(row, 'other', false)).toContain('不支持')
  expect(sessionDeleteReason({ ...row, worktree: { id: 'wt', branch: 'branch' } }, 'other', true)).toContain('工作树')
  expect(sessionDeleteReason({ ...row, archived: true }, 'other', true)).toBeNull()
})

it('requires a positive, matching deletion receipt', () => {
  for (const value of [null, {}, { ok: true, deleted: false }, { ok: true, deleted: true, key: 'wrong' }]) {
    expect(() => verifySessionDeleted(value, 'old')).toThrow('未确认')
  }
  expect(() => verifySessionDeleted({ ok: true, deleted: true }, 'old')).not.toThrow()
})

it('rechecks the session before deleting and invalidates all directory subscribers', async () => {
  const refs = createOpenClawLifecycleRefs()
  refs.session.sessionKey = 'current'
  refs.connection.hello = { features: { methods: ['sessions.list', 'sessions.preview', 'sessions.delete'] } }
  const request = vi.fn(async (method: string) => method === 'sessions.preview'
    ? { previews: [{ key: 'old', status: 'ok' }] }
    : method === 'sessions.list' ? { sessions: [{ key: 'old', hasActiveRun: false }] } : { ok: true, deleted: true })
  refs.connection.client = { request: request as never, connect: vi.fn(), close: vi.fn() }
  const { controller } = createOpenClawWorkspaceRuntime(refs)
  const listener = vi.fn(); controller.subscribe(listener)
  await controller.deleteSession('old')
  expect(request).toHaveBeenCalledWith('sessions.delete', { key: 'old', deleteTranscript: true })
  expect(listener).toHaveBeenCalledWith('sessions.changed')
  expect(refs.session.operation).toBeUndefined()
})


it('retains directory state after a rejected or unconfirmed deletion', async () => {
  const refs = createOpenClawLifecycleRefs()
  refs.session.sessionKey = 'current'
  refs.connection.hello = { features: { methods: ['sessions.list', 'sessions.preview', 'sessions.delete'] } }
  const request = vi.fn(async (method: string) => method === 'sessions.preview'
    ? { previews: [{ key: 'old', status: 'ok' }] }
    : method === 'sessions.list' ? { sessions: [{ key: 'old', hasActiveRun: false }] } : { ok: true, deleted: false })
  refs.connection.client = { request: request as never, connect: vi.fn(), close: vi.fn() }
  const { controller } = createOpenClawWorkspaceRuntime(refs)
  const listener = vi.fn(); controller.subscribe(listener)
  await expect(controller.deleteSession('old')).rejects.toThrow('未确认')
  expect(listener).not.toHaveBeenCalled()
  expect(refs.session.sessionKey).toBe('current')
  expect(refs.session.operation).toBeUndefined()
  request.mockRejectedValueOnce(new Error('private gateway worktree error'))
  await expect(controller.deleteSession('old')).rejects.toThrow('暂时无法')
  expect(listener).not.toHaveBeenCalled()
})
