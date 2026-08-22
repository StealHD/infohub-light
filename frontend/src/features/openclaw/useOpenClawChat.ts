import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'

import { projectOpenClawAgentEvent } from './chat/openclawEventProjection'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import type {
  OpenClawChatController,
  OpenClawChatOptions,
  OpenClawClientPort,
} from './openclawContracts'
import type { GatewayEvent } from './openclawGateway'
import {
  createOpenClawChatState,
  openClawChatReducer,
} from './lifecycle/openclawChatReducer'
import { createOpenClawLifecycleRefs } from './lifecycle/openclawLifecycleRefs'
import {
  initialOpenClawGatewayUrl,
  useOpenClawConnection,
} from './lifecycle/useOpenClawConnection'
import {
  type OpenClawChatEvent,
  useOpenClawConversationRun,
} from './lifecycle/useOpenClawConversationRun'
import { useOpenClawSessionRuntime } from './lifecycle/useOpenClawSessionRuntime'
import { useOpenClawTranscriptController } from './lifecycle/useOpenClawTranscriptController'
import { clearOpenClawTranscript } from './storage/openclawTranscriptStore'

export type {
  OpenClawChatController,
  OpenClawChatMessage,
  OpenClawChatOptions,
  OpenClawClientPort,
  OpenClawConnectionStatus,
  OpenClawContextUsage,
  OpenClawModelOption,
  OpenClawModelSwitchFallback,
  OpenClawRunActivity,
  OpenClawRunPhase,
  OpenClawRunTrace,
  OpenClawRuntimeSelection,
  OpenClawSanitizedAgentEvent,
  OpenClawSendRequest,
  OpenClawSendSnapshot,
  OpenClawSetupIssue,
  OpenClawThinkingOption,
  OpenClawToolsStatus,
} from './openclawContracts'
export { projectOpenClawAgentEvent } from './chat/openclawEventProjection'
export { projectChatHistory } from './chat/openclawHistoryProjection'
export {
  projectOpenClawContextUsage,
  projectOpenClawRuntime,
} from './chat/openclawRuntimeProjection'
export {
  OPENCLAW_GATEWAY_URL_KEY_PREFIX,
  readSavedGatewayUrl,
  saveGatewayUrl,
} from './storage/openclawGatewayPreferences'
export {
  OPENCLAW_TRANSCRIPT_KEY_PREFIX,
  boundChatMessages,
  clearOpenClawTranscript,
  mergeOpenClawTranscript,
  openClawTranscriptStorageKey,
  readOpenClawTranscript,
  writeOpenClawTranscript,
} from './storage/openclawTranscriptStore'

