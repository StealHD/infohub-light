import { useEffect } from 'react'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'

/** Release sockets on navigation, including the browser back/forward cache. */
export function useOpenClawPageLifecycle(
  pause: () => void,
  disconnect: () => void,
  connection: OpenClawLifecycleRefs['connection'],
  gatewayUrl: string,
  enabled: boolean,
  userId: string,
): void {
  useEffect(() => {
    let resume = false
    const hide = () => {
      resume = !connection.manualClose
        && (connection.client !== null || connection.reconnectTimer !== null)
      pause()
    }
    const show = (event: PageTransitionEvent) => {
      if (!event.persisted || !resume || !enabled) return
      resume = false
      connection.reconnect(true)
    }
    window.addEventListener('pagehide', hide)
    window.addEventListener('pageshow', show)
    return () => {
      window.removeEventListener('pagehide', hide)
      window.removeEventListener('pageshow', show)
      disconnect()
    }
  }, [pause, disconnect, connection, gatewayUrl, enabled, userId])
}
