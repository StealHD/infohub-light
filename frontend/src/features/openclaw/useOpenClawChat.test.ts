import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { OpenClawCredentialVault } from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import {
  OPENCLAW_CURRENT_SCOPES,
  OPENCLAW_LEGACY_SCOPES,
  GatewayRequestError,
  type GatewayEvent,
  type GatewayHello,
} from './openclawGateway'
import { MemoryAdapter, agents, models, session } from './useOpenClawChat.test.support'
import {
  projectOpenClawAgentEvent,
  projectOpenClawContextUsage,
  projectOpenClawRuntime,
  useOpenClawChat,
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

describe('useOpenClawChat', () => {

  beforeEach(() => {
    window.sessionStorage.clear()
    vi.mocked(forgetOpenClawBrowser).mockReset()
    vi.mocked(forgetOpenClawBrowser).mockResolvedValue('removed')
  })

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
      payload: {
        sessionKey: 'session-safe', runId: 'run-safe', seq: 5, stream: 'tool',
        data: { phase: 'start', name: 'mcp__inteliscope__resolve_source', args: { candidate_urls: ['NEVER_RENDER'] } },
      },
    }, 'session-safe')).toEqual(expect.objectContaining({
      toolKey: 'resolve_source',
      toolLabel: '验证公开来源',
    }))
    expect(projectOpenClawAgentEvent({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-safe', runId: 'run-safe', seq: 6, stream: 'tool',
        data: { phase: 'start', name: 'web_search', result: 'NEVER_RENDER' },
      },
    }, 'session-safe')).toEqual(expect.objectContaining({
      toolKey: 'web_search',
      toolLabel: '搜索公开网页',
    }))
    expect(projectOpenClawAgentEvent({
      type: 'event',
      event: 'agent',
      payload: { sessionKey: 'other', runId: 'run-safe', seq: 5, stream: 'thinking', data: { text: 'private reasoning' } },
    }, 'session-safe')).toBeNull()
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
          code: 'INVALID_REQUEST', message: 'label already in use: Inscope',
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
      label: expect.stringMatching(/^Inscope · .+ · [0-9a-f]{16}$/u),
    })
    expect(calls[1][1]).toEqual({
      agentId: 'main',
      label: expect.stringMatching(/^Inscope · .+ · [0-9a-f]{16}$/u),
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
          code: 'INVALID_REQUEST', message: 'label already in use: Inscope',
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
      label: expect.stringMatching(/^Inscope · .+ · [0-9a-f]{16}$/u),
    })
    expect(result.current.sessionKey).toBe('session-2')
  })
})
