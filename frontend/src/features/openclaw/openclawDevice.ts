import { OpenClawCredentialVault } from './openclawCredentialVault'
import {
  OPENCLAW_CURRENT_SCOPES,
  GatewayRequestError,
  OpenClawGatewayClient,
  validateGatewayUrl,
  validateNegotiatedScopes,
  type GatewayHello,
  type OpenClawGatewayClientOptions,
} from './openclawGateway'

export type OpenClawDeviceClient = {
  connect: () => Promise<GatewayHello>
  request: <T>(method: string, params: Record<string, unknown>) => Promise<T>
  close: () => void
}

export type ForgetOpenClawBrowserResult = 'removed' | 'already-removed' | 'not-paired'

export class OpenClawPairingUpgradeRequiredError extends Error {
  constructor() {
    super('此浏览器的旧配对没有设备管理权限。请到信息流对话面板粘贴 Gateway token 或 dashboard 地址重新授权后再试。')
    this.name = 'OpenClawPairingUpgradeRequiredError'
  }
}

function isUnknownDevice(error: unknown): boolean {
  return error instanceof GatewayRequestError
    && error.code.toUpperCase() === 'INVALID_REQUEST'
    && error.message.trim().toLowerCase() === 'unknown deviceid'
}

export async function forgetOpenClawBrowser(options: {
  userId: string
  gatewayUrl: string
  vault?: OpenClawCredentialVault
  clearTranscripts: (userId: string, gatewayUrl: string) => void
  clientFactory?: (options: OpenClawGatewayClientOptions) => OpenClawDeviceClient
}): Promise<ForgetOpenClawBrowserResult> {
  const gatewayUrl = validateGatewayUrl(options.gatewayUrl)
  const vault = options.vault ?? new OpenClawCredentialVault()
  const credential = await vault.load(options.userId, gatewayUrl)
  if (!credential) return 'not-paired'

  try {
    validateNegotiatedScopes(credential.scopes, OPENCLAW_CURRENT_SCOPES)
  } catch {
    throw new OpenClawPairingUpgradeRequiredError()
  }

  const factory = options.clientFactory
    ?? ((clientOptions: OpenClawGatewayClientOptions) => new OpenClawGatewayClient(clientOptions))
  const client = factory({
    url: gatewayUrl,
    deviceToken: credential.deviceToken,
    deviceIdentity: credential.identity,
    requestedScopes: OPENCLAW_CURRENT_SCOPES,
    platform: navigator.platform || 'web',
    deviceFamily: 'browser',
  })
  let result: ForgetOpenClawBrowserResult = 'removed'
  try {
    await client.connect()
    try {
      await client.request('device.pair.remove', { deviceId: credential.identity.deviceId })
    } catch (error) {
      if (!isUnknownDevice(error)) throw error
      result = 'already-removed'
    }
  } finally {
    client.close()
  }

  options.clearTranscripts(options.userId, gatewayUrl)
  await vault.forget(options.userId, gatewayUrl)
  return result
}
