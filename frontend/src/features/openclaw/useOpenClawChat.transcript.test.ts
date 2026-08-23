import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { buildAgentHandoffPrompt } from '../workbench-live/agentContext'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import {
  OPENCLAW_CURRENT_SCOPES,
  type GatewayEvent,
  type GatewayHello,
} from './openclawGateway'
import { MemoryAdapter, agents, models, session } from './useOpenClawChat.test.support'
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

describe('useOpenClawChat', () => {

  beforeEach(() => {
    window.sessionStorage.clear()
    vi.mocked(forgetOpenClawBrowser).mockReset()
    vi.mocked(forgetOpenClawBrowser).mockResolvedValue('removed')
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
      items: [{ articleId: 'internal-id', title: '标题', sourceName: '来源', sourceUrl: 'https://example.com/story?utm_source=test' }],
    })
    expect(gatewayPrompt).toContain('[INTELISCOPE_HANDOFF_V8]')
    expect(projectChatHistory({ messages: [{ id: 'user-1', role: 'user', text: gatewayPrompt }] })).toEqual([
      expect.objectContaining({
        id: 'user-1', role: 'user', text: '只显示这个问题', status: 'sent', contextCount: 1, origin: 'gateway',
        contextSources: [{ title: '标题', sourceName: '来源', url: 'https://example.com/story' }],
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


  it('sends image attachments through a stock Gateway without the optional media-ticket RPC', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-image-input', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-image', publicKey: 'public-image', privateKey: {} as CryptoKey },
      deviceToken: 'device-token',
      scopes: [...OPENCLAW_CURRENT_SCOPES],
      sessionKey: 'session-image',
    })
    const imageModels = {
      models: [{ ...models.models[0], input: ['text', 'image'] }],
    }
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [] }
      if (method === 'chat.history') return { messages: [] }
      if (method === 'models.list') return imageModels
      if (method === 'agents.list') return agents
      if (method === 'sessions.describe') return session
      if (method === 'chat.send') return { runId: 'run-image' }
      throw new Error(`unexpected method ${method}`)
    })
    const clientFactory = vi.fn(() => ({
      connect: async (): Promise<GatewayHello> => ({
        protocol: 4,
        auth: { deviceToken: 'device-token', role: 'operator', scopes: [...OPENCLAW_CURRENT_SCOPES] },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      }),
      request,
      close: vi.fn(),
    }))

    const { result } = renderHook(() => useOpenClawChat({
      enabled: true,
      imageIoEnabled: true,
      userId: 'user-image-input',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
      vault,
      clientFactory: clientFactory as never,
    }))

    await waitFor(() => expect(result.current.status).toBe('connected'))
    expect(result.current.imageInputAvailable).toBe(true)
    await act(async () => {
      await result.current.send({
        displayText: '',
        gatewayPrompt: '请分析所附图片',
        contextItems: [],
        attachments: [{
          id: 'image-1',
          mimeType: 'image/webp',
          fileName: 'image-1.webp',
          content: 'AAAA',
          previewUrl: 'blob:image-1',
          width: 1,
          height: 1,
          byteLength: 3,
        }],
      })
    })

    expect(request).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      sessionKey: 'session-image',
      attachments: [{
        type: 'image',
        mimeType: 'image/webp',
        fileName: 'image-1.webp',
        content: 'AAAA',
      }],
    }))
    expect(request).not.toHaveBeenCalledWith('chat.media.ticket', expect.anything())
  })
})
