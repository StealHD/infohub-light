import type { GatewayHello } from './openclawGatewayTypes'

export const OPENCLAW_LEGACY_SCOPES = ['operator.read', 'operator.write'] as const
export const OPENCLAW_CURRENT_SCOPES = [
  'operator.read',
  'operator.write',
  'operator.pairing',
] as const
export const OPENCLAW_ADMIN_SCOPES = ['operator.admin'] as const

export type GatewayErrorShape = {
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

export function gatewaySupportsMethod(hello: GatewayHello | null | undefined, method: string): boolean {
  if (!hello || !method) return false
  const features = (hello as Record<string, unknown>).features
  if (!features || typeof features !== 'object' || Array.isArray(features)) return false
  const methods = (features as Record<string, unknown>).methods
  return Array.isArray(methods) && methods.some((candidate) => candidate === method)
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

function hasExactScopes(scopes: readonly string[], expectedScopes: readonly string[]): boolean {
  if (scopes.length !== expectedScopes.length || new Set(scopes).size !== scopes.length) return false
  const expected = new Set(expectedScopes)
  return scopes.every((scope) => expected.has(scope))
}

export function validateNegotiatedScopes(
  scopes: readonly string[],
  expectedScopes: readonly string[] = OPENCLAW_CURRENT_SCOPES,
): string[] {
  if (!hasExactScopes(scopes, expectedScopes)) {
    throw new Error('OpenClaw 返回了超出或缺少预期的浏览器权限。')
  }
  return [...expectedScopes]
}

export function validateStoredOpenClawScopes(scopes: readonly string[]): string[] {
  if (hasExactScopes(scopes, OPENCLAW_CURRENT_SCOPES)) return [...OPENCLAW_CURRENT_SCOPES]
  if (hasExactScopes(scopes, OPENCLAW_LEGACY_SCOPES)) return [...OPENCLAW_LEGACY_SCOPES]
  throw new Error('OpenClaw 返回了超出或缺少预期的浏览器权限。')
}

export function validateAdminOpenClawScopes(scopes: readonly string[]): string[] {
  if (hasExactScopes(scopes, OPENCLAW_ADMIN_SCOPES)) return [...OPENCLAW_ADMIN_SCOPES]
  throw new Error('OpenClaw 管理连接必须且只能请求 operator.admin。')
}
