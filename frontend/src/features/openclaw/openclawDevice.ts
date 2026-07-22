import { OpenClawCredentialVault } from './openclawCredentialVault'
import {
  OPENCLAW_CURRENT_SCOPES,
  GatewayRequestError,
  OpenClawGatewayClient,
  validateGatewayUrl,
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
  requestId?: string

  constructor(requestId?: string) {
    const command = requestId
      ? `openclaw devices approve ${requestId}`
      : 'openclaw devices list，再运行 openclaw devices approve <requestId>'
    super(`OpenClaw 已创建设备权限升级请求。请在 Gateway 主机终端运行 ${command}；批准后回到这里再次确认删除。`)
    this.name = 'OpenClawPairingUpgradeRequiredError'
    this.requestId = requestId
  }
}

type PairingUpgradeRequest = { requestId?: string }

function stringField(record: Record<string, unknown> | null, key: string): string {
  const value = record?.[key]
  return typeof value === 'string' ? value.trim() : ''
}

function safeRequestId(value: string): string | undefined {
  return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value) ? value : undefined
}

function pairingUpgradeRequest(error: unknown): PairingUpgradeRequest | null {
  if (!(error instanceof GatewayRequestError)) return null
  const details = error.details && typeof error.details === 'object' && !Array.isArray(error.details)
    ? error.details as Record<string, unknown>
    : null
  const detailCode = stringField(details, 'code').toUpperCase()
  const reason = stringField(details, 'reason').toLowerCase()
  const message = error.message.trim().toLowerCase()
  const isPairingRequired = detailCode === 'PAIRING_REQUIRED'
    || message.includes('pairing required')
  const isScopeUpgrade = reason === 'scope-upgrade'
    || message.includes('scope upgrade pending approval')
  if (!isPairingRequired || !isScopeUpgrade) return null

  const requestIdFromMessage = error.message.match(/\(requestId:\s*([^\s)]+)\)/i)?.[1] ?? ''
  return {
    requestId: safeRequestId(stringField(details, 'requestId'))
      ?? safeRequestId(requestIdFromMessage),
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
    try {
      await client.connect()
    } catch (error) {
      const upgrade = pairingUpgradeRequest(error)
      if (upgrade) throw new OpenClawPairingUpgradeRequiredError(upgrade.requestId)
      throw error
    }
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
