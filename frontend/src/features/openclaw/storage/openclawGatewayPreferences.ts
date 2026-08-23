import { validateGatewayUrl } from '../openclawGateway'

export const OPENCLAW_GATEWAY_URL_KEY_PREFIX = 'inteliscope.openclaw.gateway.v1:'

export function readSavedGatewayUrl(userId: string, fallback: string): string {
  try {
    return validateGatewayUrl(window.localStorage.getItem(`${OPENCLAW_GATEWAY_URL_KEY_PREFIX}${userId}`) || fallback)
  } catch {
    return validateGatewayUrl(fallback)
  }
}

export function saveGatewayUrl(userId: string, value: string): void {
  try {
    window.localStorage.setItem(`${OPENCLAW_GATEWAY_URL_KEY_PREFIX}${userId}`, value)
  } catch {
    // URL persistence is best-effort.
  }
}
