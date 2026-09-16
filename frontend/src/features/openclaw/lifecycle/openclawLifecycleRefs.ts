import type {
  OpenClawChatMessage,
  OpenClawClientPort,
  OpenClawRunTrace,
} from '../openclawContracts'
import type { GatewayHello } from '../openclawGateway'

export type OpenClawLifecycleRefs = {
  connection: {
    client: OpenClawClientPort | null
    generation: number
    reconnectTimer: number | null
    reconnectDelay: number
    reconnectAttempt: number
    reconnecting: boolean
    manualClose: boolean
    automaticConnectKey: string | null
    reconnect: (reconnecting?: boolean) => void
    mediaTicketSupported: boolean
    hello: GatewayHello | null
    heartbeatStop: (() => void) | null
    stabilityTimer: number | null
  }
  session: {
    operation?: symbol
    agentId: string | null
    sessionKey: string | null
    thinkingLevel: string | null
    fastMode?: boolean
    navigationEpoch: number
  }
  run: {
    runId: string | null
    runTrace: OpenClawRunTrace | null
    pendingSend: boolean
    sendAttempt: number
    terminalSendAttempts: Set<number>
    agentEventSequence: Map<string, number>
    terminalRunIds: Set<string>
    streamText: string
    streamCreatedAt: number | null
  }
  transcript: {
    messages: OpenClawChatMessage[]
    readySessionKey: string | null
    mediaTicketRequests: Set<string>
  }
}

export function createOpenClawLifecycleRefs(): OpenClawLifecycleRefs {
  return {
    connection: {
      client: null,
      generation: 0,
      reconnectTimer: null,
      reconnectDelay: 1_000,
      reconnectAttempt: 0,
      reconnecting: false,
      manualClose: false,
      automaticConnectKey: null,
      reconnect: () => undefined,
      mediaTicketSupported: false,
      hello: null,
      heartbeatStop: null,
      stabilityTimer: null,
    },
    session: { agentId: null, sessionKey: null, thinkingLevel: null, navigationEpoch: 0 },
    run: {
      runId: null,
      runTrace: null,
      pendingSend: false,
      sendAttempt: 0,
      terminalSendAttempts: new Set(),
      agentEventSequence: new Map(),
      terminalRunIds: new Set(),
      streamText: '',
      streamCreatedAt: null,
    },
    transcript: { messages: [], readySessionKey: null, mediaTicketRequests: new Set() },
  }
}

export function stopOpenClawRecovery(connection: OpenClawLifecycleRefs['connection']): void {
  if (connection.reconnectTimer !== null) window.clearTimeout(connection.reconnectTimer)
  if (connection.stabilityTimer !== null) window.clearTimeout(connection.stabilityTimer)
  connection.reconnectTimer = null
  connection.stabilityTimer = null
  connection.heartbeatStop?.()
  connection.heartbeatStop = null
}
