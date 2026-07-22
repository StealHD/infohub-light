import { describe, expect, it } from 'vitest'

import {
  OpenClawCredentialVault,
  credentialStorageKey,
  type OpenClawCredentialAdapter,
  type StoredOpenClawCredential,
} from './openclawCredentialVault'

class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => { this.values.set(value.id, value) }
  delete = async (key: string) => { this.values.delete(key) }
}

describe('OpenClaw credential vault', () => {
  it('keys credentials by Inteliscope user and a Gateway URL hash', async () => {
    const first = await credentialStorageKey('user-a', 'ws://127.0.0.1:18789')
    const secondUser = await credentialStorageKey('user-b', 'ws://127.0.0.1:18789')
    const secondGateway = await credentialStorageKey('user-a', 'wss://agent.example.com')

    expect(first).toMatch(/^user-a:[a-f0-9]{64}$/)
    expect(first).not.toContain('127.0.0.1')
    expect(first).not.toBe(secondUser)
    expect(first).not.toBe(secondGateway)
  })

  it('isolates, updates and forgets scoped device credentials', async () => {
    const adapter = new MemoryAdapter()
    const vault = new OpenClawCredentialVault(adapter)
    const identity = { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey }

    await vault.save('user-a', 'ws://127.0.0.1:18789', {
      identity,
      deviceToken: 'device-token',
      scopes: ['operator.read', 'operator.write'],
      sessionKey: 'session-1',
    })

    await expect(vault.load('user-a', 'ws://127.0.0.1:18789')).resolves.toMatchObject({
      userId: 'user-a',
      identity,
      deviceToken: 'device-token',
      sessionKey: 'session-1',
    })
    await expect(vault.load('user-b', 'ws://127.0.0.1:18789')).resolves.toBeNull()

    await vault.updateSession('user-a', 'ws://127.0.0.1:18789', 'session-2')
    await expect(vault.load('user-a', 'ws://127.0.0.1:18789')).resolves.toMatchObject({ sessionKey: 'session-2' })

    await vault.forget('user-a', 'ws://127.0.0.1:18789')
    await expect(vault.load('user-a', 'ws://127.0.0.1:18789')).resolves.toBeNull()
  })

  it('refuses to persist broader device scopes', async () => {
    const vault = new OpenClawCredentialVault(new MemoryAdapter())

    await expect(vault.save('user-a', 'ws://127.0.0.1:18789', {
      identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
      deviceToken: 'device-token',
      scopes: ['operator.read', 'operator.write', 'operator.admin'],
    })).rejects.toThrow('权限')
  })

  it('persists the current pairing profile while retaining exact legacy credentials', async () => {
    const adapter = new MemoryAdapter()
    const vault = new OpenClawCredentialVault(adapter)
    const identity = { deviceId: 'device-current', publicKey: 'public-current', privateKey: {} as CryptoKey }

    await expect(vault.save('user-current', 'ws://127.0.0.1:18789', {
      identity,
      deviceToken: 'current-token',
      scopes: ['operator.read', 'operator.write', 'operator.pairing'],
      sessionKey: 'session-current',
    })).resolves.toMatchObject({
      scopes: ['operator.read', 'operator.write', 'operator.pairing'],
    })

    await expect(vault.load('user-current', 'ws://127.0.0.1:18789')).resolves.toMatchObject({
      deviceToken: 'current-token',
      scopes: ['operator.read', 'operator.write', 'operator.pairing'],
    })

    const legacy = new OpenClawCredentialVault(new MemoryAdapter())
    await legacy.save('user-legacy', 'ws://127.0.0.1:18789', {
      identity: { ...identity, deviceId: 'device-legacy' },
      deviceToken: 'legacy-token',
      scopes: ['operator.read', 'operator.write'],
    })
    await expect(legacy.load('user-legacy', 'ws://127.0.0.1:18789')).resolves.toMatchObject({
      scopes: ['operator.read', 'operator.write'],
    })
  })
})
