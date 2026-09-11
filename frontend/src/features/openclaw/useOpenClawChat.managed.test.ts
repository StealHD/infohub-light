import { createElement, StrictMode, type ReactNode } from 'react'
import { canAutoConnectManaged } from './storage/openclawManagedSession'
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import type { OpenClawClientPort } from './openclawContracts'
import { useOpenClawChat } from './useOpenClawChat'
import { MemoryAdapter, agents, models, session } from './useOpenClawChat.test.support'

vi.mock('./gateway/openclawDeviceIdentity', async (load) => ({
  ...await load<typeof import('./gateway/openclawDeviceIdentity')>(),
  generateDeviceIdentity: vi.fn(async () => ({deviceId:'unused',publicKey:'unused',privateKey:{} as CryptoKey})),
}))

describe('server managed chat lifecycle', () => {
  it.each([false, true])('auto-connects and restores without credentials (StrictMode=%s)', async (strict) => {
    sessionStorage.clear()
    localStorage.clear()
    const adapter = new MemoryAdapter()
    const request = vi.fn(async (method: string) => {
      if (method === 'sessions.create') return {key:'agent:main:managed'}
      if (method === 'sessions.describe') return {session:{...session.session,key:'agent:main:managed',agentId:'main'}}
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'chat.history') return {messages:[]}
      if (method === 'tools.effective') return {tools:[]}
      if (method === 'chat.send') return {runId:'managed-run'}
      return {}
    })
    const factory = vi.fn(() => ({
      request: request as OpenClawClientPort['request'],
      connect: vi.fn(async () => ({protocol:4,auth:{role:'operator',scopes:['operator.read','operator.write']},snapshot:{sessionDefaults:{defaultAgentId:'main'}}})),
      close:vi.fn(),
    }))
    const options = {enabled:true,userId:'managed-owner',defaultGatewayUrl:'/api/me/openclaw/socket',vault:new OpenClawCredentialVault(adapter),clientFactory:factory}
    const wrapper = ({ children }: { children: ReactNode }) => strict ? createElement(StrictMode, null, children) : children
    expect(canAutoConnectManaged(options.userId)).toBe(false)
    const hook = renderHook(() => useOpenClawChat(options), { wrapper })
    await act(async () => { await Promise.resolve() })
    expect(factory).not.toHaveBeenCalled()
    await act(async () => { await hook.result.current.connect() })
    await waitFor(() => expect(hook.result.current.status).toBe('connected'))
    expect(canAutoConnectManaged(options.userId)).toBe(true)
    expect(canAutoConnectManaged('another-user')).toBe(false)
    expect(adapter.puts).toHaveLength(0)
    expect(sessionStorage.getItem('infohub-managed-session:managed-owner')).toBe('agent:main:managed')
    await act(async () => { await hook.result.current.send({displayText:'hello',gatewayPrompt:'hello',contextItems:[]}) })
    expect(request).toHaveBeenCalledWith('chat.send',expect.objectContaining({sessionKey:'agent:main:managed',agentId:'main',message:'hello',deliver:false}))
    const connectedClient = factory.mock.results.at(-1)!.value
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })
    expect(connectedClient.close).not.toHaveBeenCalled()
    act(() => { window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })) })
    expect(connectedClient.close).toHaveBeenCalledTimes(1)
    expect(request.mock.calls.some(([method]) => method === 'chat.abort')).toBe(false)
    act(() => { window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })) })
    await waitFor(() => expect(hook.result.current.status).toBe('connected'))
    expect(factory.mock.results.at(-1)!.value).not.toBe(connectedClient)
    hook.unmount()
    expect(factory.mock.results.at(-1)!.value.close).toHaveBeenCalledTimes(1)
    const restored = renderHook(() => useOpenClawChat(options), { wrapper })
    await waitFor(() => expect(restored.result.current.status).toBe('connected'))
    expect(request.mock.calls.filter(([method]) => method === 'sessions.create')).toHaveLength(1)
    expect(adapter.puts).toHaveLength(0)
    restored.unmount()
  })
})
