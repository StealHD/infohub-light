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
  snapshot?: {
    sessionDefaults?: { defaultAgentId?: string }
    features?: { methods?: unknown[] }
    methods?: unknown[]
  }
  [key: string]: unknown
}

export type OpenClawGatewayClientOptions = {
  url: string
  bootstrapToken?: string
  deviceToken?: string
  deviceIdentity: OpenClawDeviceIdentity
  requestedScopes?: readonly string[]
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
