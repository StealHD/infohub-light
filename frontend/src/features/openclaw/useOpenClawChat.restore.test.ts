import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { OpenClawCredentialVault, type StoredOpenClawCredential } from './openclawCredentialVault'
import type { OpenClawChatOptions } from './openclawContracts'
import type { GatewayHello } from './openclawGateway'
import { MemoryAdapter, agents, models } from './useOpenClawChat.test.support'
import { useOpenClawChat } from './useOpenClawChat'

it('finishes a delayed automatic restore across startup rerenders with the owning Agent', async () => {
  const vault = new OpenClawCredentialVault(new MemoryAdapter())
  const key = 'agent:research:dashboard:old'
  await vault.save('restore-user', 'ws://127.0.0.1:18789', {
    identity: { deviceId: 'test', publicKey: 'test', privateKey: {} as CryptoKey },
    deviceToken: 'fixture', scopes: ['operator.read', 'operator.write'], sessionKey: key,
  })
  const saved = await vault.load('restore-user', 'ws://127.0.0.1:18789')
  let finish!: (value: StoredOpenClawCredential | null) => void
  vi.spyOn(vault, 'load').mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  const request = vi.fn(async (method: string) => {
    if (method === 'sessions.describe') return { session: { key, agentId: 'research', modelProvider: 'openai', model: 'gpt-5.4' } }
    if (method === 'models.list') return models
    if (method === 'agents.list') return agents
    if (method === 'chat.history') return { messages: [] }
    if (method === 'sessions.list') return { sessions: [{ key }] }
    if (method === 'tools.effective') return { groups: [] }
    throw new Error(`Unexpected ${method}`)
  })
  const connect = vi.fn(async (): Promise<GatewayHello> => ({ protocol: 4, auth: { deviceToken: 'fixture', scopes: ['operator.read', 'operator.write'] }, snapshot: { sessionDefaults: { defaultAgentId: 'main' } } }))
  const options = { enabled: true, userId: 'restore-user', defaultGatewayUrl: 'ws://127.0.0.1:18789', vault, clientFactory: (() => ({ request, connect, close: vi.fn() })) as OpenClawChatOptions['clientFactory'] }
  const { result, rerender } = renderHook(() => useOpenClawChat(options))
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  rerender()
  await act(async () => finish(saved))
  await waitFor(() => expect(result.current.status).toBe('connected'))
  expect(result.current.sessionKey).toBe(key)
  expect(request).toHaveBeenCalledWith('tools.effective', { sessionKey: key, agentId: 'research' })
  expect(connect).toHaveBeenCalledTimes(1)
  expect(request.mock.calls.some(([method]) => method === 'sessions.create')).toBe(false)
})
