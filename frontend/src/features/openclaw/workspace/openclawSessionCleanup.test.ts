import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createOpenClawLifecycleRefs } from '../lifecycle/openclawLifecycleRefs'
import { createOpenClawWorkspaceRuntime } from './openclawWorkspaceRuntime'

const now = Date.UTC(2026, 9, 13), day = 86_400_000
const key = (id: string) => `agent:own:${id}`
type Row = { key: string; updatedAt: number; hasActiveRun?: boolean; archived?: boolean; parentSessionKey?: string; hasWorktree?: boolean; hasAutomation?: boolean }
const row = (id: string, age: number, extra = {}): Row => ({ key: key(id), updatedAt: now - age * day, hasActiveRun: false, archived: false, ...extra })
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now) })
afterEach(() => { vi.useRealTimers() })

function fixture(rows: Row[], empty: string[] = []) {
  const refs = createOpenClawLifecycleRefs()
  refs.session.agentId = 'own'; refs.session.sessionKey = key('current')
  refs.connection.hello = { features: { methods: ['sessions.list', 'sessions.preview', 'sessions.delete'] } }
  const records = new Map(rows.map((session) => [session.key, session]))
  const request = vi.fn(async (method: string, params: Record<string, unknown>) => {
    if (method === 'sessions.list') {
      const selected = [...records.values()].filter((entry) => params.search ? entry.key === params.search : entry.archived === params.archived)
      const offset = Number(params.offset ?? 0), limit = Number(params.limit ?? 100)
      return { sessions: selected.slice(offset, offset + limit), hasMore: offset + limit < selected.length, nextOffset: offset + limit, totalCount: selected.length }
    }
    if (method === 'sessions.preview') return { previews: (params.keys as string[]).map((sessionKey) => ({ key: sessionKey, status: empty.includes(sessionKey) ? 'empty' : 'ok' })) }
    if (method === 'sessions.delete') return { ok: true, deleted: records.delete(String(params.key)) }
    throw new Error(method)
  })
  refs.connection.client = { request: request as never, connect: vi.fn(), close: vi.fn() }
  const onDeleted = vi.fn(), { controller } = createOpenClawWorkspaceRuntime(refs, onDeleted)
  const options = { lastUsedAt: () => 0, isEnabled: () => true }
  return { refs, records, request, onDeleted, options, clean: () => controller.cleanupSessions!(options) }
}

it('uses the confirmed 7 day empty and 90 day history boundaries, including archived sessions', async () => {
  const f = fixture([row('empty-old', 7), row('empty-new', 6.99), row('history-old', 90), row('history-new', 89.99), row('archived', 91, { archived: true })], [key('empty-old'), key('empty-new')])
  expect(await f.clean()).toBe(3)
  expect([...f.records.keys()]).toEqual([key('empty-new'), key('history-new')])
  expect(f.request).toHaveBeenCalledWith('sessions.delete', { key: key('empty-old'), deleteTranscript: true, expectedSessionUpdatedAt: now - 7 * day })
})

it('protects current, main, running, unknown activity, worktree, automation, parent and foreign sessions', async () => {
  const f = fixture([row('current', 100), row('main', 100), row('busy', 100, { hasActiveRun: true }), row('unknown', 100, { hasActiveRun: undefined }),
    row('worktree', 100, { hasWorktree: true }), row('automation', 100, { hasAutomation: true }), row('parent', 100), row('child', 1, { parentSessionKey: key('parent') }),
    row('foreign', 100, { key: 'agent:other:old' }), row('bad-time', 100, { updatedAt: 0 }), row('future', -1)])
  expect(await f.clean()).toBe(0)
  expect(f.onDeleted).not.toHaveBeenCalled()
})

it('recently opened sessions remain protected even with an old transcript timestamp', async () => {
  const f = fixture([row('read', 100)])
  f.options.lastUsedAt = () => now - day
  expect(await f.clean()).toBe(0)
})

it('rechecks activity, revision and disabled preference after preview before deletion', async () => {
  for (const change of ['activity', 'revision', 'preference']) {
    const f = fixture([row('old', 100)])
    const original = f.request.getMockImplementation()!
    f.request.mockImplementation(async (method, params) => {
      if (method === 'sessions.preview') {
        if (change === 'activity') f.records.get(key('old'))!.hasActiveRun = true
        if (change === 'revision') f.records.get(key('old'))!.updatedAt = now
        if (change === 'preference') f.options.isEnabled = () => false
      }
      return original(method, params)
    })
    expect(await f.clean()).toBe(0)
    expect(f.records.has(key('old'))).toBe(true)
  }
})

it('bounds each pass and eventually checks empties behind younger history', async () => {
  const f = fixture([...Array.from({ length: 21 }, (_, i) => row(`history-${i}`, 8)), row('empty', 7)], [key('empty')])
  expect(await f.clean()).toBe(0)
  expect(await f.clean()).toBe(1)
  const many = fixture(Array.from({ length: 25 }, (_, i) => row(`old-${i}`, 100)))
  expect(await many.clean()).toBe(10)
  expect(await many.clean()).toBe(10)
})

it('skips cleanup if the directory is incomplete or a connection changes', async () => {
  const large = fixture(Array.from({ length: 1001 }, (_, i) => row(`old-${i}`, 100)))
  await expect(large.clean()).rejects.toThrow('完整读取')
  expect(large.onDeleted).not.toHaveBeenCalled()
  const f = fixture([row('old', 100)])
  const original = f.request.getMockImplementation()!
  f.request.mockImplementation(async (method, params) => { f.refs.connection.generation += 1; return original(method, params) })
  await expect(f.clean()).rejects.toThrow('连接已变化')
})
