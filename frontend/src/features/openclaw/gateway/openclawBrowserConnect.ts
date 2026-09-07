import { signDevicePayload } from './openclawDeviceIdentity'
import { buildDeviceAuthPayloadV3 } from './openclawGatewayProtocol'
import type { OpenClawGatewayClientOptions } from './openclawGatewayTypes'

const CLIENT_ID = 'webchat-ui'
const CLIENT_MODE = 'webchat'
const CLIENT_VERSION = '1.0.0'
const ROLE = 'operator'

export async function browserConnectParams(options: OpenClawGatewayClientOptions, nonce: string, scopes: string[]): Promise<Record<string, unknown>> {
  const signedAtMs = (options.now ?? Date.now)()
  const signatureToken = options.bootstrapToken || options.deviceToken || ''
  const payload = buildDeviceAuthPayloadV3({
    deviceId: options.deviceIdentity.deviceId,
    clientId: CLIENT_ID,
    clientMode: CLIENT_MODE,
    role: ROLE,
    scopes,
    signedAtMs,
    token: signatureToken,
    nonce,
    platform: options.platform,
    deviceFamily: options.deviceFamily,
  })
  const signature = await (options.signer ?? signDevicePayload)(
    options.deviceIdentity.privateKey,
    payload,
  )
  const auth = options.bootstrapToken
    ? { token: options.bootstrapToken }
    : options.deviceToken
      ? { deviceToken: options.deviceToken }
      : undefined
  return {
    minProtocol: 4,
    maxProtocol: 4,
    client: {
      id: CLIENT_ID,
      version: CLIENT_VERSION,
      platform: options.platform || navigator.platform || 'web',
      deviceFamily: options.deviceFamily || 'browser',
      mode: CLIENT_MODE,
    },
    caps: ['tool-events'],
    auth,
    role: ROLE,
    scopes,
    device: {
      id: options.deviceIdentity.deviceId,
      publicKey: options.deviceIdentity.publicKey,
      signature,
      signedAt: signedAtMs,
      nonce,
    },
    userAgent: navigator.userAgent,
    locale: navigator.language,
  }
}
