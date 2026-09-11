import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import type { GatewayEvent } from './openclawGateway'
import { MemoryAdapter } from './useOpenClawChat.test.support'
import { useOpenClawChat } from './useOpenClawChat'
import { projectOpenClawRuntime } from './chat/openclawRuntimeProjection'

const modelResult = { models: [{ id: 'gpt', provider: 'openai', name: 'GPT', reasoning: true, thinkingLevels: [{ id: 'high', label: '高' }] }] }
const agentResult = { defaultId: 'main', agents: [{ id: 'main', model: { primary: 'openai/gpt' } }] }
const message = { displayText: 'hello', gatewayPrompt: 'hello', contextItems: [] }

async function setup(defaultFastMode: boolean | 'auto' = false) {
  const vault = new OpenClawCredentialVault(new MemoryAdapter())
  await vault.save('fast-user', 'ws://127.0.0.1:18789', {
    identity: { deviceId: 'device', publicKey: 'public', privateKey: {} as CryptoKey },
    deviceToken: 'fixture', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
  })
  let emit: (event: GatewayEvent) => void = () => undefined
  let fail = false
  let count = 0
  const request = vi.fn(async (method: string, params: Record<string, unknown>) => {
    if (method === 'models.list') return modelResult
    if (method === 'agents.list') return agentResult
    if (method === 'sessions.describe') return { session: { key: params.key, agentId: 'main', modelProvider: 'openai', model: 'gpt', thinkingLevel: 'high', effectiveFastMode: defaultFastMode } }
    if (method === 'chat.history') return { messages: [] }
    if (method === 'tools.effective') return { groups: [] }
    if (method === 'sessions.create') return { key: 'session-2' }
    if (method === 'chat.send') { count += 1; if (fail) throw new Error('offline'); return { runId: `run-${count}` } }
    return {}
  })
  const hook = renderHook(({ userId }) => useOpenClawChat({
    enabled: true, userId, defaultGatewayUrl: 'ws://127.0.0.1:18789', vault,
    clientFactory: (options) => {
      emit = (event) => options.onEvent?.(event)
      return { request: request as never, close: vi.fn(), connect: async () => ({ protocol: 4, auth: { deviceToken: 'fixture', scopes: ['operator.read', 'operator.write'], role: 'operator' }, snapshot: { sessionDefaults: { defaultAgentId: 'main' } } }) }
    },
  }), { initialProps: { userId: 'fast-user' } })
  await waitFor(() => expect(hook.result.current.status).toBe('connected'))
  return { ...hook, request, fail: (next: boolean) => { fail = next }, finish: () => emit({ type: 'event', event: 'chat', payload: { sessionKey: 'session-1', runId: `run-${count}`, state: 'final', message: { role: 'assistant', content: [{ type: 'text', text: 'done' }] } } }) }
}

describe('Fast request override', () => {
  beforeEach(() => sessionStorage.clear())
  it('keeps Fast independent, sends true/false, and blocks changes during a run', async () => {
    const { result, request, finish } = await setup()
    await act(async () => { expect(await result.current.setFastMode(true)).toBe(true) })
    expect(result.current.runtimeSelection.thinkingLevel).toBe('high')
    expect(request.mock.calls.some(([method]) => method === 'chat.send' || method === 'sessions.patch')).toBe(false)
    await act(async () => { await result.current.send(message) })
    expect(request).toHaveBeenCalledWith('chat.send', expect.objectContaining({ fastMode: true, thinking: 'high' }))
    await act(async () => { expect(await result.current.setFastMode(false)).toBe(false); finish() })
    await waitFor(() => expect(result.current.isRunning).toBe(false))
    await act(async () => { await result.current.setFastMode(false) })
    await act(async () => { await result.current.send(message) })
    expect(request).toHaveBeenLastCalledWith('chat.send', expect.objectContaining({ fastMode: false }))
  })
  it('retries the original Fast choice even after the current choice changes', async () => {
    const { result, request, fail } = await setup()
    fail(true)
    await act(async () => { await result.current.setFastMode(true) })
    await act(async () => { expect(await result.current.send(message)).toBe(false) })
    const failed = result.current.messages.find((entry) => entry.status === 'failed')!
    expect(failed.sendSnapshot?.fastMode).toBe(true)
    await act(async () => { await result.current.setFastMode(false) })
    fail(false)
    await act(async () => { await result.current.retry(failed.id) })
    expect(request).toHaveBeenLastCalledWith('chat.send', expect.objectContaining({ fastMode: true, idempotencyKey: failed.sendSnapshot?.idempotencyKey }))
  })
  it('omits untouched overrides and clears a local choice for a new session and user', async () => {
    const { result, request, finish, rerender } = await setup('auto')
    expect(result.current.runtimeSelection.defaultFastMode).toBe(true)
    await act(async () => { await result.current.send(message) })
    expect(request.mock.calls.find(([method]) => method === 'chat.send')?.[1]).not.toHaveProperty('fastMode')
    await act(async () => { finish() })
    await act(async () => { await result.current.setFastMode(false) })
    await act(async () => { await result.current.newConversation() })
    expect(result.current.runtimeSelection.fastMode).toBeUndefined()
    rerender({ userId: 'other-user' })
    await waitFor(() => expect(result.current.runtimeSelection.defaultFastMode).toBeUndefined())
  })
  it('does not adopt a Fast default from a mismatched session or malformed value', () => {
    for (const session of [{ key: 'other', effectiveFastMode: true }, { key: 'exact', effectiveFastMode: 'true' }]) {
      expect(projectOpenClawRuntime(modelResult, agentResult, { session }, 'main', 'exact').selection.defaultFastMode).toBeUndefined()
    }
  })
})
