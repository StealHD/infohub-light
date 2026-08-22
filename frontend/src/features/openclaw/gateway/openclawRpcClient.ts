import { signDevicePayload } from './openclawDeviceIdentity'
import {
  OPENCLAW_CURRENT_SCOPES,
  GatewayRequestError,
  buildDeviceAuthPayloadV3,
  type GatewayErrorShape,
  validateNegotiatedScopes,
  validateStoredOpenClawScopes,
} from './openclawGatewayProtocol'
import type {
  GatewayEvent,
  GatewayHello,
  GatewaySocket,
  OpenClawGatewayClientOptions,
} from './openclawGatewayTypes'
import { validateGatewayUrl } from './openclawGatewayUrl'

const CLIENT_ID = 'webchat-ui'
const CLIENT_MODE = 'webchat'
const CLIENT_VERSION = '1.0.0'
const ROLE = 'operator'
const OPEN = 1

type PendingRequest = {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: number
}

export class OpenClawGatewayClient {
  private options: OpenClawGatewayClientOptions
  private socket: GatewaySocket | null = null
  private pending = new Map<string, PendingRequest>()
  private connectSent = false
  private connectTimer: number | null = null
  private closed = false
  private hello: GatewayHello | null = null

  constructor(options: OpenClawGatewayClientOptions) {
    this.options = {
      ...options,
      url: validateGatewayUrl(options.url),
      requestedScopes: validateStoredOpenClawScopes(
        options.requestedScopes ?? OPENCLAW_CURRENT_SCOPES,
      ),
    }
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
      const scopes = [...(this.options.requestedScopes ?? OPENCLAW_CURRENT_SCOPES)]
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
      validateNegotiatedScopes(hello.auth.scopes ?? [], scopes)
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
