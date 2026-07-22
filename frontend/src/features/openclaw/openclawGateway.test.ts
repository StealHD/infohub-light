import { describe, expect, it, vi } from 'vitest'

import {
  OPENCLAW_CURRENT_SCOPES,
  OPENCLAW_LEGACY_SCOPES,
  OpenClawGatewayClient,
  buildDeviceAuthPayloadV3,
  parseOpenClawConnectionInput,
  validateGatewayUrl,
  validateNegotiatedScopes,
  validateStoredOpenClawScopes,
  type GatewaySocket,
} from './openclawGateway'

class FakeSocket implements GatewaySocket {
  readyState = 0
  sent: string[] = []
  listeners = new Map<string, Array<(event: unknown) => void>>()

  addEventListener(type: string, listener: (event: unknown) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  send(value: string) { this.sent.push(value) }
  close() { this.readyState = 3 }
  emit(type: string, event: unknown = {}) {
    if (type === 'open') this.readyState = 1
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
}

describe('OpenClaw Gateway connection input', () => {
  it('accepts loopback WS and remote WSS but rejects credential-bearing or plain remote WS URLs', () => {
    expect(validateGatewayUrl('ws://127.0.0.1:18789')).toBe('ws://127.0.0.1:18789')
    expect(validateGatewayUrl('wss://agent.example.com/openclaw/ws')).toBe('wss://agent.example.com/openclaw/ws')
    expect(() => validateGatewayUrl('ws://192.168.1.8:18789')).toThrow('WSS')
    expect(() => validateGatewayUrl('ws://[::1]:18789')).toThrow('WSS')
    expect(() => validateGatewayUrl('wss://agent.example.com/ws?token=bad')).toThrow('查询参数')
    expect(() => validateGatewayUrl('wss://user:secret@agent.example.com')).toThrow('凭证')
  })

  it('extracts a dashboard fragment token without retaining it in the Gateway URL', () => {
    expect(parseOpenClawConnectionInput(
      'ws://127.0.0.1:18789',
      'http://127.0.0.1:18789/#token=bootstrap-secret',
    )).toEqual({ gatewayUrl: 'ws://127.0.0.1:18789', bootstrapToken: 'bootstrap-secret' })
    expect(parseOpenClawConnectionInput('wss://agent.example.com/ws', 'raw-secret')).toEqual({
      gatewayUrl: 'wss://agent.example.com/ws',
      bootstrapToken: 'raw-secret',
    })
  })
})

describe('OpenClaw Gateway v4 client', () => {
  it('builds the preferred v3 device signature payload deterministically', () => {
    expect(buildDeviceAuthPayloadV3({
      deviceId: 'device-1',
      clientId: 'webchat-ui',
      clientMode: 'webchat',
      role: 'operator',
      scopes: ['operator.read', 'operator.write'],
      signedAtMs: 123,
      token: 'token-1',
      nonce: 'nonce-1',
      platform: 'MacIntel',
      deviceFamily: 'Browser',
    })).toBe('v3|device-1|webchat-ui|webchat|operator|operator.read,operator.write|123|token-1|nonce-1|macintel|browser')
  })

  it('rejects broader or incomplete negotiated scopes', () => {
    expect(validateNegotiatedScopes(['operator.write', 'operator.pairing', 'operator.read']))
      .toEqual(OPENCLAW_CURRENT_SCOPES)
    expect(validateNegotiatedScopes(
      ['operator.write', 'operator.read'],
      OPENCLAW_LEGACY_SCOPES,
    )).toEqual(OPENCLAW_LEGACY_SCOPES)
    expect(validateStoredOpenClawScopes(['operator.write', 'operator.read']))
      .toEqual(OPENCLAW_LEGACY_SCOPES)
    expect(validateStoredOpenClawScopes(['operator.pairing', 'operator.write', 'operator.read']))
      .toEqual(OPENCLAW_CURRENT_SCOPES)
    expect(() => validateNegotiatedScopes(['operator.read', 'operator.write'])).toThrow('权限')
    expect(() => validateNegotiatedScopes(['operator.admin', 'operator.read', 'operator.write'])).toThrow('权限')
    expect(() => validateNegotiatedScopes(['operator.read'])).toThrow('权限')
    expect(() => validateStoredOpenClawScopes(['operator.read', 'operator.write', 'operator.approvals'])).toThrow('权限')
  })

  it('answers a challenge, connects with a signed device and supports requests and events', async () => {
    const socket = new FakeSocket()
    const events: unknown[] = []
    const signer = vi.fn().mockResolvedValue('signed-value')
    const client = new OpenClawGatewayClient({
      url: 'ws://127.0.0.1:18789',
      bootstrapToken: 'bootstrap-secret',
      deviceIdentity: {
        deviceId: 'device-1',
        publicKey: 'public-key',
        privateKey: {} as CryptoKey,
      },
      platform: 'MacIntel',
      deviceFamily: 'Browser',
      socketFactory: () => socket,
      signer,
      now: () => 123,
      randomId: () => `request-${socket.sent.length + 1}`,
      onEvent: (event) => events.push(event),
    })

    const connecting = client.connect()
    socket.emit('open')
    socket.emit('message', { data: JSON.stringify({ type: 'event', event: 'connect.challenge', payload: { nonce: 'nonce-1' } }) })
    await vi.waitFor(() => expect(socket.sent).toHaveLength(1))

    const connectFrame = JSON.parse(socket.sent[0])
    expect(connectFrame).toMatchObject({
      type: 'req',
      method: 'connect',
      params: {
        minProtocol: 4,
        maxProtocol: 4,
        client: { id: 'webchat-ui', mode: 'webchat', platform: 'MacIntel', deviceFamily: 'Browser' },
        role: 'operator',
        scopes: ['operator.read', 'operator.write', 'operator.pairing'],
        auth: { token: 'bootstrap-secret' },
        device: { id: 'device-1', publicKey: 'public-key', signature: 'signed-value', signedAt: 123, nonce: 'nonce-1' },
      },
    })
    expect(signer).toHaveBeenCalledWith(expect.anything(), expect.stringContaining('|bootstrap-secret|nonce-1|macintel|browser'))

    socket.emit('message', { data: JSON.stringify({
      type: 'res', id: connectFrame.id, ok: true,
      payload: {
        protocol: 4,
        auth: {
          deviceToken: 'device-token',
          role: 'operator',
          scopes: ['operator.read', 'operator.write', 'operator.pairing'],
        },
        snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
      },
    }) })
    await expect(connecting).resolves.toMatchObject({ protocol: 4, auth: { deviceToken: 'device-token' } })

    const request = client.request('sessions.create', { agentId: 'main', label: 'Inteliscope' })
    const requestFrame = JSON.parse(socket.sent[1])
    socket.emit('message', { data: JSON.stringify({ type: 'res', id: requestFrame.id, ok: true, payload: { ok: true, key: 'session-1' } }) })
    await expect(request).resolves.toEqual({ ok: true, key: 'session-1' })

    socket.emit('message', { data: JSON.stringify({ type: 'event', event: 'chat', payload: { sessionKey: 'session-1', state: 'delta' } }) })
    expect(events).toHaveLength(1)
  })

  it('reconnects an existing legacy device with its exact stored scopes', async () => {
    const socket = new FakeSocket()
    const client = new OpenClawGatewayClient({
      url: 'ws://127.0.0.1:18789',
      deviceToken: 'legacy-device-token',
      deviceIdentity: {
        deviceId: 'legacy-device',
        publicKey: 'legacy-public-key',
        privateKey: {} as CryptoKey,
      },
      requestedScopes: OPENCLAW_LEGACY_SCOPES,
      socketFactory: () => socket,
      signer: vi.fn().mockResolvedValue('legacy-signature'),
      now: () => 456,
      randomId: () => 'legacy-request',
    })

    const connecting = client.connect()
    socket.emit('open')
    socket.emit('message', { data: JSON.stringify({
      type: 'event', event: 'connect.challenge', payload: { nonce: 'legacy-nonce' },
    }) })
    await vi.waitFor(() => expect(socket.sent).toHaveLength(1))

    const connectFrame = JSON.parse(socket.sent[0])
    expect(connectFrame.params).toMatchObject({
      scopes: ['operator.read', 'operator.write'],
      auth: { deviceToken: 'legacy-device-token' },
    })
    socket.emit('message', { data: JSON.stringify({
      type: 'res', id: connectFrame.id, ok: true,
      payload: {
        protocol: 4,
        auth: {
          deviceToken: 'legacy-device-token',
          role: 'operator',
          scopes: ['operator.read', 'operator.write'],
        },
      },
    }) })

    await expect(connecting).resolves.toMatchObject({
      auth: { scopes: ['operator.read', 'operator.write'] },
    })
  })
})
