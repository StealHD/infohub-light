import { describe, expect, it, vi } from 'vitest'

import {
  OpenClawCredentialVault,
  type OpenClawCredentialAdapter,
  type StoredOpenClawCredential,
} from './openclawCredentialVault'
import {
  OpenClawPairingUpgradeRequiredError,
  forgetOpenClawBrowser,
} from './openclawDevice'
import {
  OPENCLAW_CURRENT_SCOPES,
  OPENCLAW_LEGACY_SCOPES,
  GatewayRequestError,
  type GatewayHello,
} from './openclawGateway'

class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  events: string[] = []
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => { this.values.set(value.id, value) }
  delete = async (key: string) => {
    this.events.push('delete')
    this.values.delete(key)
  }
}

const gatewayUrl = 'ws://127.0.0.1:18789'
const identity = {
  deviceId: 'device-current',
  publicKey: 'public-current',
  privateKey: {} as CryptoKey,
}

async function pairedVault(scopes: readonly string[]) {
  const adapter = new MemoryAdapter()
  const vault = new OpenClawCredentialVault(adapter)
  await vault.save('user-a', gatewayUrl, {
    identity,
    deviceToken: 'device-token',
    scopes: [...scopes],
    sessionKey: 'session-a',
  })
  return { adapter, vault }
}

