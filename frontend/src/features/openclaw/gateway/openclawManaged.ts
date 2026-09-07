export const MANAGED_GATEWAY_PATH = '/api/me/openclaw/socket'

export function managedGatewayUrl(): string {
  return window.location.origin.replace('http', 'ws') + MANAGED_GATEWAY_PATH
}

export function isManagedGateway(url: string): boolean {
  return url === MANAGED_GATEWAY_PATH || url === managedGatewayUrl()
}
