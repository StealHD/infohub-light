import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OpenClawGatewayClientOptions } from './openclawGateway'
import type { OpenClawClientPort } from './openclawContracts'
import { rememberManagedConnection, saveManagedSession } from './storage/openclawManagedSession'
import { useOpenClawChat } from './useOpenClawChat'
import { agents, models, session } from './useOpenClawChat.test.support'

vi.mock('./gateway/openclawDeviceIdentity', async (load) => ({
  ...await load<typeof import('./gateway/openclawDeviceIdentity')>(),
  generateDeviceIdentity: vi.fn(async () => ({deviceId:'unused',publicKey:'unused',privateKey:{} as CryptoKey})),
}))

describe('managed OpenClaw reconnect recovery', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    sessionStorage.clear()
    localStorage.clear()
  })
  afterEach(() => { vi.useRealTimers() })

  async function settleConnection(): Promise<void> {
    await act(async () => {
      await vi.dynamicImportSettled()
      await Promise.resolve()
    })
  }

  it('keeps the current run through a failed attempt and never resends chat', async () => {
    const userId = 'managed-recovery-user'
    rememberManagedConnection(userId)
    saveManagedSession(userId, 'agent:main:managed-recovery')
    const request = vi.fn(async (method: string) => {
      if (method === 'sessions.describe') return {session:{...session.session,key:'agent:main:managed-recovery',agentId:'main'}}
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'chat.history') return {messages:[]}
      if (method === 'tools.effective') return {tools:[]}
      if (method === 'chat.send') return {runId:'run-before-disconnect'}
      return {}
    })
    const connectionOptions: OpenClawGatewayClientOptions[] = []
    let attempt = 0
    const factory = vi.fn((options: OpenClawGatewayClientOptions) => {
      connectionOptions.push(options)
      attempt += 1
      return {
        request: request as OpenClawClientPort['request'],
        close: vi.fn(),
        connect: vi.fn(async () => {
          if (attempt === 2) throw new Error('temporary network unavailable')
          return {protocol:4,auth:{role:'operator',scopes:['operator.read','operator.write']},snapshot:{sessionDefaults:{defaultAgentId:'main'}}}
        }),
      }
    })
    const hook = renderHook(() => useOpenClawChat({
      enabled: true, userId, defaultGatewayUrl: '/api/me/openclaw/socket', clientFactory: factory,
    }))
    await settleConnection()
    expect(hook.result.current.status).toBe('connected')
    await act(async () => {
      await hook.result.current.send({displayText:'keep this turn',gatewayPrompt:'keep this turn',contextItems:[]})
    })
    expect(hook.result.current.runTrace?.runId).toBe('run-before-disconnect')

    act(() => connectionOptions[0].onClose?.({code:1006}))
    await settleConnection()
    await act(async () => { await vi.advanceTimersByTimeAsync(1_500) })
    await settleConnection()
    expect(factory).toHaveBeenCalledTimes(2)
    expect(hook.result.current.status).toBe('reconnecting')
    expect(hook.result.current.runTrace?.runId).toBe('run-before-disconnect')
    expect(request.mock.calls.filter(([method]) => method === 'chat.send')).toHaveLength(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(2_500) })
    await settleConnection()
    expect(hook.result.current.status).toBe('connected')
    expect(factory).toHaveBeenCalledTimes(3)
    expect(request.mock.calls.filter(([method]) => method === 'chat.send')).toHaveLength(1)
    hook.unmount()
  })

  it('stops reconnecting when the relay reports an expired login or binding', async () => {
    const userId = 'managed-terminal-user'
    rememberManagedConnection(userId)
    saveManagedSession(userId, 'agent:main:managed-terminal')
    let options: OpenClawGatewayClientOptions | undefined
    const request = vi.fn(async (method: string) => {
      if (method === 'sessions.describe') return {session:{...session.session,key:'agent:main:managed-terminal',agentId:'main'}}
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'chat.history') return {messages:[]}
      if (method === 'tools.effective') return {tools:[]}
      return {}
    })
    const factory = vi.fn((value: OpenClawGatewayClientOptions) => {
      options = value
      return {
        request: request as OpenClawClientPort['request'],
        close: vi.fn(),
        connect: vi.fn(async () => ({protocol:4,auth:{role:'operator',scopes:['operator.read','operator.write']},snapshot:{sessionDefaults:{defaultAgentId:'main'}}})),
      }
    })
    const hook = renderHook(() => useOpenClawChat({
      enabled: true, userId, defaultGatewayUrl: '/api/me/openclaw/socket', clientFactory: factory,
    }))
    await settleConnection()
    expect(hook.result.current.status).toBe('connected')
    act(() => options?.onClose?.({code:1008}))
    expect(hook.result.current.status).toBe('error')
    expect(hook.result.current.issue?.kind).toBe('auth')
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(factory).toHaveBeenCalledOnce()
    hook.unmount()
  })
})
