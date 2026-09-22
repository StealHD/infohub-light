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
  else {
    expect(refs.session.sessionKey).toBe('old')
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ value: expect.objectContaining({
      runtimeIssue: 'Gateway 未能固定所选模型，暂无法保留上下文切换。请管理员检查模型继承兼容修复。 原对话和输入已保留。',
      modelSwitchFallback: null,
    }) }))
    expect(request.mock.calls.some(([method]) => method === 'chat.send')).toBe(false)
  }
})

it('keeps the model recovery warning when changing thinking or Fast', async () => {
  const refs = createOpenClawLifecycleRefs()
  refs.connection.client = { request: vi.fn(), connect: vi.fn(), close: vi.fn() }
  refs.session.sessionKey = 'old'; refs.session.agentId = 'personal'
  const state = { runtimeIssue: 'Gateway 未能固定所选模型',
    runtimeSelection: { modelId: 'deepseek/flash', modelSafety: 'unsafe_fork' },
    models: [{ id: 'deepseek/flash', name: 'DeepSeek' }], thinkingOptions: [{ id: 'low', label: '低' }],
  } as OpenClawLifecycleState
  const dispatch = vi.fn()
  const { result } = renderHook(() => useOpenClawSessionActions({ refs, state, dispatch, activateSession: vi.fn(), archiveFailedSession: vi.fn() }))
  await act(async () => { expect(await result.current.setThinking('low')).toBe(true) })
  await act(async () => { expect(await result.current.setFastMode(true)).toBe(true) })
  expect(dispatch).toHaveBeenCalledTimes(2)
  for (const [action] of dispatch.mock.calls) expect(action.value.runtimeIssue).toBe(state.runtimeIssue)
})
