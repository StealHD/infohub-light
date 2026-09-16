import type { OpenClawChatDispatch } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'

const STABLE_CONNECTION_MS = 60_000
const MAX_RECONNECT_DELAY_MS = 30_000

type ConnectionRefs = OpenClawLifecycleRefs['connection']

export function scheduleOpenClawReconnect(
  connection: ConnectionRefs,
  dispatch: OpenClawChatDispatch,
  random: () => number = Math.random,
): void {
  if (connection.manualClose || connection.reconnectTimer !== null) return
  connection.reconnectAttempt += 1
  dispatch({ type: 'patch', value: {
    status: 'reconnecting', issue: null, reconnectAttempt: connection.reconnectAttempt,
  } })
  const baseDelay = connection.reconnectDelay
  const jitteredDelay = Math.max(250, Math.round(baseDelay * (0.8 + random() * 0.4)))
  connection.reconnectDelay = Math.min(Math.round(baseDelay * 1.7), MAX_RECONNECT_DELAY_MS)
  connection.reconnectTimer = window.setTimeout(() => {
    connection.reconnectTimer = null
    connection.reconnect(true)
  }, jitteredDelay)
}

export function markOpenClawConnectionStable(
  connection: ConnectionRefs,
  dispatch: OpenClawChatDispatch,
  isCurrent: () => boolean,
): void {
  if (connection.stabilityTimer !== null) window.clearTimeout(connection.stabilityTimer)
  connection.stabilityTimer = window.setTimeout(() => {
    connection.stabilityTimer = null
    if (!isCurrent()) return
    connection.reconnectDelay = 1_000
    connection.reconnectAttempt = 0
    dispatch({ type: 'patch', value: { reconnectAttempt: 0 } })
  }, STABLE_CONNECTION_MS)
}
