import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  OpenClawCredentialVault,
  type OpenClawCredentialAdapter,
  type StoredOpenClawCredential,
} from './openclawCredentialVault'
import type { GatewayEvent, GatewayHello } from './openclawGateway'
import { boundChatMessages, useOpenClawChat } from './useOpenClawChat'

class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => { this.values.set(value.id, value) }
  delete = async (key: string) => { this.values.delete(key) }
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

  it('bounds browser-visible history by both message count and total text', () => {
    const bounded = boundChatMessages(Array.from({ length: 120 }, (_, index) => ({
      id: String(index),
      role: index % 2 ? 'assistant' as const : 'user' as const,
      text: 'X'.repeat(1500),
    })))

    expect(bounded.length).toBeLessThanOrEqual(100)
    expect(bounded.reduce((total, message) => total + message.text.length, 0)).toBeLessThanOrEqual(100_000)
    expect(bounded.at(-1)?.id).toBe('119')
  })

  it('restores a paired session, discovers tools, streams, sends idempotently and aborts', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())
    await vault.save('user-a', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token',
      scopes: ['operator.read', 'operator.write'],
      sessionKey: 'session-1',
    })

    let gatewayEvent: ((event: GatewayEvent) => void) | undefined
    let gatewayClose: (() => void) | undefined
    const request = vi.fn(async (method: string) => {
      if (method === 'tools.effective') return { groups: [{ tools: [{ id: 'mcp__inteliscope__get_item', source: 'mcp' }] }] }
      if (method === 'chat.history') return { messages: [{ id: 'history-1', role: 'assistant', text: '已有消息' }] }
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
    const clientFactory = vi.fn((options: { onEvent?: (event: GatewayEvent) => void; onClose?: () => void }) => {
      gatewayEvent = options.onEvent
      gatewayClose = options.onClose
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
    expect(connect).toHaveBeenCalledTimes(1)
    expect(result.current.toolsStatus).toBe('available')
    expect(result.current.messages).toEqual([{ id: 'history-1', role: 'assistant', text: '已有消息' }])

    await act(async () => { await result.current.send('分析 article-1', 'deep') })
    expect(request).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      sessionKey: 'session-1',
      agentId: 'main',
      message: '分析 article-1',
      thinking: 'high',
      deliver: false,
      idempotencyKey: expect.any(String),
    }))

    act(() => gatewayEvent?.({ type: 'event', event: 'chat', payload: { state: 'delta', sessionKey: 'session-1', runId: 'run-1', seq: 1, deltaText: '流式回复' } }))
    expect(result.current.streamText).toBe('流式回复')
    await act(async () => { await result.current.stop() })
    expect(request).toHaveBeenCalledWith('chat.abort', expect.objectContaining({ sessionKey: 'session-1', runId: 'run-1' }))

    act(() => gatewayClose?.())
    expect(result.current.status).toBe('reconnecting')
    await waitFor(() => expect(result.current.status).toBe('connected'), { timeout: 2500 })
    expect(clientFactory).toHaveBeenCalledTimes(2)
  })
})
