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
  it('auto-connects, sends, and reconnects without saving upstream credentials', async () => {
    sessionStorage.clear()
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
    const hook = renderHook(() => useOpenClawChat(options))
    await waitFor(() => expect(hook.result.current.status).toBe('connected'))
    expect(adapter.puts).toHaveLength(0)
    expect(sessionStorage.getItem('infohub-managed-session:managed-owner')).toBe('agent:main:managed')
    await act(async () => { await hook.result.current.send({displayText:'hello',gatewayPrompt:'hello',contextItems:[]}) })
    expect(request).toHaveBeenCalledWith('chat.send',expect.objectContaining({sessionKey:'agent:main:managed',agentId:'main',message:'hello',deliver:false}))
    hook.unmount()
    const restored = renderHook(() => useOpenClawChat(options))
    await waitFor(() => expect(restored.result.current.status).toBe('connected'))
    expect(request.mock.calls.filter(([method]) => method === 'sessions.create')).toHaveLength(1)
    expect(adapter.puts).toHaveLength(0)
    restored.unmount()
  })
})