describe('OpenClaw paired browser removal', () => {
  it('removes the server pairing before clearing transcripts and IndexedDB', async () => {
    const { adapter, vault } = await pairedVault(OPENCLAW_CURRENT_SCOPES)
    const events: string[] = []
    const request = vi.fn(async (method: string) => {
      events.push(method)
      return { deviceId: identity.deviceId }
    })
    const close = vi.fn(() => { events.push('close') })
    const clientFactory = vi.fn((options) => ({
      options,
      connect: vi.fn(async (): Promise<GatewayHello> => {
        events.push('connect')
        return { auth: { deviceToken: 'device-token', scopes: [...OPENCLAW_CURRENT_SCOPES] } }
      }),
      request,
      close,
    }))
    const clearTranscripts = vi.fn(() => {
      events.push('clear')
      adapter.events.push('clear')
    })

    await expect(forgetOpenClawBrowser({
      userId: 'user-a',
      gatewayUrl,
      vault,
      clearTranscripts,
      clientFactory: clientFactory as never,
    })).resolves.toBe('removed')

    expect(clientFactory).toHaveBeenCalledWith(expect.objectContaining({
      url: gatewayUrl,
      deviceToken: 'device-token',
      deviceIdentity: identity,
      requestedScopes: OPENCLAW_CURRENT_SCOPES,
    }))
    expect(request).toHaveBeenCalledWith('device.pair.remove', { deviceId: identity.deviceId })
    expect(request.mock.calls.some(([method]) => method === 'device.token.revoke')).toBe(false)
    expect(events).toEqual(['connect', 'device.pair.remove', 'close', 'clear'])
    expect(adapter.events).toEqual(['clear', 'delete'])
    await expect(vault.load('user-a', gatewayUrl)).resolves.toBeNull()
  })

  it('treats an already-missing server device as idempotent success', async () => {
    const { vault } = await pairedVault(OPENCLAW_CURRENT_SCOPES)
    const clearTranscripts = vi.fn()
    const close = vi.fn()
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({})),
      request: vi.fn(async () => {
        throw new GatewayRequestError({ code: 'INVALID_REQUEST', message: 'unknown deviceId' })
      }),
      close,
    }))

    await expect(forgetOpenClawBrowser({
      userId: 'user-a', gatewayUrl, vault, clearTranscripts,
      clientFactory: clientFactory as never,
    })).resolves.toBe('already-removed')
    expect(clearTranscripts).toHaveBeenCalledWith('user-a', gatewayUrl)
    expect(close).toHaveBeenCalledOnce()
    await expect(vault.load('user-a', gatewayUrl)).resolves.toBeNull()
  })

  it('retains every local recovery artifact when server removal fails', async () => {
    const { vault } = await pairedVault(OPENCLAW_CURRENT_SCOPES)
    const clearTranscripts = vi.fn()
    const close = vi.fn()
    const failure = new GatewayRequestError({
      code: 'PERMISSION_DENIED',
      message: 'missing scope: operator.pairing',
    })
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({})),
      request: vi.fn(async () => { throw failure }),
      close,
    }))

    await expect(forgetOpenClawBrowser({
      userId: 'user-a', gatewayUrl, vault, clearTranscripts,
      clientFactory: clientFactory as never,
    })).rejects.toBe(failure)
    expect(clearTranscripts).not.toHaveBeenCalled()
    expect(close).toHaveBeenCalledOnce()
    await expect(vault.load('user-a', gatewayUrl)).resolves.toMatchObject({
      deviceToken: 'device-token',
      sessionKey: 'session-a',
    })
  })

  it('requests a scope upgrade for a legacy credential and preserves local recovery state', async () => {
    const { vault } = await pairedVault(OPENCLAW_LEGACY_SCOPES)
    const clearTranscripts = vi.fn()
    const close = vi.fn()
    const request = vi.fn()
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => {
        throw new GatewayRequestError({
          code: 'NOT_PAIRED',
          message: 'scope upgrade pending approval',
          details: {
            code: 'PAIRING_REQUIRED',
            reason: 'scope-upgrade',
            requestId: 'request-upgrade-1',
            remediationHint: 'Review and approve the device pairing request.',
          },
        })
      }),
      request,
      close,
    }))

    await expect(forgetOpenClawBrowser({
      userId: 'user-a', gatewayUrl, vault, clearTranscripts,
      clientFactory: clientFactory as never,
    })).rejects.toMatchObject({
      name: 'OpenClawPairingUpgradeRequiredError',
      requestId: 'request-upgrade-1',
      message: expect.stringContaining('openclaw devices approve request-upgrade-1'),
    } satisfies Partial<OpenClawPairingUpgradeRequiredError>)
    expect(clientFactory).toHaveBeenCalledWith(expect.objectContaining({
      deviceToken: 'device-token',
      deviceIdentity: identity,
      requestedScopes: OPENCLAW_CURRENT_SCOPES,
    }))
    expect(request).not.toHaveBeenCalled()
    expect(close).toHaveBeenCalledOnce()
    expect(clearTranscripts).not.toHaveBeenCalled()
    await expect(vault.load('user-a', gatewayUrl)).resolves.toMatchObject({
      scopes: OPENCLAW_LEGACY_SCOPES,
      deviceToken: 'device-token',
    })
  })

  it('removes a legacy pairing when its requested scope upgrade has been approved', async () => {
    const { vault } = await pairedVault(OPENCLAW_LEGACY_SCOPES)
    const clearTranscripts = vi.fn()
    const request = vi.fn(async () => ({ deviceId: identity.deviceId }))
    const close = vi.fn()
    const clientFactory = vi.fn(() => ({
      connect: vi.fn(async (): Promise<GatewayHello> => ({
        auth: { deviceToken: 'upgraded-device-token', scopes: [...OPENCLAW_CURRENT_SCOPES] },
      })),
      request,
      close,
    }))

    await expect(forgetOpenClawBrowser({
      userId: 'user-a', gatewayUrl, vault, clearTranscripts,
      clientFactory: clientFactory as never,
    })).resolves.toBe('removed')

    expect(request).toHaveBeenCalledWith('device.pair.remove', { deviceId: identity.deviceId })
    expect(clearTranscripts).toHaveBeenCalledWith('user-a', gatewayUrl)
    expect(close).toHaveBeenCalledOnce()
    await expect(vault.load('user-a', gatewayUrl)).resolves.toBeNull()
  })
})
