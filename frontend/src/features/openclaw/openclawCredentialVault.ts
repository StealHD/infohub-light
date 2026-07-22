import {
  validateGatewayUrl,
  validateStoredOpenClawScopes,
  type OpenClawDeviceIdentity,
} from './openclawGateway'

export type StoredOpenClawCredential = {
  id: string
  userId: string
  gatewayHash: string
  identity: OpenClawDeviceIdentity
  deviceToken: string
  scopes: string[]
  sessionKey?: string
  updatedAt: number
}

export type OpenClawCredentialAdapter = {
  get: (key: string) => Promise<StoredOpenClawCredential | null>
  put: (value: StoredOpenClawCredential) => Promise<void>
  delete: (key: string) => Promise<void>
}

async function gatewayHash(gatewayUrl: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(validateGatewayUrl(gatewayUrl)),
  ))
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function credentialStorageKey(userId: string, gatewayUrl: string): Promise<string> {
  return `${userId}:${await gatewayHash(gatewayUrl)}`
}

const DATABASE_NAME = 'inteliscope-openclaw-v1'
const STORE_NAME = 'credentials'

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, 1)
    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('无法打开浏览器凭证存储。'))
  })
}

class IndexedDbCredentialAdapter implements OpenClawCredentialAdapter {
  async get(key: string): Promise<StoredOpenClawCredential | null> {
    const database = await openDatabase()
    try {
      return await new Promise((resolve, reject) => {
        const request = database.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(key)
        request.onsuccess = () => resolve((request.result as StoredOpenClawCredential | undefined) ?? null)
        request.onerror = () => reject(request.error ?? new Error('无法读取浏览器凭证。'))
      })
    } finally {
      database.close()
    }
  }

  async put(value: StoredOpenClawCredential): Promise<void> {
    const database = await openDatabase()
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = database.transaction(STORE_NAME, 'readwrite')
        transaction.objectStore(STORE_NAME).put(value)
        transaction.oncomplete = () => resolve()
        transaction.onerror = () => reject(transaction.error ?? new Error('无法保存浏览器凭证。'))
        transaction.onabort = () => reject(transaction.error ?? new Error('浏览器凭证保存已取消。'))
      })
    } finally {
      database.close()
    }
  }

  async delete(key: string): Promise<void> {
    const database = await openDatabase()
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = database.transaction(STORE_NAME, 'readwrite')
        transaction.objectStore(STORE_NAME).delete(key)
        transaction.oncomplete = () => resolve()
        transaction.onerror = () => reject(transaction.error ?? new Error('无法删除浏览器凭证。'))
        transaction.onabort = () => reject(transaction.error ?? new Error('浏览器凭证删除已取消。'))
      })
    } finally {
      database.close()
    }
  }
}

export class OpenClawCredentialVault {
  constructor(private adapter: OpenClawCredentialAdapter = new IndexedDbCredentialAdapter()) {}

  async load(userId: string, gatewayUrl: string): Promise<StoredOpenClawCredential | null> {
    const id = await credentialStorageKey(userId, gatewayUrl)
    const value = await this.adapter.get(id)
    if (!value || value.userId !== userId || value.gatewayHash !== id.slice(userId.length + 1)) return null
    try {
      validateStoredOpenClawScopes(value.scopes)
    } catch {
      return null
    }
    return value
  }

  async save(
    userId: string,
    gatewayUrl: string,
    value: {
      identity: OpenClawDeviceIdentity
      deviceToken: string
      scopes: string[]
      sessionKey?: string
    },
  ): Promise<StoredOpenClawCredential> {
    const scopes = validateStoredOpenClawScopes(value.scopes)
    if (!value.deviceToken.trim()) throw new Error('OpenClaw 没有返回可保存的设备凭证。')
    const id = await credentialStorageKey(userId, gatewayUrl)
    const stored: StoredOpenClawCredential = {
      id,
      userId,
      gatewayHash: id.slice(userId.length + 1),
      identity: value.identity,
      deviceToken: value.deviceToken,
      scopes,
      ...(value.sessionKey ? { sessionKey: value.sessionKey } : {}),
      updatedAt: Date.now(),
    }
    await this.adapter.put(stored)
    return stored
  }

  async updateSession(userId: string, gatewayUrl: string, sessionKey: string): Promise<void> {
    const stored = await this.load(userId, gatewayUrl)
    if (!stored) return
    await this.adapter.put({ ...stored, sessionKey, updatedAt: Date.now() })
  }

  async forget(userId: string, gatewayUrl: string): Promise<void> {
    await this.adapter.delete(await credentialStorageKey(userId, gatewayUrl))
  }
}
