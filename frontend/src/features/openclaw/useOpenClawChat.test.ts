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
  projectOpenClawAgentEvent,
  projectOpenClawContextUsage,
  projectOpenClawRuntime,
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
  session: {
    modelProvider: 'openai',
    model: 'gpt-5.4',
    thinkingLevel: 'high',
    thinkingLevels: agents.agents[0].thinkingLevels,
    thinkingDefault: 'low',
  },
}

describe('useOpenClawChat', () => {
  it('projects only bounded, allowlisted agent activity and drops private payload data', () => {
    const projected = projectOpenClawAgentEvent({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-safe',
        runId: 'run-safe',
        seq: 4,
        stream: 'tool',
        ts: 1_725_000_000_000,
        data: {
          phase: 'start',
          name: 'mcp__inteliscope__diagnose_source',
          toolCallId: 'call-safe',
          args: { token: 'NEVER_RENDER_TOKEN', url: 'https://secret.example' },
          result: 'NEVER_RENDER_RESULT',
          meta: { raw: 'NEVER_RENDER_META' },
          error: 'NEVER_RENDER_ERROR',
        },
      },
    }, 'session-safe')

    expect(projected).toEqual({
      runId: 'run-safe',
      seq: 4,
      stream: 'tool',
      phase: 'start',
      timestamp: 1_725_000_000_000,
      toolCallId: 'call-safe',
      toolKey: 'diagnose_source',
      toolLabel: '诊断来源',
      failed: false,
    })
    expect(JSON.stringify(projected)).not.toMatch(/NEVER_RENDER|secret\.example/u)
    expect(projectOpenClawAgentEvent({
      type: 'event',
      event: 'agent',
      payload: { sessionKey: 'other', runId: 'run-safe', seq: 5, stream: 'thinking', data: { text: 'private reasoning' } },
    }, 'session-safe')).toBeNull()
  })

  beforeEach(() => {
    window.sessionStorage.clear()
    vi.mocked(forgetOpenClawBrowser).mockReset()
    vi.mocked(forgetOpenClawBrowser).mockResolvedValue('removed')
  })

  it('accepts only fresh exact-session context usage', () => {
    const fresh = {
      sessions: [
        { key: 'other', totalTokens: 1, contextTokens: 10 },
        {
          key: 'session-usage',
          totalTokens: 42_000,
          totalTokensFresh: true,
          contextTokens: 200_000,
          modelProvider: 'openai',
          model: 'gpt-5.4',
        },
      ],
    }
    expect(projectOpenClawContextUsage(fresh, 'session-usage')).toEqual({
      sessionKey: 'session-usage',
      usedTokens: 42_000,
      contextTokens: 200_000,
      percent: 21,
      modelId: 'openai/gpt-5.4',
    })
    expect(projectOpenClawContextUsage({ sessionKey: 'other', totalTokens: 5, contextTokens: 10 }, 'session-usage')).toBeNull()
    expect(projectOpenClawContextUsage({ sessionKey: 'session-usage', totalTokens: 5, totalTokensFresh: false, contextTokens: 10 }, 'session-usage')).toBeNull()
    expect(projectOpenClawContextUsage({ sessionKey: 'session-usage', totalTokens: '5', contextTokens: 10 }, 'session-usage')).toBeNull()
  })

  it('projects thinking choices only from the exact model or current session', () => {
    const agentOnly = projectOpenClawRuntime(
      models,
      agents,
      { session: { modelProvider: 'openai', model: 'gpt-5.4', thinkingLevel: 'high' } },
      'main',
    )
    expect(agentOnly.thinkingOptions).toEqual([])
    expect(agentOnly.selection.thinkingLevel).toBeNull()

    const sessionSpecific = projectOpenClawRuntime(models, agents, session, 'main')
    expect(sessionSpecific.thinkingOptions).toEqual(agents.agents[0].thinkingLevels)
    expect(sessionSpecific.selection.thinkingLevel).toBe('high')

    const modelSpecific = projectOpenClawRuntime(
      {
        models: [{
          id: 'gpt-5.4',
          name: 'GPT-5.4',
          provider: 'openai',
          available: true,
          reasoning: true,
          thinkingLevels: [{ id: 'medium', label: '中等' }],
          thinkingDefault: 'medium',
        }],
      },
      agents,
      session,
      'main',
    )
    expect(modelSpecific.thinkingOptions).toEqual([{ id: 'medium', label: '中等' }])
    expect(modelSpecific.selection).toMatchObject({
      thinkingLevel: null,
      defaultThinkingLevel: 'medium',
    })
  })

  it('loads and subscribes to exact-session context usage without adopting another session', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-usage', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-usage', publicKey: 'public-usage', privateKey: {} as CryptoKey },
      deviceToken: 'device-token',
      scopes: [...OPENCLAW_CURRENT_SCOPES],
      sessionKey: 'session-usage',
    })
    let onEvent: ((event: GatewayEvent) => void) | undefined
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return models
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'sessions.subscribe') return {}
      if (method === 'sessions.list') return {
        sessions: [
          { key: 'other', totalTokens: 199_000, contextTokens: 200_000 },
          { key: 'session-usage', totalTokens: 42_000, totalTokensFresh: true, contextTokens: 200_000 },
        ],
      }
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn((options: { onEvent?: (event: GatewayEvent) => void }) => {
      onEvent = options.onEvent
      return {
        connect: vi.fn(async (): Promise<GatewayHello> => ({
          auth: { deviceToken: 'device-token', scopes: [...OPENCLAW_CURRENT_SCOPES] },
          snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
        })),
        request,
        close: vi.fn(),
      }
    })
    const { result } = renderHook(() => useOpenClawChat({
      enabled: true,
      userId: 'user-usage',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    expect(result.current.contextUsage).toMatchObject({ sessionKey: 'session-usage', usedTokens: 42_000, percent: 21 })
    expect(request).toHaveBeenCalledWith('sessions.list', { search: 'session-usage', limit: 100 })
    expect(request).toHaveBeenCalledWith('sessions.subscribe', {})

    act(() => onEvent?.({
      type: 'event',
      event: 'sessions.changed',
      payload: { sessionKey: 'session-usage', session: { totalTokens: 64_000, totalTokensFresh: true, contextTokens: 200_000 } },
    }))
    expect(result.current.contextUsage).toMatchObject({ usedTokens: 64_000, percent: 32 })

    act(() => onEvent?.({
      type: 'event', event: 'sessions.changed', payload: { sessionKey: 'other', totalTokens: 1, contextTokens: 200_000 },
    }))
    expect(result.current.contextUsage).toMatchObject({ usedTokens: 64_000 })

    act(() => onEvent?.({
      type: 'event', event: 'sessions.changed', payload: { sessionKey: 'session-usage', totalTokens: 70_000, totalTokensFresh: false, contextTokens: 200_000 },
    }))
    expect(result.current.contextUsage).toBeNull()
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
    expect(gatewayPrompt).toContain('[INTELISCOPE_HANDOFF_V5]')
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
    let resolveLateSend: ((value: { runId: string }) => void) | undefined
    let sendCalls = 0
    const sendResult = new Promise<{ runId: string }>((resolve) => { resolveSend = resolve })
    const lateSendResult = new Promise<{ runId: string }>((resolve) => { resolveLateSend = resolve })
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
      if (method === 'chat.send') {
        sendCalls += 1
        return sendCalls === 1 ? sendResult : lateSendResult
      }
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
    expect(result.current.runTrace).toMatchObject({
      phase: 'sending',
      status: 'running',
      activities: [],
    })
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

    let lateSend: Promise<boolean> | undefined
    act(() => {
      lateSend = result.current.send({
        displayText: '首字前停止',
        gatewayPrompt: 'PRIVATE_LATE_PROMPT',
        contextItems: [],
      })
    })
    act(() => gatewayEvent?.({
      type: 'event',
      event: 'chat',
      payload: { state: 'aborted', sessionKey: 'session-atomic', runId: 'run-late' },
    }))
    expect(result.current.isRunning).toBe(false)
    expect(result.current.runTrace).toMatchObject({ phase: 'aborted', status: 'aborted' })

    await act(async () => {
      resolveLateSend?.({ runId: 'run-late' })
      await lateSend
    })
    expect(result.current.isRunning).toBe(false)
    expect(result.current.runTrace).toMatchObject({ phase: 'aborted', status: 'aborted' })
    expect(result.current.messages.find((message) => message.text === '首字前停止')).toMatchObject({ status: 'sent' })
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
