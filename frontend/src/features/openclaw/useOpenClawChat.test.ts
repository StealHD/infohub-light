import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { buildAgentHandoffPrompt } from '../workbench-live/agentContext'
import {
  OpenClawCredentialVault,
  type OpenClawCredentialAdapter,
  type StoredOpenClawCredential,
} from './openclawCredentialVault'
import type { GatewayEvent, GatewayHello } from './openclawGateway'
import { boundChatMessages, projectChatHistory, useOpenClawChat } from './useOpenClawChat'

class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => { this.values.set(value.id, value) }
  delete = async (key: string) => { this.values.delete(key) }
}

const models = {
  models: [
    { id: 'openai/gpt-5.4', name: 'GPT-5.4', provider: 'openai', available: true, contextWindow: 200_000, reasoning: true },
    { id: 'local/quick', name: 'Quick', provider: 'local', available: true, contextWindow: 32_000, reasoning: false },
  ],
}
const agents = {
  defaultId: 'main',
  agents: [{
    id: 'main',
    model: { primary: 'openai/gpt-5.4' },
    thinkingLevels: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }],
    thinkingDefault: 'low',
  }],
}
const session = {
  session: { modelProvider: 'openai', model: 'gpt-5.4', thinkingLevel: 'high' },
}

describe('useOpenClawChat', () => {
  it('does not create a Gateway client while browser chat is disabled', async () => {
    const clientFactory = vi.fn()
    const { result } = renderHook(() => useOpenClawChat({
      enabled: false,
      userId: 'user-disabled',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault: new OpenClawCredentialVault(new MemoryAdapter()),
      clientFactory: clientFactory as never,
    }))

    await act(async () => { await Promise.resolve() })
    expect(result.current.status).toBe('disabled')
    expect(clientFactory).not.toHaveBeenCalled()
  })

  it('bounds browser-visible history and projects versioned handoffs without exposing MCP instructions', () => {
    const bounded = boundChatMessages(Array.from({ length: 120 }, (_, index) => ({
      id: String(index),
      role: index % 2 ? 'assistant' as const : 'user' as const,
      text: 'X'.repeat(1500),
    })))
    expect(bounded.length).toBeLessThanOrEqual(100)
    expect(bounded.reduce((total, message) => total + message.text.length, 0)).toBeLessThanOrEqual(100_000)
    expect(bounded.at(-1)?.id).toBe('119')

    const gatewayPrompt = buildAgentHandoffPrompt({
      userId: 'user-a',
      question: '只显示这个问题',
      items: [{ articleId: 'internal-id', title: '标题' }],
    })
    expect(projectChatHistory({ messages: [{ id: 'user-1', role: 'user', text: gatewayPrompt }] })).toEqual([{
      id: 'user-1', role: 'user', text: '只显示这个问题', status: 'sent', contextCount: 1,
    }])
  })

  it('restores a session, uses real model metadata, sends separate display text and retains a partial aborted reply', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-a', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token',
      scopes: ['operator.read', 'operator.write'],
      sessionKey: 'session-1',
    })

    let gatewayEvent: ((event: GatewayEvent) => void) | undefined
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [{ tools: [{ id: 'mcp__inteliscope__get_item', source: 'mcp' }] }] }
      if (method === 'chat.history') return { messages: [{ id: 'history-1', role: 'assistant', text: '已有消息' }] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'sessions.patch') return { ok: true }
      if (method === 'chat.send') return { runId: 'run-1' }
      if (method === 'chat.abort') return { ok: true }
      throw new Error(`unexpected method ${method}`)
    })
    const connect = vi.fn(async (): Promise<GatewayHello> => ({
      protocol: 4,
      auth: { deviceToken: 'device-token', role: 'operator', scopes: ['operator.read', 'operator.write'] },
      snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
    }))
    const close = vi.fn()
    const clientFactory = vi.fn((options: { onEvent?: (event: GatewayEvent) => void }) => {
      gatewayEvent = options.onEvent
      return { connect, request, close }
    })

    const { result } = renderHook(() => useOpenClawChat({
      enabled: true,
      userId: 'user-a',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    expect(result.current.toolsStatus).toBe('available')
    expect(result.current.models).toEqual(models.models.map((model) => ({
      id: model.id,
      name: model.name,
      provider: model.provider,
      contextWindow: model.contextWindow,
      reasoning: model.reasoning,
    })))
    expect(result.current.thinkingOptions).toEqual(agents.agents[0].thinkingLevels)
    expect(result.current.runtimeSelection).toMatchObject({ modelId: 'openai/gpt-5.4', thinkingLevel: 'high' })

    const gatewayPrompt = buildAgentHandoffPrompt({ userId: 'user-a', question: '分析 article-1', items: [{ articleId: 'article-1', title: 'A' }] })
    await act(async () => {
      await result.current.send({
        displayText: '分析 article-1',
        gatewayPrompt,
        contextItems: [{ articleId: 'article-1', title: 'A' }],
      })
    })
    expect(request).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      sessionKey: 'session-1',
      agentId: 'main',
      message: gatewayPrompt,
      deliver: false,
      idempotencyKey: expect.any(String),
    }))
    expect(result.current.messages.at(-1)).toMatchObject({ role: 'user', text: '分析 article-1', contextCount: 1, status: 'sent' })

    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'delta', sessionKey: 'session-1', runId: 'run-1', seq: 1, deltaText: '流式回复' } }))
    expect(result.current.streamText).toBe('流式回复')
    await act(async () => { await result.current.stop() })
    expect(request).toHaveBeenCalledWith('chat.abort', expect.objectContaining({ sessionKey: 'session-1', runId: 'run-1' }))
    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'aborted', sessionKey: 'session-1', runId: 'run-1' } }))
    expect(result.current.streamText).toBe('')
    expect(result.current.messages.at(-1)).toMatchObject({ role: 'assistant', text: '流式回复', status: 'aborted' })
  })

  it('patches only the current session model and thinking level', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-model', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
    })
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'sessions.patch') return { ok: true }
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({
        auth: { deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'] },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      })),
      request,
      close: vi.fn(),
    }))
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true, userId: 'user-model', defaultGatewayUrl: 'ws://127.0.0.1:18789', vault, clientFactory: clientFactory as never,
    }))
    await waitFor(() => expect(result.current.status).toBe('connected'))

    await act(async () => { await result.current.setModel('local/quick') })
    expect(request).toHaveBeenCalledWith('sessions.patch', { key: 'session-1', agentId: 'main', model: 'local/quick', thinkingLevel: null })
    await act(async () => { await result.current.setThinking('low') })
    expect(request).toHaveBeenCalledWith('sessions.patch', { key: 'session-1', agentId: 'main', thinkingLevel: 'low' })
  })

  it('falls back from an unavailable session model and uses session-specific thinking levels', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-fallback', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
    })
    let described = 0
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') {
        described += 1
        return {
          session: {
            modelProvider: described === 1 ? 'removed' : 'openai',
            model: described === 1 ? 'unavailable-model' : 'gpt-5.4',
            thinkingLevel: 'medium',
            thinkingLevels: [{ id: 'medium', label: '中等' }],
            thinkingDefault: 'medium',
          },
        }
      }
      if (method === 'sessions.patch') return { ok: true }
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({
        auth: { deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'] },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      })),
      request,
      close: vi.fn(),
    }))
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true, userId: 'user-fallback', defaultGatewayUrl: 'ws://127.0.0.1:18789', vault, clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    expect(request).toHaveBeenCalledWith('sessions.patch', { key: 'session-1', agentId: 'main', model: null })
    expect(result.current.runtimeSelection).toMatchObject({
      modelId: 'openai/gpt-5.4',
      thinkingLevel: 'medium',
      defaultThinkingLevel: 'medium',
    })
    expect(result.current.thinkingOptions).toEqual([{ id: 'medium', label: '中等' }])
  })
})
