const CLIENT_ID = 'webchat-ui'
const CLIENT_MODE = 'webchat'
const CLIENT_VERSION = '1.0.0'
const ROLE = 'operator'
const REQUESTED_SCOPES = ['operator.read', 'operator.write'] as const
const OPEN = 1

export type GatewaySocket = {
  readyState: number
  addEventListener: (type: string, listener: (event: unknown) => void) => void
  send: (value: string) => void
  close: (code?: number, reason?: string) => void
}

export type OpenClawDeviceIdentity = {
  deviceId: string
  publicKey: string
  privateKey: CryptoKey
}

export type GatewayEvent = { type: 'event'; event: string; payload?: unknown; seq?: number }

export type GatewayHello = {
  protocol?: number
  auth?: { deviceToken?: string; role?: string; scopes?: string[] }
  snapshot?: { sessionDefaults?: { defaultAgentId?: string } }
  [key: string]: unknown
}

type GatewayErrorShape = {
  code?: string
  message?: string
  details?: unknown
  retryable?: boolean
  retryAfterMs?: number
}

export class GatewayRequestError extends Error {
  code: string
  details?: unknown
  retryable: boolean
  retryAfterMs?: number

  constructor(error: GatewayErrorShape) {
    super(error.message || 'OpenClaw Gateway 请求失败')
    this.name = 'GatewayRequestError'
    this.code = error.code || 'UNAVAILABLE'
    this.details = error.details
    this.retryable = error.retryable === true
    this.retryAfterMs = error.retryAfterMs
  }
}

function isLoopback(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '')
  return host === 'localhost' || host === '127.0.0.1'
}

function canonicalSocketUrl(parsed: URL): string {
  const path = parsed.pathname === '/' ? '' : parsed.pathname
  return `${parsed.protocol}//${parsed.host}${path}`
}

export function validateGatewayUrl(value: string): string {
  const input = value.trim()
  let parsed: URL
  try {
    parsed = new URL(input)
  } catch {
    throw new Error('请输入有效的 OpenClaw Gateway URL。')
  }
  if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') {
    throw new Error('Gateway URL 必须使用 ws:// 或 wss://。')
  }
  if (parsed.username || parsed.password) {
    throw new Error('Gateway URL 不能包含用户名、密码或其他凭证。')
  }
  if (parsed.search) throw new Error('Gateway URL 不能包含查询参数。')
  if (parsed.hash) throw new Error('Gateway URL 不能包含 fragment。')
  if (parsed.protocol === 'ws:' && !isLoopback(parsed.hostname)) {
    throw new Error('非本机 OpenClaw Gateway 必须使用 WSS。')
  }
  return canonicalSocketUrl(parsed)
}