export function useOpenClawChat(options: OpenClawChatOptions): OpenClawChatController {
  const initialGatewayUrl = useMemo(
    () => initialOpenClawGatewayUrl(options.userId, options.defaultGatewayUrl),
    [options.defaultGatewayUrl, options.userId],
  )
  const gatewayUrlRef = useRef(initialGatewayUrl)
  const refs = useMemo(() => createOpenClawLifecycleRefs(), [])
  const vault = useMemo(() => options.vault ?? new OpenClawCredentialVault(), [options.vault])
  const [state, dispatch] = useReducer(
    openClawChatReducer,
    createOpenClawChatState(initialGatewayUrl, options.enabled ? 'idle' : 'disabled'),
  )
  const getGatewayUrl = useCallback(() => gatewayUrlRef.current, [])
  const setGatewayUrlRef = useCallback((value: string) => { gatewayUrlRef.current = value }, [])

  const transcript = useOpenClawTranscriptController({
    userId: options.userId,
    imageIoEnabled: Boolean(options.imageIoEnabled),
    mediaOrigins: options.mediaOrigins ?? [],
    refs,
    dispatch,
    getGatewayUrl,
  })
  const sessionBridge = useRef<{
    reloadRuntime: (client: OpenClawClientPort, sessionKey: string, agentId: string) => void
    setModel: (modelId: string | null) => Promise<boolean>
  }>({
    reloadRuntime: () => undefined,
    setModel: async () => false,
  })
  const reloadRuntime = useCallback((client: OpenClawClientPort, sessionKey: string, agentId: string) => {
    sessionBridge.current.reloadRuntime(client, sessionKey, agentId)
  }, [])
  const setModelBridge = useCallback((modelId: string | null) => sessionBridge.current.setModel(modelId), [])
  const conversation = useOpenClawConversationRun({
    refs,
    state,
    dispatch,
    transcript,
    reloadRuntime,
    setModel: setModelBridge,
  })
  const session = useOpenClawSessionRuntime({
    userId: options.userId,
    refs,
    state,
    dispatch,
    vault,
    getGatewayUrl,
    transcript,
    resetConversation: conversation.reset,
  })
  useEffect(() => {
    sessionBridge.current.reloadRuntime = session.reloadRuntime
    sessionBridge.current.setModel = session.setModel
  }, [session.reloadRuntime, session.setModel])

  const routeGatewayEvent = useCallback((event: GatewayEvent, generation: number) => {
    if (generation !== refs.connection.generation) return
    const sessionKey = refs.session.sessionKey
    if (!sessionKey) return
    if (event.event === 'sessions.changed') {
      session.routeContextUsage(event.payload, sessionKey)
      return
    }
    if (event.event === 'agent') {
      const projected = projectOpenClawAgentEvent(event, sessionKey)
      if (projected) conversation.handleAgent(projected)
      return
    }
    if (event.event !== 'chat' || !event.payload || typeof event.payload !== 'object') return
    const payload = event.payload as Partial<OpenClawChatEvent>
    if (payload.sessionKey !== sessionKey || !conversation.acceptsRun(payload.runId)) return
    conversation.handleChat(payload as OpenClawChatEvent)
  }, [conversation, refs, session])

  const connection = useOpenClawConnection({
    options,
    state,
    refs,
    dispatch,
    vault,
    routeEvent: routeGatewayEvent,
    session,
    transcript,
    resetConversation: conversation.reset,
    getGatewayUrl,
    setGatewayUrlRef,
  })

  useEffect(() => {
    if (gatewayUrlRef.current === initialGatewayUrl) return
    gatewayUrlRef.current = initialGatewayUrl
    dispatch({ type: 'patch', value: { gatewayUrl: initialGatewayUrl } })
  }, [initialGatewayUrl])

  const clearTranscript = useCallback(() => transcript.clear(state.gatewayUrl), [state.gatewayUrl, transcript])
  const forget = useCallback(async () => {
    await forgetOpenClawBrowser({
      userId: options.userId,
      gatewayUrl: state.gatewayUrl,
      vault,
      clearTranscripts: clearOpenClawTranscript,
      clientFactory: options.clientFactory,
    })
    clearTranscript()
    connection.disconnect()
  }, [clearTranscript, connection, options.clientFactory, options.userId, state.gatewayUrl, vault])

  const status = !options.enabled ? 'disabled' : state.status === 'disabled' ? 'idle' : state.status
  const currentModelSupportsImages = state.models
    .find((model) => model.id === state.runtimeSelection.modelId)?.supportsImages === true
  return {
    gatewayUrl: state.gatewayUrl,
    setGatewayUrl: connection.setGatewayUrl,
    status,
    toolsStatus: state.toolsStatus,
    messages: state.messages,
    streamText: state.streamText,
    streamCreatedAt: state.streamCreatedAt,
    runTrace: state.runTrace,
    issue: state.issue,
    runtimeIssue: state.runtimeIssue,
    modelSwitchFallback: state.modelSwitchFallback,
    contextUsage: state.contextUsage,
    imageInputAvailable: state.imageInputAvailable,
    currentModelSupportsImages,
    sessionKey: state.sessionKey,
    isRunning: state.sending || Boolean(state.runId),
    isStopping: state.stopping,
    reconnectAttempt: state.reconnectAttempt,
    runtimeLoading: state.runtimeLoading,
    runtimeUpdating: state.runtimeUpdating,
    models: state.models,
    thinkingOptions: state.thinkingOptions,
    runtimeSelection: state.runtimeSelection,
    connect: connection.connect,
    retryConnection: connection.retryConnection,
    disconnect: connection.disconnect,
    clearTranscript,
    forget,
    send: conversation.send,
    retry: conversation.retry,
    takeFailedMessage: conversation.takeFailedMessage,
    refreshMedia: conversation.refreshMedia,
    stop: conversation.stop,
    setModel: session.setModel,
    setThinking: session.setThinking,
    switchToBlankConversation: session.switchToBlankConversation,
    newConversation: session.newConversation,
  }
}
