import { expect, it, vi } from 'vitest'
import { readOpenClawRuntime } from './openclawSessionOperations'
import type { OpenClawClientPort } from '../openclawContracts'

const key = 'agent:personal:dashboard:new'
const parentKey = 'agent:personal:main'
function client(parent: Record<string, unknown> | null, child = {}) {
  return { request: vi.fn(async (method: string, params: Record<string, unknown>) => {
    if (method === 'models.list') return { models: [{ provider: 'google', id: 'flash' }, { provider: 'google', id: 'pro' }] }
    if (method === 'agents.list') return { agents: [{ id: 'personal', model: { primary: 'google/flash' } }] }
    if (method === 'sessions.list') return { sessions: parent ? [{ key: parentKey }] : [], totalCount: parent ? 1 : 0, hasMore: false }
    if (method === 'sessions.describe') return { session: params.key === parentKey ? parent : { key, agentId: 'personal', parentSessionKey: parentKey, modelProvider: 'google', model: 'flash', ...child } }
    throw new Error(method)
  }) } as unknown as OpenClawClientPort
}

it.each([null, { key: parentKey, agentId: 'personal', modelProvider: 'google', model: 'flash' }])('accepts a plain main link only after checking the inherited model', async (parent) => {
  expect((await readOpenClawRuntime(client(parent), key, 'personal', true, true)).selection.modelSafety).toBe('verified')
})
it.each([
  { key: parentKey, modelProvider: 'google', model: 'pro' },
  { key: parentKey, agentId: 'other', modelProvider: 'google', model: 'flash' },
  { key: parentKey, parentSessionKey: 'another', model: 'flash' },
  { key: 'wrong', modelProvider: 'google', model: 'flash' },
])('keeps protection for conflicting or unverified inheritance: %o', async (parent) => {
  expect((await readOpenClawRuntime(client(parent), key, 'personal')).selection.modelSafety).toBe('unsafe_fork')
})
it.each([{ forkedFromParent: true }, { forkSource: { sessionKey: parentKey } }, { parentSessionKey: 'agent:other:main' }, { parentSessionKey: 1 }])('does not treat a real fork or foreign parent as a blank conversation: %o', async (child) => {
  await expect(readOpenClawRuntime(client(null, child), key, 'personal', true, true)).rejects.toThrow('独立对话')
})
it('retains protection when the parent lookup fails', async () => {
  const port = client(null)
  const original = port.request
  port.request = vi.fn((method, params) => method === 'sessions.list' ? Promise.reject(new Error('unavailable')) : original(method, params)) as OpenClawClientPort['request']
  expect((await readOpenClawRuntime(port, key, 'personal')).selection.modelSafety).toBe('unsafe_fork')
})