export function parseOpenClawConnectionInput(gatewayUrl: string, authInput: string): {
  gatewayUrl: string
  bootstrapToken: string
} {
  const input = authInput.trim()
  if (!input) throw new Error('请输入 OpenClaw Gateway token。')
  if (/^https?:\/\//i.test(input)) {
    const dashboard = new URL(input)
    if (dashboard.search) throw new Error('Dashboard 地址不能包含查询参数。')
    const fragment = new URLSearchParams(dashboard.hash.replace(/^#/, ''))
    const bootstrapToken = fragment.get('token')?.trim() || ''
    if (!bootstrapToken) throw new Error('Dashboard 地址中没有找到 token。')
    dashboard.protocol = dashboard.protocol === 'https:' ? 'wss:' : 'ws:'
    dashboard.hash = ''
    return { gatewayUrl: validateGatewayUrl(dashboard.toString()), bootstrapToken }
  }
  return { gatewayUrl: validateGatewayUrl(gatewayUrl), bootstrapToken: input }
}

function normalizeDeviceMetadata(value?: string): string {
  return (value || '').trim().toLowerCase()
}

export function buildDeviceAuthPayloadV3(params: {
  deviceId: string
  clientId: string
  clientMode: string
  role: string
  scopes: string[]
  signedAtMs: number
  token?: string | null
  nonce: string
  platform?: string
  deviceFamily?: string
}): string {
  return [
    'v3',
    params.deviceId,
    params.clientId,
    params.clientMode,
    params.role,
    params.scopes.join(','),
    String(params.signedAtMs),
    params.token ?? '',
    params.nonce,
    normalizeDeviceMetadata(params.platform),
    normalizeDeviceMetadata(params.deviceFamily),
  ].join('|')
}

export function validateNegotiatedScopes(scopes: string[]): string[] {
  const unique = Array.from(new Set(scopes)).sort()
  if (
    unique.length !== REQUESTED_SCOPES.length
    || unique.some((scope, index) => scope !== REQUESTED_SCOPES[index])
  ) {
    throw new Error('OpenClaw 返回了超出或缺少预期的浏览器权限。')
  }
  return [...REQUESTED_SCOPES]
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function generateDeviceIdentity(): Promise<OpenClawDeviceIdentity> {
  const generated = await crypto.subtle.generateKey(
    { name: 'Ed25519' },
    true,
    ['sign', 'verify'],
  ) as CryptoKeyPair
  const publicBytes = new Uint8Array(await crypto.subtle.exportKey('raw', generated.publicKey))
  const privateBytes = new Uint8Array(await crypto.subtle.exportKey('pkcs8', generated.privateKey))
  const privateKey = await crypto.subtle.importKey(
    'pkcs8',
    privateBytes,
    { name: 'Ed25519' },
    false,
    ['sign'],
  )
  privateBytes.fill(0)
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', publicBytes))
  return { deviceId: toHex(digest), publicKey: toBase64Url(publicBytes), privateKey }
}

export async function signDevicePayload(privateKey: CryptoKey, payload: string): Promise<string> {
  const signature = await crypto.subtle.sign(
    { name: 'Ed25519' },
    privateKey,
    new TextEncoder().encode(payload),
  )
  return toBase64Url(new Uint8Array(signature))
}

type ClientOptions = {
  url: string
  bootstrapToken?: string
  deviceToken?: string
  deviceIdentity: OpenClawDeviceIdentity
  platform?: string
  deviceFamily?: string
  socketFactory?: (url: string) => GatewaySocket
  signer?: (privateKey: CryptoKey, payload: string) => Promise<string>
  now?: () => number
  randomId?: () => string
  onHello?: (hello: GatewayHello) => void
  onEvent?: (event: GatewayEvent) => void
  onClose?: (event: { code?: number; reason?: string }) => void
}

type PendingRequest = {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: number
}

export class OpenClawGatewayClient {
  private options: ClientOptions
  private socket: GatewaySocket | null = null
  private pending = new Map<string, PendingRequest>()
  private connectSent = false
  private connectTimer: number | null = null
  private closed = false
  private hello: GatewayHello | null = null

  constructor(options: ClientOptions) {
    this.options = { ...options, url: validateGatewayUrl(options.url) }
  }

  connect(): Promise<GatewayHello> {
    if (this.socket) return Promise.reject(new Error('Gateway 已开始连接。'))
    this.closed = false
    const socketFactory = this.options.socketFactory
      ?? ((url: string) => new WebSocket(url) as unknown as GatewaySocket)
    let socket: GatewaySocket
    try {
      socket = socketFactory(this.options.url)
    } catch (error) {
      return Promise.reject(error instanceof Error ? error : new Error(String(error)))
    }
    this.socket = socket
    const connected = new Promise<GatewayHello>((resolve, reject) => {
      socket.addEventListener('open', () => {
        this.connectTimer = window.setTimeout(() => {
          const error = new Error('OpenClaw Gateway 未在 15 秒内发送连接 challenge。')
          reject(error)
          this.socket?.close(4008, 'challenge timeout')
        }, 15_000)
      })
      socket.addEventListener('message', (event) => {
        const data = (event as { data?: unknown }).data
        this.handleMessage(typeof data === 'string' ? data : String(data ?? ''), resolve, reject)
      })
      socket.addEventListener('close', (event) => {
        this.clearConnectTimer()
        this.rejectPending(new Error('OpenClaw Gateway 连接已关闭。'))
        if (!this.hello) reject(new Error('OpenClaw Gateway 连接已关闭。'))
        if (!this.closed) this.options.onClose?.(event as { code?: number; reason?: string })
      })
      socket.addEventListener('error', () => undefined)
    })
    return connected
  }

  request<T>(method: string, params: Record<string, unknown>): Promise<T> {
    return this.requestOnSocket(method, params) as Promise<T>
  }

  close(): void {
    this.closed = true
    this.clearConnectTimer()
    this.rejectPending(new Error('OpenClaw Gateway 客户端已关闭。'))
    this.socket?.close(1000, 'client closed')
    this.socket = null
    this.hello = null
  }

  private async sendConnect(
    nonce: string,
    resolve: (hello: GatewayHello) => void,
    reject: (error: Error) => void,
  ): Promise<void> {
    if (this.connectSent || !this.socket || this.socket.readyState !== OPEN) return
    this.connectSent = true
    this.clearConnectTimer()
    try {
      const signedAtMs = (this.options.now ?? Date.now)()
      const scopes = [...REQUESTED_SCOPES]
      const signatureToken = this.options.bootstrapToken || this.options.deviceToken || ''
      const payload = buildDeviceAuthPayloadV3({
        deviceId: this.options.deviceIdentity.deviceId,
        clientId: CLIENT_ID,
        clientMode: CLIENT_MODE,
        role: ROLE,
        scopes,
        signedAtMs,
        token: signatureToken,
        nonce,
        platform: this.options.platform,
        deviceFamily: this.options.deviceFamily,
      })
      const signature = await (this.options.signer ?? signDevicePayload)(
        this.options.deviceIdentity.privateKey,
        payload,
      )
      const auth = this.options.bootstrapToken
        ? { token: this.options.bootstrapToken }
        : this.options.deviceToken
          ? { deviceToken: this.options.deviceToken }
          : undefined
      const hello = await this.requestOnSocket('connect', {
        minProtocol: 4,
        maxProtocol: 4,
        client: {
          id: CLIENT_ID,
          version: CLIENT_VERSION,
          platform: this.options.platform || navigator.platform || 'web',
          deviceFamily: this.options.deviceFamily || 'browser',
          mode: CLIENT_MODE,
        },
        caps: ['tool-events'],
        auth,
        role: ROLE,
        scopes,
        device: {
          id: this.options.deviceIdentity.deviceId,
          publicKey: this.options.deviceIdentity.publicKey,
          signature,
          signedAt: signedAtMs,
          nonce,
        },
        userAgent: navigator.userAgent,
        locale: navigator.language,
      }) as GatewayHello
      if (hello.protocol !== undefined && hello.protocol !== 4) {
        throw new Error('OpenClaw Gateway 协议版本不兼容。')
      }
      if (hello.auth?.role !== ROLE) throw new Error('OpenClaw 返回了非 operator 的浏览器角色。')
      validateNegotiatedScopes(hello.auth.scopes ?? [])
      if (hello.auth.deviceToken) {
        this.options = { ...this.options, bootstrapToken: undefined, deviceToken: hello.auth.deviceToken }
      }
      this.hello = hello
      this.options.onHello?.(hello)
      resolve(hello)
    } catch (error) {
      const failure = error instanceof Error ? error : new Error(String(error))
      reject(failure)
      this.socket?.close(4008, 'connect failed')
    }
  }

  private requestOnSocket(method: string, params: Record<string, unknown>): Promise<unknown> {
    if (!this.socket || this.socket.readyState !== OPEN) {
      return Promise.reject(new Error('OpenClaw Gateway 尚未连接。'))
    }
    const id = (this.options.randomId ?? (() => crypto.randomUUID()))()
    const promise = new Promise<unknown>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`OpenClaw Gateway 请求超时：${method}`))
      }, 30_000)
      this.pending.set(id, { resolve, reject, timer })
    })
    this.socket.send(JSON.stringify({ type: 'req', id, method, params }))
    return promise
  }

  private handleMessage(
    raw: string,
    resolveConnect: (hello: GatewayHello) => void,
    rejectConnect: (error: Error) => void,
  ): void {
    let frame: unknown
    try { frame = JSON.parse(raw) } catch { return }
    if (!frame || typeof frame !== 'object') return
    const value = frame as Record<string, unknown>
    if (value.type === 'event' && typeof value.event === 'string') {
      const event = value as GatewayEvent
      if (event.event === 'connect.challenge') {
        const nonce = (event.payload as { nonce?: unknown } | undefined)?.nonce
        if (typeof nonce === 'string') void this.sendConnect(nonce, resolveConnect, rejectConnect)
        return
      }
      this.options.onEvent?.(event)
      return
    }
    if (value.type !== 'res' || typeof value.id !== 'string') return
    const pending = this.pending.get(value.id)
    if (!pending) return
    this.pending.delete(value.id)
    window.clearTimeout(pending.timer)
    if (value.ok === true) pending.resolve(value.payload)
    else pending.reject(new GatewayRequestError((value.error as GatewayErrorShape | undefined) ?? {}))
  }

  private clearConnectTimer(): void {
    if (this.connectTimer !== null) window.clearTimeout(this.connectTimer)
    this.connectTimer = null
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) {
      window.clearTimeout(pending.timer)
      pending.reject(error)
    }
    this.pending.clear()
  }
}
