import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { buildAgentHandoffPrompt } from '../workbench-live/agentContext'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import type { GatewayEvent, GatewayHello } from './openclawGateway'
import { MemoryAdapter, agents, models, session } from './useOpenClawChat.test.support'
import { useOpenClawChat } from './useOpenClawChat'

vi.mock('./openclawGateway', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./openclawGateway')>()
  return {
    ...actual,
    generateDeviceIdentity: vi.fn(async () => ({
      deviceId: 'generated-device',
      publicKey: 'generated-public-key',
      privateKey: {} as CryptoKey,
    })),
  }
})

vi.mock('./openclawDevice', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./openclawDevice')>()
  return { ...actual, forgetOpenClawBrowser: vi.fn() }
})

describe('useOpenClawChat', () => {

  beforeEach(() => {
    window.sessionStorage.clear()
    vi.mocked(forgetOpenClawBrowser).mockReset()
    vi.mocked(forgetOpenClawBrowser).mockResolvedValue('removed')
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
    let sendCount = 0
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [{ tools: [{ id: 'mcp__inteliscope__get_item', source: 'mcp' }] }] }
      if (method === 'chat.history') return { messages: [{ id: 'history-1', role: 'assistant', text: '已有消息' }] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'sessions.patch') return { ok: true }
      if (method === 'chat.send') {
        sendCount += 1
        return { runId: `run-${sendCount}` }
      }
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
      id: `${model.provider}/${model.id}`,
      name: model.name,
      provider: model.provider,
      contextWindow: model.contextWindow,
      reasoning: model.reasoning,
      supportsImages: false,
    })))
    expect(result.current.thinkingOptions).toEqual(agents.agents[0].thinkingLevels)
    expect(result.current.runtimeSelection).toMatchObject({ modelId: 'openai/gpt-5.4', thinkingLevel: 'high' })

    await act(async () => { await result.current.setThinking('low') })
    expect(result.current.runtimeSelection.thinkingLevel).toBe('low')

    const contextItems = [{
      articleId: 'article-1',
      title: 'A',
      sourceName: '来源 A',
      sourceUrl: 'https://example.com/a?utm_source=feed&keep=yes',
    }]
    const gatewayPrompt = buildAgentHandoffPrompt({ userId: 'user-a', question: '分析 article-1', items: contextItems })
    await act(async () => {
      await result.current.send({
        displayText: '分析 article-1',
        gatewayPrompt,
        contextItems,
      })
    })
    expect(request).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      sessionKey: 'session-1',
      agentId: 'main',
      message: gatewayPrompt,
      deliver: false,
      idempotencyKey: expect.any(String),
      thinking: 'low',
    }))
    expect(result.current.messages.at(-1)).toMatchObject({
      role: 'user',
      text: '分析 article-1',
      contextCount: 1,
      contextSources: [{ title: 'A', sourceName: '来源 A', url: 'https://example.com/a?keep=yes' }],
      status: 'sent',
    })

    act(() => gatewayEvent?.({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-1',
        runId: 'run-1',
        seq: 1,
        stream: 'thinking',
        ts: Date.now(),
        data: { text: 'PRIVATE_CHAIN_OF_THOUGHT' },
      },
    }))
    expect(result.current.runTrace).toMatchObject({ runId: 'run-1', phase: 'thinking', status: 'running' })
    act(() => gatewayEvent?.({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-1',
        runId: 'run-1',
        seq: 2,
        stream: 'tool',
        ts: Date.now(),
        data: {
          phase: 'start',
          name: 'mcp__inteliscope__get_item',
          toolCallId: 'call-item',
          args: { article_id: 'PRIVATE_ARTICLE_ID' },
        },
      },
    }))
    expect(result.current.runTrace).toMatchObject({
      phase: 'using_tool',
      activities: [expect.objectContaining({ label: '接收 1 条上下文', status: 'completed' }), expect.objectContaining({ label: '读取文章详情', status: 'running' })],
    })
    expect(JSON.stringify(result.current.runTrace)).not.toMatch(/PRIVATE_CHAIN_OF_THOUGHT|PRIVATE_ARTICLE_ID/u)
    const activitiesAfterStart = result.current.runTrace?.activities
    act(() => gatewayEvent?.({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-1',
        runId: 'run-1',
        seq: 2,
        stream: 'tool',
        data: { phase: 'start', name: 'mcp__inteliscope__get_item', toolCallId: 'call-item' },
      },
    }))
    act(() => gatewayEvent?.({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-1',
        runId: 'other-run',
        seq: 99,
        stream: 'tool',
        data: { phase: 'start', name: 'mcp__inteliscope__diagnose_job', toolCallId: 'wrong-run' },
      },
    }))
    expect(result.current.runTrace?.activities).toEqual(activitiesAfterStart)
    act(() => gatewayEvent?.({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-1',
        runId: 'run-1',
        seq: 3,
        stream: 'tool',
        ts: Date.now(),
        data: {
          phase: 'result',
          name: 'mcp__inteliscope__get_item',
          toolCallId: 'call-item',
          result: 'PRIVATE_TOOL_RESULT',
        },
      },
    }))
    expect(result.current.runTrace?.activities.at(-1)).toMatchObject({ label: '读取文章详情', status: 'completed' })
    expect(JSON.stringify(result.current.runTrace)).not.toContain('PRIVATE_TOOL_RESULT')

    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'delta', sessionKey: 'session-1', runId: 'run-1', seq: 1, deltaText: '流式回复' } }))
    expect(result.current.streamText).toBe('流式回复')
    expect(result.current.runTrace?.phase).toBe('streaming')
    const firstStreamCreatedAt = result.current.streamCreatedAt
    expect(firstStreamCreatedAt).toEqual(expect.any(Number))
    const now = vi.spyOn(Date, 'now').mockReturnValue((firstStreamCreatedAt ?? 0) + 60_000)
    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'delta', sessionKey: 'session-1', runId: 'run-1', seq: 2, deltaText: '继续' } }))
    expect(result.current.streamCreatedAt).toBe(firstStreamCreatedAt)
    now.mockRestore()
    await act(async () => { await result.current.stop() })
    expect(request).toHaveBeenCalledWith('chat.abort', expect.objectContaining({ sessionKey: 'session-1', runId: 'run-1' }))
    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'aborted', sessionKey: 'session-1', runId: 'run-1' } }))
    expect(result.current.streamText).toBe('')
    expect(result.current.messages.at(-1)).toMatchObject({ role: 'assistant', text: '流式回复继续', status: 'aborted' })
    expect(result.current.runTrace).toMatchObject({ status: 'aborted', phase: 'aborted' })

    await act(async () => {
      await result.current.send({ displayText: '第二个问题', gatewayPrompt: 'second gateway prompt', contextItems: [] })
    })
    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'delta', sessionKey: 'session-1', runId: 'run-2', seq: 1, deltaText: '第二个回答' } }))
    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'final', sessionKey: 'session-1', runId: 'run-2' } }))

    await waitFor(() => expect(result.current.messages.some((message) => message.text === '第二个回答')).toBe(true))
    expect(result.current.messages.some((message) => message.role === 'user' && message.text === '第二个问题')).toBe(true)
  })


  it('retries with the model and thinking snapshot captured by the failed send', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-retry', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
    })
    let sendAttempts = 0
    const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      void params
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'chat.send') {
        sendAttempts += 1
        if (sendAttempts === 1) throw new Error('temporary failure')
        return { runId: 'retry-run' }
      }
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
      enabled: true, userId: 'user-retry', defaultGatewayUrl: 'ws://127.0.0.1:18789', vault, clientFactory: clientFactory as never,
    }))
    await waitFor(() => expect(result.current.status).toBe('connected'))

    await act(async () => {
      await result.current.send({ displayText: '重试我', gatewayPrompt: 'gateway prompt', contextItems: [] })
    })
    await waitFor(() => expect(result.current.messages.at(-1)?.status).toBe('failed'))
    const messageId = result.current.messages.at(-1)!.id
    await act(async () => { await result.current.setThinking('low') })
    expect(result.current.runtimeSelection.thinkingLevel).toBe('low')

    await act(async () => { await result.current.retry(messageId) })
    const sendCalls = request.mock.calls.filter(([method]) => method === 'chat.send')
    expect(sendCalls).toHaveLength(2)
    expect(sendCalls[1][1]).toEqual(expect.objectContaining({
      message: 'gateway prompt',
      thinking: 'high',
    }))
  })


  it('forks and verifies the current session model without requiring admin scope', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-model', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
    })
    const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return params?.key === 'session-2'
        ? { session: { modelProvider: 'local', model: 'quick' } }
        : session
      if (method === 'sessions.create') return { key: 'session-2' }
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

    await act(async () => { await result.current.setThinking('low') })
    expect(result.current.runtimeSelection.thinkingLevel).toBe('low')
    expect(request.mock.calls.some(([method]) => method === 'sessions.patch')).toBe(false)

    await act(async () => { await result.current.setModel('local/quick') })
    expect(request).toHaveBeenCalledWith('sessions.create', {
      agentId: 'main',
      label: expect.stringMatching(/^Inscope · .+ · [0-9a-f]{16}$/u),
      parentSessionKey: 'session-1',
      fork: true,
      model: 'local/quick',
    })
    expect(result.current.sessionKey).toBe('session-2')
    expect(result.current.runtimeSelection).toMatchObject({ modelId: 'local/quick', thinkingLevel: null })
    expect(request.mock.calls.some(([method]) => method === 'sessions.patch')).toBe(false)
  })


  it('keeps a supported thinking override when a verified model fork stays compatible', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-thinking-fork', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
    })
    const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return params?.key === 'session-deep'
        ? {
            session: {
              modelProvider: 'openai',
              model: 'deep',
              thinkingLevels: agents.agents[0].thinkingLevels,
              thinkingDefault: 'low',
            },
          }
        : session
      if (method === 'sessions.create') return { key: 'session-deep' }
      if (method === 'chat.send') return { runId: 'run-deep' }
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
      enabled: true,
      userId: 'user-thinking-fork',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))
    await waitFor(() => expect(result.current.status).toBe('connected'))

    await act(async () => { await result.current.setThinking('low') })
    await act(async () => { await result.current.setModel('openai/deep') })

    expect(result.current.runtimeSelection).toMatchObject({ modelId: 'openai/deep', thinkingLevel: 'low' })
    await act(async () => {
      await result.current.send({ displayText: '继续', gatewayPrompt: 'private prompt', contextItems: [] })
    })
    expect(request).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      sessionKey: 'session-deep',
      thinking: 'low',
    }))
  })


  it('offers a verified blank-session fallback for an unavailable session model', async () => {
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
      if (method === 'sessions.create') return { key: 'session-fallback' }
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
    expect(result.current.runtimeSelection.modelId).toBeNull()
    expect(result.current.modelSwitchFallback).toEqual({ modelId: 'openai/gpt-5.4', modelName: 'GPT-5.4' })
    expect(request.mock.calls.some(([method]) => method === 'sessions.patch')).toBe(false)

    await act(async () => { await result.current.switchToBlankConversation() })
    expect(request).toHaveBeenCalledWith('sessions.create', {
      agentId: 'main',
      label: expect.stringMatching(/^Inscope · .+ · [0-9a-f]{16}$/u),
      model: 'openai/gpt-5.4',
    })
    expect(result.current.sessionKey).toBe('session-fallback')
    expect(result.current.runtimeSelection).toMatchObject({
      modelId: 'openai/gpt-5.4',
      thinkingLevel: null,
      defaultThinkingLevel: 'medium',
    })
    expect(result.current.thinkingOptions).toEqual([{ id: 'medium', label: '中等' }])
  })
})
