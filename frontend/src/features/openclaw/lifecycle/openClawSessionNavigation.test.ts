import { describe, expect, it, vi } from 'vitest'

import type { OpenClawCredentialVault } from '../openclawCredentialVault'
import type { OpenClawClientPort } from '../openclawContracts'
import { createOpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { openOpenClawSession } from './openClawSessionNavigation'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('OpenClaw session navigation epoch', () => {
  it('lets only the latest reverse-completing intent bind transcript or Vault', async () => {
    const first = deferred<unknown>()
    const second = deferred<unknown>()
    const request = vi.fn((method: string, params: Record<string, unknown>) => {
      if (method === 'models.list') return Promise.resolve({ models: [] })
      if (method === 'agents.list') return Promise.resolve({ agents: [] })
      if (method === 'sessions.describe') return params.key === 'session-a' ? first.promise : second.promise
      throw new Error(`unexpected ${method}`)
    }) as OpenClawClientPort['request']
    const client = { connect: vi.fn(), request, close: vi.fn() } as OpenClawClientPort
    const refs = createOpenClawLifecycleRefs()
    refs.connection.client = client
    refs.session.agentId = 'main'
    refs.session.sessionKey = 'root'
    const updateSession = vi.fn().mockResolvedValue(undefined)
    const bind = vi.fn((_agentId: string, key: string) => { refs.session.sessionKey = key })
    const input = {
      userId: 'user', refs, state: { sending: false, runtimeUpdating: false }, dispatch: vi.fn(),
      vault: { updateSession } as unknown as OpenClawCredentialVault,
      getGatewayUrl: () => 'ws://127.0.0.1:18789',
      transcript: { replace: vi.fn(), loadHistory: vi.fn().mockResolvedValue(undefined) },
      resetConversation: vi.fn(), bind, applyRuntime: vi.fn(), loadContextUsage: vi.fn().mockResolvedValue(undefined),
    }
    const typedInput = input as unknown as Parameters<typeof openOpenClawSession>[0]
    const a = openOpenClawSession(typedInput, 'session-a')
    const b = openOpenClawSession(typedInput, 'session-b')
    second.resolve({ session: { key: 'session-b' } })
    await expect(b).resolves.toBe(true)
    first.resolve({ session: { key: 'session-a' } })
    await expect(a).resolves.toBe(false)
    expect(bind).toHaveBeenCalledTimes(1)
    expect(bind).toHaveBeenCalledWith('main', 'session-b')
    expect(updateSession).toHaveBeenCalledTimes(1)
    expect(updateSession).toHaveBeenCalledWith('user', 'ws://127.0.0.1:18789', 'session-b', expect.any(Function))
  })
})
