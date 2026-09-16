import type { OpenClawClientPort } from '../openclawContracts'
import { gatewaySupportsMethod, type GatewayHello } from '../openclawGateway'

export function startManagedRelayHeartbeat(options: {
  client: OpenClawClientPort
  hello: GatewayHello
  isCurrent: () => boolean
  onFailure: () => void
}): () => void {
  if (!gatewaySupportsMethod(options.hello, 'relay.ping')) return () => undefined
  let stopped = false
  let inFlight = false
  let timer: number | null = null
  const schedule = () => {
    if (stopped || timer !== null) return
    timer = window.setTimeout(() => { timer = null; void ping() }, 20_000)
  }
  const ping = async () => {
    if (stopped || inFlight || !options.isCurrent()) return
    if (document.hidden || !navigator.onLine) { schedule(); return }
    inFlight = true
    try {
      await options.client.request('relay.ping', {})
    } catch {
      if (!stopped && options.isCurrent() && !document.hidden && navigator.onLine) {
        options.onFailure()
        return
      }
    } finally {
      inFlight = false
    }
    schedule()
  }
  const probeWhenUsable = () => {
    if (!document.hidden && navigator.onLine) void ping()
  }
  document.addEventListener('visibilitychange', probeWhenUsable)
  window.addEventListener('online', probeWhenUsable)
  schedule()
  return () => {
    stopped = true
    if (timer !== null) window.clearTimeout(timer)
    document.removeEventListener('visibilitychange', probeWhenUsable)
    window.removeEventListener('online', probeWhenUsable)
  }
}
