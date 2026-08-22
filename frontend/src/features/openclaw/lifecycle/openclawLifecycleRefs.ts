import type {
  OpenClawChatMessage,
  OpenClawClientPort,
  OpenClawRunTrace,
} from '../openclawContracts'

export type OpenClawLifecycleRefs = {
  connection: {
    client: OpenClawClientPort | null
    generation: number
    reconnectTimer: number | null
    reconnectDelay: number
    reconnectAttempt: number
    manualClose: boolean
    automaticConnectKey: string | null
    reconnect: (reconnecting?: boolean) => void
    mediaTicketSupported: boolean
  }
  session: {
    agentId: string | null
    sessionKey: string | null
    thinkingLevel: string | null
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
      manualClose: false,
      automaticConnectKey: null,
      reconnect: () => undefined,
      mediaTicketSupported: false,
    },
    session: { agentId: null, sessionKey: null, thinkingLevel: null },
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
