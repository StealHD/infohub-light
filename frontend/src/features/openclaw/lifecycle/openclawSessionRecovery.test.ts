import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useOpenClawSessionActions } from './openclawSessionActions'
import { createOpenClawLifecycleRefs } from './openclawLifecycleRefs'
import type { OpenClawClientPort } from '../openclawContracts'
import type { OpenClawLifecycleState } from './openclawChatReducer'

it.each([false, true])('context-preserving default switch excludes double activation; patched=%s', async (patched) => {
  const refs = createOpenClawLifecycleRefs()
  const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'sessions.create') return { key: 'child' }
    if (method === 'sessions.describe') return { session: { key: params?.key, agentId: 'personal', parentSessionKey: 'old-parent', modelProvider: 'deepseek', model: 'flash', ...(patched && params?.key === 'child' ? { modelOverrideSource: 'user' } : {}) } }
    if (method === 'models.list') return { models: [{ id: 'flash', provider: 'deepseek' }] }
    if (method === 'agents.list') return { agents: [{ id: 'personal', model: { primary: 'deepseek/flash' } }] }
    return {}
  })
  refs.connection.client = { request: request as OpenClawClientPort['request'], connect: vi.fn(), close: vi.fn() }
  refs.session.sessionKey = 'old'; refs.session.agentId = 'personal'
  const state = { runtimeSelection: { modelId: 'deepseek/flash', defaultModelId: 'deepseek/flash', modelSafety: 'unsafe_fork' },
    models: [{ id: 'deepseek/flash', name: 'DeepSeek' }] } as OpenClawLifecycleState
  const dispatch = vi.fn(), activateSession = vi.fn()
  const { result } = renderHook(() => useOpenClawSessionActions({ refs, state, dispatch, activateSession, archiveFailedSession: vi.fn() }))
  await act(async () => { await Promise.all([result.current.setModel('deepseek/flash'), result.current.setModel('deepseek/flash')]) })
  expect(request.mock.calls.filter(([method]) => method === 'sessions.create')).toHaveLength(1)
  expect(request).toHaveBeenCalledWith('sessions.create', { agentId: 'personal', model: 'deepseek/flash', parentSessionKey: 'old', fork: true })
  expect(activateSession).toHaveBeenCalledTimes(patched ? 1 : 0)
  if (patched) expect(activateSession).toHaveBeenCalledWith(expect.anything(), 'child', 'personal', expect.anything(), false, true, expect.any(Function))
  else expect(refs.session.sessionKey).toBe('old')
})
