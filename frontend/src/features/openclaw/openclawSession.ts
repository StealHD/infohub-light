import { GatewayRequestError } from './openclawGateway'

const LABEL_PREFIX = 'Inteliscope · '
const RANDOM_HEX_LENGTH = 16
const MAX_LABEL_LENGTH = 512

export function createOpenClawSessionLabel(
  siteHost: string,
  randomId: string = crypto.randomUUID(),
): string {
  const randomHex = randomId.replaceAll('-', '').toLowerCase()
  if (!/^[0-9a-f]{16,}$/u.test(randomHex)) {
    throw new Error('OpenClaw 会话随机标识无效。')
  }
  const suffix = ` · ${randomHex.slice(0, RANDOM_HEX_LENGTH)}`
  const normalizedHost = siteHost.trim().toLowerCase() || 'browser'
  const boundedHost = normalizedHost.slice(0, MAX_LABEL_LENGTH - LABEL_PREFIX.length - suffix.length)
  return `${LABEL_PREFIX}${boundedHost}${suffix}`
}

export function isOpenClawSessionLabelConflict(error: unknown): boolean {
  return error instanceof GatewayRequestError
    && error.code.toUpperCase() === 'INVALID_REQUEST'
    && error.message.toLowerCase().includes('label already in use')
}
