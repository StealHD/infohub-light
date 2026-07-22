import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { buildAgentHandoffPrompt } from '../workbench-live/agentContext'
import {
  OpenClawCredentialVault,
  type OpenClawCredentialAdapter,
  type StoredOpenClawCredential,
} from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import {
  OPENCLAW_CURRENT_SCOPES,
  OPENCLAW_LEGACY_SCOPES,
  GatewayRequestError,
  type GatewayEvent,
  type GatewayHello,
} from './openclawGateway'
import {
  boundChatMessages,
  mergeOpenClawTranscript,
  openClawTranscriptStorageKey,
  projectChatHistory,
  useOpenClawChat,
  writeOpenClawTranscript,
} from './useOpenClawChat'

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

class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  puts: StoredOpenClawCredential[] = []
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => {
    this.puts.push(value)
    this.values.set(value.id, value)
  }
  delete = async (key: string) => { this.values.delete(key) }
}

const models = {
  models: [
    { id: 'gpt-5.4', name: 'GPT-5.4', provider: 'openai', available: true, contextWindow: 200_000, reasoning: true },
    { id: 'deep', name: 'Deep', provider: 'openai', available: true, contextWindow: 160_000, reasoning: true },
    { id: 'quick', name: 'Quick', provider: 'local', available: true, contextWindow: 32_000, reasoning: false },
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
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.mocked(forgetOpenClawBrowser).mockReset()
    vi.mocked(forgetOpenClawBrowser).mockResolvedValue('removed')
  })

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

  it('uses server-first device removal before clearing the active chat state', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-forget', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-forget', publicKey: 'public-forget', privateKey: {} as CryptoKey },
      deviceToken: 'device-token',
      scopes: [...OPENCLAW_CURRENT_SCOPES],
      sessionKey: 'session-forget',
    })
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      throw new Error(`unexpected method ${method}`)
    })
    const close = vi.fn()
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({
        auth: { deviceToken: 'device-token', scopes: [...OPENCLAW_CURRENT_SCOPES] },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      })),
      request,
      close,
    }))
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true,
      userId: 'user-forget',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    await act(async () => { await result.current.forget() })

    expect(forgetOpenClawBrowser).toHaveBeenCalledWith(expect.objectContaining({
      userId: 'user-forget',
      gatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clearTranscripts: expect.any(Function),
      clientFactory,
    }))
    expect(close).toHaveBeenCalled()
    expect(result.current.status).toBe('idle')
  })

  it('retries one label collision with a fresh label and keeps all other session parameters', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-collision', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'],
    })
    let creates = 0
    const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      void params
      if (method === 'sessions.create') {
        creates += 1
        if (creates === 1) throw new GatewayRequestError({
          code: 'INVALID_REQUEST', message: 'label already in use: Inteliscope',
        })
        return { key: 'session-created' }
      }
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
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
      enabled: true, userId: 'user-collision', defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault, clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    const calls = request.mock.calls.filter(([method]) => method === 'sessions.create')
    expect(calls).toHaveLength(2)
    expect(calls[0][1]).toEqual({
      agentId: 'main',
      label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
    })
    expect(calls[1][1]).toEqual({
      agentId: 'main',
      label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
    })
    expect(calls[0][1]?.label).not.toBe(calls[1][1]?.label)
  })

  it('retains an exact-scope pairing when session setup fails and reuses it on retry', async () => {
    const adapter = new MemoryAdapter()
    const vault = new OpenClawCredentialVault(adapter)
    let creates = 0
    const request = vi.fn(async (method: string) => {
      if (method === 'sessions.create') {
        creates += 1
        if (creates <= 2) throw new GatewayRequestError({
          code: 'INVALID_REQUEST', message: 'label already in use: Inteliscope',
        })
        return { key: 'session-recovered' }
      }
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn((options: {
      bootstrapToken?: string
      deviceToken?: string
      requestedScopes?: readonly string[]
    }) => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({
        auth: { deviceToken: 'paired-device-token', scopes: [...OPENCLAW_CURRENT_SCOPES] },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      })),
      request,
      close: vi.fn(),
      options,
    }))
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true, userId: 'user-pairing', defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault, clientFactory: clientFactory as never,
    }))

    let firstSuccess = true
    await act(async () => { firstSuccess = await result.current.connect('bootstrap-token') })
    expect(firstSuccess).toBe(false)
    expect(clientFactory).toHaveBeenCalledTimes(1)
    expect(creates).toBe(2)
    expect(result.current.issue).toEqual(expect.objectContaining({
      kind: 'session',
      message: 'OpenClaw 会话名称冲突，请重新连接。',
    }))
    expect(adapter.puts[0]).toMatchObject({
      deviceToken: 'paired-device-token',
      scopes: OPENCLAW_CURRENT_SCOPES,
    })
    expect(adapter.puts[0].sessionKey).toBeUndefined()

    let secondSuccess = false
    await act(async () => { secondSuccess = await result.current.connect() })
    expect(clientFactory.mock.calls[0][0]).toMatchObject({
      bootstrapToken: 'bootstrap-token',
      requestedScopes: OPENCLAW_CURRENT_SCOPES,
    })
    expect(clientFactory.mock.calls[1][0]).toMatchObject({
      bootstrapToken: undefined,
      deviceToken: 'paired-device-token',
      requestedScopes: OPENCLAW_CURRENT_SCOPES,
    })
    expect(secondSuccess).toBe(true)
    expect(adapter.puts.at(-1)).toMatchObject({ sessionKey: 'session-recovered' })
  })

  it('keeps legacy reconnect scopes and upgrades the same identity when a bootstrap token is supplied', async () => {
    const adapter = new MemoryAdapter()
    const vault = new OpenClawCredentialVault(adapter)
    const identity = { deviceId: 'legacy-device', publicKey: 'legacy-public', privateKey: {} as CryptoKey }
    await vault.save('user-scope-upgrade', 'ws://127.0.0.1:18789', {
      identity,
      deviceToken: 'legacy-token',
      scopes: [...OPENCLAW_LEGACY_SCOPES],
      sessionKey: 'session-existing',
    })
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn((options: {
      bootstrapToken?: string
      requestedScopes?: readonly string[]
      deviceIdentity: typeof identity
    }) => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({
        auth: {
          deviceToken: options.bootstrapToken ? 'upgraded-token' : 'legacy-token',
          scopes: [...(options.requestedScopes ?? [])],
        },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      })),
      request,
      close: vi.fn(),
    }))
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true,
      userId: 'user-scope-upgrade',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    expect(clientFactory.mock.calls[0][0]).toMatchObject({
      deviceToken: 'legacy-token',
      requestedScopes: OPENCLAW_LEGACY_SCOPES,
      deviceIdentity: identity,
    })

    await act(async () => { await result.current.connect('bootstrap-token') })
    expect(clientFactory.mock.calls[1][0]).toMatchObject({
      bootstrapToken: 'bootstrap-token',
      deviceToken: undefined,
      requestedScopes: OPENCLAW_CURRENT_SCOPES,
      deviceIdentity: identity,
    })
    await expect(vault.load('user-scope-upgrade', 'ws://127.0.0.1:18789')).resolves.toMatchObject({
      identity,
      deviceToken: 'upgraded-token',
      scopes: OPENCLAW_CURRENT_SCOPES,
      sessionKey: 'session-existing',
    })
  })

  it('creates a uniquely labelled new conversation without changing runtime semantics', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-new', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
    })
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
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
      enabled: true, userId: 'user-new', defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault, clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    await act(async () => { await result.current.newConversation() })

    expect(request).toHaveBeenCalledWith('sessions.create', {
      agentId: 'main',
      label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
    })
    expect(result.current.sessionKey).toBe('session-2')
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
    expect(projectChatHistory({ messages: [{ id: 'user-1', role: 'user', text: gatewayPrompt }] })).toEqual([
      expect.objectContaining({
        id: 'user-1', role: 'user', text: '只显示这个问题', status: 'sent', contextCount: 1, origin: 'gateway',
      }),
    ])
  })

  it('merges Gateway history without dropping a local question and omits completed internal prompts from storage', () => {
    const snapshot = {
      displayText: '我的问题',
      gatewayPrompt: 'INTELISCOPE_INTERNAL_PROMPT',
      contextItems: [],
      idempotencyKey: 'local-user',
      modelId: null,
      thinkingLevel: null,
    }
    const local = [{
      id: 'local-user', role: 'user' as const, text: '我的问题', status: 'sent' as const,
      origin: 'local' as const, createdAt: 10, sendSnapshot: snapshot,
    }]
    const gateway = [{
      id: 'gateway-answer', role: 'assistant' as const, text: '回答', status: 'sent' as const,
      origin: 'gateway' as const, createdAt: 20,
    }]

    const merged = mergeOpenClawTranscript(local, gateway)
    expect(merged.map(({ role, text }) => ({ role, text }))).toEqual([
      { role: 'user', text: '我的问题' },
      { role: 'assistant', text: '回答' },
    ])

    writeOpenClawTranscript('user-merge', 'ws://127.0.0.1:18789', 'session-merge', merged)
    const stored = window.sessionStorage.getItem(openClawTranscriptStorageKey(
      'user-merge', 'ws://127.0.0.1:18789', 'session-merge',
    ))
    expect(stored).toContain('我的问题')
    expect(stored).not.toContain('INTELISCOPE_INTERNAL_PROMPT')
  })

  it('keeps the local display question when Gateway returns the same user turn with an internal prompt', () => {
    const snapshot = {
      displayText: '比较这两条信息的差异',
      gatewayPrompt: 'INTELISCOPE_HANDOFF_V3\nINTERNAL MCP get_item instructions',
      contextItems: [],
      idempotencyKey: 'turn-shared',
      modelId: null,
      thinkingLevel: null,
    }
    const local = [{
      id: 'local-question',
      role: 'user' as const,
      text: snapshot.displayText,
      status: 'pending' as const,
      origin: 'local' as const,
      createdAt: 10,
      clientTurnId: 'turn-shared',
      sendSnapshot: snapshot,
    }]
    const gateway = [{
      id: 'gateway-user-record',
      role: 'user' as const,
      text: snapshot.gatewayPrompt,
      status: 'sent' as const,
      origin: 'gateway' as const,
      createdAt: 11,
      clientTurnId: 'turn-shared',
    }]

    const merged = mergeOpenClawTranscript(local, gateway)

    expect(merged).toEqual([
      expect.objectContaining({
        id: 'local-question',
        role: 'user',
        text: snapshot.displayText,
        status: 'sent',
        origin: 'local',
        clientTurnId: 'turn-shared',
        sendSnapshot: undefined,
      }),
    ])
  })

  it('preserves repeated identical questions as separate conversation turns', () => {
    const local = [
      { id: 'local-1', role: 'user' as const, text: '继续分析', status: 'sent' as const, createdAt: 1_000, origin: 'local' as const },
      { id: 'local-2', role: 'user' as const, text: '继续分析', status: 'sent' as const, createdAt: 9_000, origin: 'local' as const },
    ]
    const gateway = [
      { id: 'gateway-1', role: 'user' as const, text: '继续分析', status: 'sent' as const, createdAt: 1_100, origin: 'gateway' as const },
      { id: 'gateway-2', role: 'user' as const, text: '继续分析', status: 'sent' as const, createdAt: 9_100, origin: 'gateway' as const },
    ]

    const merged = mergeOpenClawTranscript(local, gateway)

    expect(merged).toHaveLength(2)
    expect(merged.map((message) => message.id)).toEqual(['local-1', 'local-2'])
  })

  it('persists the user turn before Gateway send resolves and keeps it when history omits users', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-atomic', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-atomic',
    })
    let gatewayEvent: ((event: GatewayEvent) => void) | undefined
    let historyCalls = 0
    let resolveSend: ((value: { runId: string }) => void) | undefined
    const sendResult = new Promise<{ runId: string }>((resolve) => { resolveSend = resolve })
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') {
        historyCalls += 1
        return historyCalls === 1
          ? { messages: [] }
          : { messages: [{ id: 'remote-answer', role: 'assistant', text: '远端回答', createdAt: Date.now() }] }
      }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'chat.send') return sendResult
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn((options: { onEvent?: (event: GatewayEvent) => void }) => {
      gatewayEvent = options.onEvent
      return {
        connect: vi.fn(async (): Promise<GatewayHello> => ({
          auth: { deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'] },
          snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
        })),
        request,
        close: vi.fn(),
      }
    })
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true,
      userId: 'user-atomic',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))
    await waitFor(() => expect(result.current.status).toBe('connected'))

    let pendingSend: Promise<boolean> | undefined
    act(() => {
      pendingSend = result.current.send({
        displayText: '必须保留的问题',
        gatewayPrompt: 'INTELISCOPE_PRIVATE_GATEWAY_PROMPT',
        contextItems: [],
      })
    })

    const storedBeforeGateway = window.sessionStorage.getItem(openClawTranscriptStorageKey(
      'user-atomic', 'ws://127.0.0.1:18789', 'session-atomic',
    ))
    expect(storedBeforeGateway).toContain('必须保留的问题')
    expect(JSON.parse(storedBeforeGateway || '{}').messages[0]).toMatchObject({
      role: 'user',
      status: 'pending',
      clientTurnId: expect.any(String),
    })

    await act(async () => {
      resolveSend?.({ runId: 'run-atomic' })
      await pendingSend
    })
    act(() => gatewayEvent?.({
      type: 'event',
      event: 'chat',
      payload: { state: 'final', sessionKey: 'session-atomic', runId: 'run-atomic' },
    }))

    await waitFor(() => expect(result.current.messages.map(({ role, text }) => ({ role, text }))).toEqual([
      { role: 'user', text: '必须保留的问题' },
      { role: 'assistant', text: '远端回答' },
    ]))
    expect(historyCalls).toBeGreaterThan(1)
    const storedAfterHistory = window.sessionStorage.getItem(openClawTranscriptStorageKey(
      'user-atomic', 'ws://127.0.0.1:18789', 'session-atomic',
    ))
    expect(storedAfterHistory).toContain('必须保留的问题')
    expect(storedAfterHistory).not.toContain('INTELISCOPE_PRIVATE_GATEWAY_PROMPT')
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
    })))
    expect(result.current.thinkingOptions).toEqual(agents.agents[0].thinkingLevels)
    expect(result.current.runtimeSelection).toMatchObject({ modelId: 'openai/gpt-5.4', thinkingLevel: 'high' })

    await act(async () => { await result.current.setThinking('low') })
    expect(result.current.runtimeSelection.thinkingLevel).toBe('low')

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
      thinking: 'low',
    }))
    expect(result.current.messages.at(-1)).toMatchObject({ role: 'user', text: '分析 article-1', contextCount: 1, status: 'sent' })

    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'delta', sessionKey: 'session-1', runId: 'run-1', seq: 1, deltaText: '流式回复' } }))
    expect(result.current.streamText).toBe('流式回复')
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
      label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
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
      label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
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
