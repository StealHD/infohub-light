import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { applyAgentEventToTrace, projectOpenClawAgentEvent } from './chat/openclawEventProjection'
import {
  openClawSourceReferences,
  sanitizeOpenClawSourceUrl,
} from './chat/openclawHandoffProtocol'
import { projectChatHistory, projectChatMessage } from './chat/openclawHistoryProjection'
import { stringOf } from './chat/openclawProjectionUtils'
import {
  contextUsagePayloadMatchesSession,
  type OpenClawRuntimeProjection,
  projectOpenClawContextUsage,
  projectOpenClawRuntime,
} from './chat/openclawRuntimeProjection'
import { hasInteliscopeTools, runtimeFailureMessage, setupIssue } from './chat/openclawSetupIssue'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import {
  OPENCLAW_CURRENT_SCOPES,
  OpenClawGatewayClient,
  generateDeviceIdentity,
  gatewaySupportsMethod,
  parseOpenClawConnectionInput,
  validateGatewayUrl,
  type GatewayEvent,
  type GatewayHello,
} from './openclawGateway'
import {
  parseOpenClawMediaTicket,
  releaseOpenClawImageUrl,
  ticketUrlForOpenClawMedia,
} from './openclawMedia'
import type {
  OpenClawChatController,
  OpenClawChatMessage,
  OpenClawChatOptions,
  OpenClawClientPort,
  OpenClawConnectionStatus,
  OpenClawContextUsage,
  OpenClawModelOption,
  OpenClawModelSwitchFallback,
  OpenClawRunActivity,
  OpenClawRunTrace,
  OpenClawRuntimeSelection,
  OpenClawSendRequest,
  OpenClawSendSnapshot,
  OpenClawSetupIssue,
  OpenClawThinkingOption,
  OpenClawToolsStatus,
} from './openclawContracts'
import {
  readSavedGatewayUrl,
  saveGatewayUrl,
} from './storage/openclawGatewayPreferences'
import {
  OPENCLAW_MAX_HISTORY_CHARS,
  OPENCLAW_MAX_MESSAGES,
  boundChatMessages,
  clearOpenClawTranscript,
  mergeOpenClawTranscript,
  messageMergeId,
  readOpenClawTranscript,
  writeOpenClawTranscript,
} from './storage/openclawTranscriptStore'
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
import {
  createOpenClawSessionLabel,
  isOpenClawSessionLabelConflict,
} from './openclawSession'

export {
  projectOpenClawAgentEvent,
} from './chat/openclawEventProjection'
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

type ChatEventPayload = {
  state?: 'delta' | 'final' | 'aborted' | 'error'
  sessionKey?: string
  runId?: string
  deltaText?: string
  replace?: boolean
  errorMessage?: string
  message?: unknown
}

type OpenClawSessionCreateParams = {
  agentId: string
  parentSessionKey?: string
  fork?: true
  model?: string
}

async function createOpenClawSession(
  client: OpenClawClientPort,
  params: OpenClawSessionCreateParams,
): Promise<{ key?: string }> {
  const create = () => client.request<{ key?: string }>('sessions.create', {
    ...params,
    label: createOpenClawSessionLabel(window.location.host),
  })
  try {
    return await create()
  } catch (error) {
    if (!isOpenClawSessionLabelConflict(error)) throw error
    return create()
  }
}

export function useOpenClawChat(options: OpenClawChatOptions): OpenClawChatController {
  const vault = useMemo(() => options.vault ?? new OpenClawCredentialVault(), [options.vault])
  const configurationKey = `${options.userId}\n${options.defaultGatewayUrl}`
  const hasConfiguredMediaOrigins = Boolean(options.mediaOrigins?.length)
  const [gatewayState, setGatewayState] = useState(() => ({
    configurationKey,
    value: readSavedGatewayUrl(options.userId, options.defaultGatewayUrl),
  }))
  const gatewayUrl = gatewayState.configurationKey === configurationKey
    ? gatewayState.value
    : readSavedGatewayUrl(options.userId, options.defaultGatewayUrl)
  const gatewayUrlRef = useRef(gatewayUrl)
  const [status, setStatus] = useState<OpenClawConnectionStatus>(options.enabled ? 'idle' : 'disabled')
  const [toolsStatus, setToolsStatus] = useState<OpenClawToolsStatus>('unknown')
  const [messages, setMessages] = useState<OpenClawChatMessage[]>([])
  const [streamText, setStreamText] = useState('')
  const [streamCreatedAt, setStreamCreatedAt] = useState<number | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runTrace, setRunTrace] = useState<OpenClawRunTrace | null>(null)
  const [sending, setSending] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [reconnectAttempt, setReconnectAttempt] = useState(0)
  const [issue, setIssue] = useState<OpenClawSetupIssue | null>(null)
  const [sessionKey, setSessionKey] = useState<string | null>(null)
  const [models, setModels] = useState<OpenClawModelOption[]>([])
  const [thinkingOptions, setThinkingOptions] = useState<OpenClawThinkingOption[]>([])
  const [runtimeSelection, setRuntimeSelection] = useState<OpenClawRuntimeSelection>({
    modelId: null,
    thinkingLevel: null,
    defaultModelId: null,
    defaultThinkingLevel: null,
  })
  const [runtimeLoading, setRuntimeLoading] = useState(false)
  const [runtimeUpdating, setRuntimeUpdating] = useState(false)
  const [runtimeIssue, setRuntimeIssue] = useState<string | null>(null)
  const [modelSwitchFallback, setModelSwitchFallback] = useState<OpenClawModelSwitchFallback | null>(null)
  const [contextUsage, setContextUsage] = useState<OpenClawContextUsage | null>(null)
  const [imageInputAvailable, setImageInputAvailable] = useState(false)
  const clientRef = useRef<OpenClawClientPort | null>(null)
  const agentIdRef = useRef<string | null>(null)
  const sessionKeyRef = useRef<string | null>(null)
  const runIdRef = useRef<string | null>(null)
  const runTraceRef = useRef<OpenClawRunTrace | null>(null)
  const pendingSendRef = useRef(false)
  const sendAttemptRef = useRef(0)
  const terminalSendAttemptsRef = useRef(new Set<number>())
  const agentEventSeqRef = useRef(new Map<string, number>())
  const reconnectTimerRef = useRef<number | null>(null)
  const reconnectDelayRef = useRef(1000)
  const reconnectAttemptRef = useRef(0)
  const generationRef = useRef(0)
  const manualCloseRef = useRef(false)
  const automaticConnectKeyRef = useRef<string | null>(null)
  const reconnectRef = useRef<(reconnecting?: boolean) => void>(() => undefined)
  const streamTextRef = useRef('')
  const streamCreatedAtRef = useRef<number | null>(null)
  const messagesRef = useRef<OpenClawChatMessage[]>([])
  const transcriptReadyKeyRef = useRef<string | null>(null)
  const terminalRunIdsRef = useRef(new Set<string>())
  const thinkingLevelRef = useRef<string | null>(null)
  const mediaTicketRequestsRef = useRef(new Set<string>())
  const mediaTicketSupportedRef = useRef(false)
  const setModelRef = useRef<(modelId: string | null) => Promise<boolean>>(async () => false)

  const updateRunTrace = useCallback((
    update: OpenClawRunTrace | null | ((current: OpenClawRunTrace | null) => OpenClawRunTrace | null),
  ) => {
    setRunTrace((current) => {
      const next = typeof update === 'function' ? update(current) : update
      runTraceRef.current = next
      return next
    })
  }, [])

  const beginRunTrace = useCallback((contextCount: number) => {
    const startedAt = Date.now()
    agentEventSeqRef.current.clear()
    const activities: OpenClawRunActivity[] = contextCount > 0 ? [{
      id: 'context',
      label: `接收 ${contextCount} 条上下文`,
      status: 'completed',
      startedAt,
      endedAt: startedAt,
    }] : []
    updateRunTrace({
      runId: null,
      phase: 'sending',
      status: 'running',
      startedAt,
      activities,
    })
  }, [updateRunTrace])

  const finishRunTrace = useCallback((
    terminal: 'completed' | 'aborted' | 'failed',
    completedRunId: string,
  ) => {
    const endedAt = Date.now()
    updateRunTrace((current) => {
      const trace = current ?? {
        runId: completedRunId,
        phase: terminal,
        status: terminal,
        startedAt: endedAt,
        activities: [],
      }
      return {
        ...trace,
        runId: completedRunId,
        phase: terminal,
        status: terminal,
        endedAt,
        activities: trace.activities.map((activity) => activity.status === 'running'
          ? { ...activity, status: terminal === 'completed' ? 'completed' : 'stopped', endedAt }
          : activity),
      }
    })
  }, [updateRunTrace])

  const persistVisibleTranscript = useCallback((
    update: OpenClawChatMessage[] | ((current: OpenClawChatMessage[]) => OpenClawChatMessage[]),
    keyOverride?: string,
  ): OpenClawChatMessage[] => {
    const next = boundChatMessages(typeof update === 'function' ? update(messagesRef.current) : update)
    const retainedUrls = new Set(next.flatMap((message) => message.images?.map((image) => image.url).filter((url): url is string => Boolean(url)) ?? []))
    for (const previous of messagesRef.current) {
      for (const image of previous.images ?? []) {
        if (image.url && !retainedUrls.has(image.url)) releaseOpenClawImageUrl(image.url)
      }
    }
    messagesRef.current = next
    const key = keyOverride ?? sessionKeyRef.current
    if (key && transcriptReadyKeyRef.current === key) {
      writeOpenClawTranscript(options.userId, gatewayUrlRef.current, key, next)
    }
    setMessages(next)
    return next
  }, [options.userId])

  const replaceVisibleTranscript = useCallback((next: OpenClawChatMessage[]) => {
    const bounded = boundChatMessages(next)
    const retainedUrls = new Set(bounded.flatMap((message) => message.images?.map((image) => image.url).filter((url): url is string => Boolean(url)) ?? []))
    for (const previous of messagesRef.current) {
      for (const image of previous.images ?? []) {
        if (image.url && !retainedUrls.has(image.url)) releaseOpenClawImageUrl(image.url)
      }
    }
    messagesRef.current = bounded
    setMessages(bounded)
  }, [])

  const setGatewayUrl = useCallback((value: string) => {
    const normalized = validateGatewayUrl(value)
    gatewayUrlRef.current = normalized
    setGatewayState({ configurationKey, value: normalized })
    saveGatewayUrl(options.userId, normalized)
  }, [configurationKey, options.userId])

  const resolveMediaTickets = useCallback(async (
    client: OpenClawClientPort,
    key: string,
    sourceMessages: OpenClawChatMessage[],
    force = false,
  ) => {
    if (!options.imageIoEnabled || !mediaTicketSupportedRef.current || sessionKeyRef.current !== key) return
    const candidates = sourceMessages.flatMap((message) => (message.images ?? []).flatMap((image) => (
      image.reference && (force || !image.url) ? [{ messageId: message.id, image }] : []
    )))
    await Promise.all(candidates.map(async ({ image }) => {
      const reference = image.reference!
      const requestKey = `${key}:${reference.messageId}:${reference.partIndex}`
      if (mediaTicketRequestsRef.current.has(requestKey)) return
      mediaTicketRequestsRef.current.add(requestKey)
      try {
        const ticket = parseOpenClawMediaTicket(await client.request('chat.media.ticket', {
          sessionKey: key,
          messageId: reference.messageId,
          partIndex: reference.partIndex,
        }))
        const url = ticket ? ticketUrlForOpenClawMedia(gatewayUrlRef.current, ticket, options.mediaOrigins ?? []) : null
        if (!url || sessionKeyRef.current !== key) return
        persistVisibleTranscript((current) => current.map((message) => !message.images?.some((candidate) => candidate.id === image.id)
          ? message
          : {
              ...message,
              images: message.images?.map((candidate) => candidate.id === image.id
                ? {
                    ...candidate,
                    ...(ticket?.mimeType ? { mimeType: ticket.mimeType } : {}),
                    ...(ticket?.width ? { width: ticket.width } : {}),
                    ...(ticket?.height ? { height: ticket.height } : {}),
                    url,
                  }
                : candidate),
            }))
      } catch {
        // A delayed history refresh or an expired media ticket must not fail the conversation.
      } finally {
        mediaTicketRequestsRef.current.delete(requestKey)
      }
    }))
  }, [options.imageIoEnabled, options.mediaOrigins, persistVisibleTranscript])

  const loadHistory = useCallback(async (client: OpenClawClientPort, key: string, agentId: string) => {
    const history = await client.request('chat.history', {
      sessionKey: key,
      agentId,
      limit: OPENCLAW_MAX_MESSAGES,
      maxChars: OPENCLAW_MAX_HISTORY_CHARS,
    })
    if (sessionKeyRef.current !== key) return
    const stored = readOpenClawTranscript(options.userId, gatewayUrlRef.current, key)
    const gatewayMessages = projectChatHistory(history)
    transcriptReadyKeyRef.current = key
    persistVisibleTranscript((current) => mergeOpenClawTranscript(
      mergeOpenClawTranscript(stored, current),
      gatewayMessages,
    ), key)
    void resolveMediaTickets(client, key, gatewayMessages)
  }, [options.userId, persistVisibleTranscript, resolveMediaTickets])

  const readRuntime = useCallback(async (client: OpenClawClientPort, key: string, agentId: string) => {
    const [modelsValue, agentsValue, sessionValue] = await Promise.all([
      client.request('models.list', { view: 'configured' }),
      client.request('agents.list', {}),
      client.request('sessions.describe', { key }),
    ])
    return projectOpenClawRuntime(modelsValue, agentsValue, sessionValue, agentId)
  }, [])

  const applyRuntime = useCallback((projection: OpenClawRuntimeProjection, preserveThinking = false) => {
    const selectedModel = projection.models.find((model) => model.id === projection.selection.modelId)
    const preservedThinking = preserveThinking
      && selectedModel?.reasoning !== false
      && thinkingLevelRef.current
      && projection.thinkingOptions.some((option) => option.id === thinkingLevelRef.current)
        ? thinkingLevelRef.current
        : projection.selection.thinkingLevel
    const selection = { ...projection.selection, thinkingLevel: preservedThinking }
    setModels(projection.models)
    setThinkingOptions(projection.thinkingOptions)
    setRuntimeSelection(selection)
    thinkingLevelRef.current = selection.thinkingLevel
    if (projection.invalidSessionModel && projection.selection.defaultModelId) {
      const fallbackModel = projection.models.find((model) => model.id === projection.selection.defaultModelId)
      setRuntimeIssue('当前对话模型已不可用，可切换到 OpenClaw 默认模型。')
      setModelSwitchFallback(fallbackModel ? { modelId: fallbackModel.id, modelName: fallbackModel.name } : null)
    } else {
      setModelSwitchFallback(null)
    }
  }, [])

  const loadRuntime = useCallback(async (
    client: OpenClawClientPort,
    key: string,
    agentId: string,
    preserveThinking = false,
  ): Promise<OpenClawRuntimeProjection | null> => {
    setRuntimeLoading(true)
    setRuntimeIssue(null)
    try {
      const projection = await readRuntime(client, key, agentId)
      applyRuntime(projection, preserveThinking)
      return projection
    } catch (error) {
      setRuntimeIssue(runtimeFailureMessage(error, 'load'))
      return null
    } finally {
      setRuntimeLoading(false)
    }
  }, [applyRuntime, readRuntime])

  const loadContextUsage = useCallback(async (client: OpenClawClientPort, key: string) => {
    if (sessionKeyRef.current === key) setContextUsage(null)
    const [, listResult] = await Promise.allSettled([
      client.request('sessions.subscribe', {}),
      client.request('sessions.list', { search: key, limit: 100 }),
    ])
    if (sessionKeyRef.current !== key || listResult.status !== 'fulfilled') return
    setContextUsage(projectOpenClawContextUsage(listResult.value, key))
  }, [])

  useEffect(() => { streamTextRef.current = streamText }, [streamText])

  const handleGatewayEvent = useCallback((event: GatewayEvent) => {
    if (event.event === 'sessions.changed') {
      const key = sessionKeyRef.current
      if (!key || !contextUsagePayloadMatchesSession(event.payload, key)) return
      setContextUsage(projectOpenClawContextUsage(event.payload, key))
      return
    }
    if (event.event === 'agent') {
      const key = sessionKeyRef.current
      if (!key) return
      const projected = projectOpenClawAgentEvent(event, key)
      if (!projected || terminalRunIdsRef.current.has(projected.runId)) return
      if (runIdRef.current && projected.runId !== runIdRef.current) return
      if (!runIdRef.current && !pendingSendRef.current && runTraceRef.current?.status !== 'running') return
      const previousSeq = agentEventSeqRef.current.get(projected.runId)
      if (previousSeq !== undefined && projected.seq <= previousSeq) return
      agentEventSeqRef.current.set(projected.runId, projected.seq)
      if (!runIdRef.current) {
        runIdRef.current = projected.runId
        setRunId(projected.runId)
      }
      updateRunTrace((current) => applyAgentEventToTrace(current, projected))
      return
    }
    if (event.event !== 'chat' || !event.payload || typeof event.payload !== 'object') return
    const payload = event.payload as ChatEventPayload
    if (!payload.sessionKey || payload.sessionKey !== sessionKeyRef.current) return
    if (payload.runId && terminalRunIdsRef.current.has(payload.runId)) return
    if (runIdRef.current && payload.runId && payload.runId !== runIdRef.current) return
    if (!runIdRef.current && payload.runId) {
      runIdRef.current = payload.runId
      setRunId(payload.runId)
    }
    if (payload.state === 'delta' && typeof payload.deltaText === 'string') {
      updateRunTrace((current) => current ? {
        ...current,
        runId: payload.runId ?? current.runId,
        phase: 'streaming',
        status: 'running',
      } : current)
      if (streamCreatedAtRef.current === null && payload.deltaText) {
        const createdAt = Date.now()
        streamCreatedAtRef.current = createdAt
        setStreamCreatedAt(createdAt)
      }
      setStreamText((current) => {
        const next = (payload.replace ? payload.deltaText! : `${current}${payload.deltaText}`).slice(0, OPENCLAW_MAX_HISTORY_CHARS)
        streamTextRef.current = next
        return next
      })
      return
    }
    if (payload.state === 'error') setIssue({ kind: 'unknown', message: 'OpenClaw 对话失败，请重试。' })
    if (payload.state === 'final' || payload.state === 'aborted' || payload.state === 'error') {
      const partialText = streamTextRef.current.trim()
      const partialCreatedAt = streamCreatedAtRef.current ?? Date.now()
      const completedRunId = payload.runId || runIdRef.current || crypto.randomUUID()
      terminalRunIdsRef.current.add(completedRunId)
      if (terminalRunIdsRef.current.size > 20) terminalRunIdsRef.current.delete(terminalRunIdsRef.current.values().next().value!)
      if (pendingSendRef.current) {
        terminalSendAttemptsRef.current.add(sendAttemptRef.current)
        if (terminalSendAttemptsRef.current.size > 20) {
          terminalSendAttemptsRef.current.delete(terminalSendAttemptsRef.current.values().next().value!)
        }
      }
      runIdRef.current = null
      pendingSendRef.current = false
      setRunId(null)
      setSending(false)
      setStopping(false)
      streamTextRef.current = ''
      streamCreatedAtRef.current = null
      setStreamText('')
      setStreamCreatedAt(null)
      const client = clientRef.current
      const key = sessionKeyRef.current
      const agentId = agentIdRef.current
      finishRunTrace(
        payload.state === 'aborted' ? 'aborted' : payload.state === 'error' ? 'failed' : 'completed',
        completedRunId,
      )
      if (client && key && agentId) void loadRuntime(client, key, agentId, true)
      const assistantMessage = projectChatMessage(payload.message, {
        id: `${payload.state}-${completedRunId}`,
        role: 'assistant',
        text: partialText,
        createdAt: partialCreatedAt,
      })
      if (assistantMessage) {
        assistantMessage.status = payload.state === 'aborted' ? 'aborted' : payload.state === 'error' ? 'failed' : 'sent'
        assistantMessage.origin = 'local'
        persistVisibleTranscript((current) => mergeOpenClawTranscript(current, [assistantMessage]), key ?? undefined)
        if (client && key) void resolveMediaTickets(client, key, [assistantMessage])
      }
      if (payload.state === 'aborted') return
      if (client && key && agentId) void loadHistory(client, key, agentId).catch(() => undefined)
    }
  }, [finishRunTrace, loadHistory, loadRuntime, persistVisibleTranscript, resolveMediaTickets, updateRunTrace])

  const disconnect = useCallback(() => {
    manualCloseRef.current = true
    generationRef.current += 1
    if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current)
    reconnectTimerRef.current = null
    clientRef.current?.close()
    clientRef.current = null
    agentIdRef.current = null
    sessionKeyRef.current = null
    transcriptReadyKeyRef.current = null
    runIdRef.current = null
    pendingSendRef.current = false
    sendAttemptRef.current += 1
    terminalSendAttemptsRef.current.clear()
    agentEventSeqRef.current.clear()
    terminalRunIdsRef.current.clear()
    setRunId(null)
    updateRunTrace(null)
    setSending(false)
    setStopping(false)
    reconnectAttemptRef.current = 0
    setReconnectAttempt(0)
    setSessionKey(null)
    streamTextRef.current = ''
    setStreamText('')
    setStreamCreatedAt(null)
    streamCreatedAtRef.current = null
    replaceVisibleTranscript([])
    setModels([])
    setThinkingOptions([])
    setRuntimeSelection({ modelId: null, thinkingLevel: null, defaultModelId: null, defaultThinkingLevel: null })
    setRuntimeLoading(false)
    setRuntimeUpdating(false)
    setRuntimeIssue(null)
    setModelSwitchFallback(null)
    setContextUsage(null)
    mediaTicketSupportedRef.current = false
    setImageInputAvailable(false)
    thinkingLevelRef.current = null
    setToolsStatus('unknown')
    setStatus(options.enabled ? 'idle' : 'disabled')
  }, [options.enabled, replaceVisibleTranscript, updateRunTrace])

  const connectInternal = useCallback(async (authInput?: string, reconnecting = false, requestedUrl?: string): Promise<boolean> => {
    if (!options.enabled) return false
    const generation = ++generationRef.current
    manualCloseRef.current = false
    setStatus(reconnecting ? 'reconnecting' : 'connecting')
    setIssue(null)
    try {
      const parsed = authInput
        ? parseOpenClawConnectionInput(requestedUrl ?? gatewayUrlRef.current, authInput)
        : { gatewayUrl: validateGatewayUrl(requestedUrl ?? gatewayUrlRef.current), bootstrapToken: '' }
      if (parsed.gatewayUrl !== gatewayUrlRef.current) setGatewayUrl(parsed.gatewayUrl)
      const stored = await vault.load(options.userId, parsed.gatewayUrl)
      if (!stored && !parsed.bootstrapToken) throw new Error('请输入 OpenClaw Gateway token 完成首次配对。')
      const identity = stored?.identity ?? await generateDeviceIdentity()
      const factory = options.clientFactory ?? ((clientOptions) => new OpenClawGatewayClient(clientOptions))
      const client = factory({
        url: parsed.gatewayUrl,
        bootstrapToken: parsed.bootstrapToken || undefined,
        deviceToken: parsed.bootstrapToken ? undefined : stored?.deviceToken,
        deviceIdentity: identity,
        requestedScopes: parsed.bootstrapToken
          ? OPENCLAW_CURRENT_SCOPES
          : stored?.scopes ?? OPENCLAW_CURRENT_SCOPES,
        platform: navigator.platform || 'web',
        deviceFamily: 'browser',
        onEvent: handleGatewayEvent,
        onClose: () => {
          if (manualCloseRef.current || generation !== generationRef.current) return
          setStatus('reconnecting')
          reconnectAttemptRef.current += 1
          setReconnectAttempt(reconnectAttemptRef.current)
          const delay = reconnectDelayRef.current
          reconnectDelayRef.current = Math.min(Math.round(delay * 1.7), 30_000)
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectTimerRef.current = null
            reconnectRef.current(true)
          }, delay)
        },
      })
      clientRef.current?.close()
      clientRef.current = client
      const hello: GatewayHello = await client.connect()
      if (generation !== generationRef.current) { client.close(); return false }
      // `chat.send.attachments` is part of the stock Gateway chat protocol.
      // `chat.media.ticket` is only needed to render trusted assistant/history
      // images across the Inteliscope and Gateway origins.
      mediaTicketSupportedRef.current = Boolean(
        options.imageIoEnabled
        && hasConfiguredMediaOrigins
        && gatewaySupportsMethod(hello, 'chat.media.ticket'),
      )
      setImageInputAvailable(Boolean(options.imageIoEnabled))
      const deviceToken = hello.auth?.deviceToken || stored?.deviceToken
      if (!deviceToken) throw new Error('OpenClaw 没有返回浏览器设备 token。')
      const credential = {
        identity,
        deviceToken,
        scopes: hello.auth?.scopes ?? stored?.scopes ?? [],
      }
      await vault.save(options.userId, parsed.gatewayUrl, {
        ...credential,
        sessionKey: stored?.sessionKey,
      })
      const agentId = hello.snapshot?.sessionDefaults?.defaultAgentId
      if (!agentId) throw new Error('OpenClaw Gateway 没有返回默认 Agent。')
      agentIdRef.current = agentId
      let key = stored?.sessionKey
      if (!key) {
        const created = await createOpenClawSession(client, { agentId })
        const createdKey = stringOf(created.key)
        if (!createdKey) throw new Error('OpenClaw 无法创建 Inscope 对话。')
        key = createdKey
        await vault.save(options.userId, parsed.gatewayUrl, { ...credential, sessionKey: key })
      }
      if (!key) throw new Error('OpenClaw 无法创建 Inscope 对话。')
      sessionKeyRef.current = key
      setSessionKey(key)
      transcriptReadyKeyRef.current = key
      persistVisibleTranscript((current) => mergeOpenClawTranscript(
        readOpenClawTranscript(options.userId, parsed.gatewayUrl, key),
        current,
      ), key)
      const [tools] = await Promise.all([
        client.request('tools.effective', { sessionKey: key, agentId }),
        loadHistory(client, key, agentId),
        loadRuntime(client, key, agentId),
        loadContextUsage(client, key),
      ])
      setToolsStatus(hasInteliscopeTools(tools) ? 'available' : 'missing')
      reconnectDelayRef.current = 1000
      reconnectAttemptRef.current = 0
      setReconnectAttempt(0)
      setStatus('connected')
      return true
    } catch (error) {
      if (generation === generationRef.current) {
        clientRef.current?.close()
        clientRef.current = null
        setStatus('error')
        setIssue(setupIssue(error))
      }
      return false
    }
  }, [handleGatewayEvent, hasConfiguredMediaOrigins, loadContextUsage, loadHistory, loadRuntime, options.clientFactory, options.enabled, options.imageIoEnabled, options.userId, persistVisibleTranscript, setGatewayUrl, vault])

  useEffect(() => {
    reconnectRef.current = (reconnecting = true) => { void connectInternal(undefined, reconnecting) }
  }, [connectInternal])

  const retryConnection = useCallback(() => {
    if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current)
    reconnectTimerRef.current = null
    reconnectRef.current(true)
  }, [])

  const submitSend = useCallback(async (snapshot: OpenClawSendSnapshot, messageId: string): Promise<boolean> => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    const agentId = agentIdRef.current
    if (!client || !key || !agentId || !snapshot.gatewayPrompt.trim() || runIdRef.current) return false
    const sendAttempt = ++sendAttemptRef.current
    terminalSendAttemptsRef.current.delete(sendAttempt)
    beginRunTrace(snapshot.contextCount ?? snapshot.contextItems.length)
    pendingSendRef.current = true
    streamTextRef.current = ''
    streamCreatedAtRef.current = null
    setStreamText('')
    setStreamCreatedAt(null)
    setIssue(null)
    setSending(true)
    try {
      const result = await client.request<{ runId?: string }>('chat.send', {
        sessionKey: key,
        agentId,
        message: snapshot.gatewayPrompt,
        deliver: false,
      idempotencyKey: snapshot.idempotencyKey,
      ...(snapshot.thinkingLevel ? { thinking: snapshot.thinkingLevel } : {}),
      ...(snapshot.attachments?.length ? {
        attachments: snapshot.attachments.map((attachment) => ({
          type: 'image',
          mimeType: attachment.mimeType,
          fileName: attachment.fileName,
          content: attachment.content,
        })),
      } : {}),
      })
      const terminatedBeforeResponse = terminalSendAttemptsRef.current.delete(sendAttempt)
      persistVisibleTranscript((current) => current.map((message) => (
        message.id === messageId ? { ...message, status: 'sent', sendSnapshot: undefined } : message
      )))
      if (sendAttempt !== sendAttemptRef.current || terminatedBeforeResponse) return true
      runIdRef.current = runIdRef.current || result.runId || snapshot.idempotencyKey
      setRunId(runIdRef.current)
      pendingSendRef.current = false
      updateRunTrace((current) => current ? {
        ...current,
        runId: runIdRef.current,
        phase: current.phase === 'sending' ? 'waiting' : current.phase,
      } : current)
      return true
    } catch (error) {
      const terminatedBeforeResponse = terminalSendAttemptsRef.current.delete(sendAttempt)
      if (terminatedBeforeResponse) {
        persistVisibleTranscript((current) => current.map((message) => (
          message.id === messageId ? { ...message, status: 'sent', sendSnapshot: undefined } : message
        )))
        return true
      }
      persistVisibleTranscript((current) => current.map((message) => (
        message.id === messageId ? { ...message, status: 'failed' } : message
      )))
      if (sendAttempt !== sendAttemptRef.current) return false
      const failedRunId = runIdRef.current || snapshot.idempotencyKey
      pendingSendRef.current = false
      runIdRef.current = null
      setRunId(null)
      finishRunTrace('failed', failedRunId)
      setIssue(setupIssue(error))
      return false
    } finally {
      if (sendAttempt === sendAttemptRef.current) setSending(false)
    }
  }, [beginRunTrace, finishRunTrace, persistVisibleTranscript, updateRunTrace])

  const send = useCallback(async (request: OpenClawSendRequest): Promise<boolean> => {
    if (runIdRef.current || sending) return false
    const displayText = request.displayText.trim()
    const gatewayPrompt = request.gatewayPrompt.trim()
    const attachments = (request.attachments ?? []).slice(0, 4)
    const selectedModel = models.find((model) => model.id === runtimeSelection.modelId)
    if (!gatewayPrompt || (!displayText && !attachments.length)) return false
    if (attachments.length && (!imageInputAvailable || selectedModel?.supportsImages !== true)) return false
    const idempotencyKey = crypto.randomUUID()
    const contextItems = request.contextItems.map((item) => {
      const sourceUrl = sanitizeOpenClawSourceUrl(item.sourceUrl)
      return { ...item, sourceUrl: sourceUrl || undefined }
    })
    const snapshot: OpenClawSendSnapshot = {
      displayText,
      gatewayPrompt,
      contextItems,
      ...(request.contextCount !== undefined ? { contextCount: request.contextCount } : {}),
      ...(request.sourceSnapshot ? { sourceSnapshot: request.sourceSnapshot } : {}),
      idempotencyKey,
      modelId: runtimeSelection.modelId,
      thinkingLevel: runtimeSelection.thinkingLevel,
      ...(attachments.length ? { attachments } : {}),
    }
    const message: OpenClawChatMessage = {
      id: idempotencyKey,
      role: 'user',
      text: displayText,
      status: 'pending',
      contextCount: snapshot.contextCount ?? snapshot.contextItems.length,
      contextSources: openClawSourceReferences(snapshot.contextItems),
      sendSnapshot: snapshot,
      createdAt: Date.now(),
      origin: 'local',
      clientTurnId: idempotencyKey,
      ...(attachments.length ? { images: attachments.map((attachment, index) => ({
        id: `${idempotencyKey}:image:${index}`,
        alt: `你发送的第 ${index + 1} 张图片`,
        mimeType: attachment.mimeType,
        width: attachment.width,
        height: attachment.height,
        url: attachment.previewUrl,
      })) } : {}),
    }
    message.mergeId = messageMergeId(message)
    persistVisibleTranscript((current) => [...current, message])
    return submitSend(snapshot, message.id)
  }, [imageInputAvailable, models, persistVisibleTranscript, runtimeSelection.modelId, runtimeSelection.thinkingLevel, sending, submitSend])

  const retry = useCallback(async (messageId: string): Promise<boolean> => {
    const message = messagesRef.current.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot || runIdRef.current || sending) return false
    persistVisibleTranscript((current) => current.map((candidate) => (
      candidate.id === messageId ? { ...candidate, status: 'pending' } : candidate
    )))
    if (message.sendSnapshot.modelId && message.sendSnapshot.modelId !== runtimeSelection.modelId) {
      const switched = await setModelRef.current(message.sendSnapshot.modelId)
      if (!switched) {
        persistVisibleTranscript((current) => current.map((candidate) => (
          candidate.id === messageId ? { ...candidate, status: 'failed' } : candidate
        )))
        return false
      }
    }
    return submitSend(message.sendSnapshot, messageId)
  }, [persistVisibleTranscript, runtimeSelection.modelId, sending, submitSend])

  const takeFailedMessage = useCallback((messageId: string): OpenClawSendRequest | null => {
    const message = messagesRef.current.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot) return null
    const request = {
      displayText: message.sendSnapshot.displayText,
      gatewayPrompt: message.sendSnapshot.gatewayPrompt,
      contextItems: message.sendSnapshot.contextItems.map((item) => ({ ...item })),
      ...(message.sendSnapshot.contextCount !== undefined ? { contextCount: message.sendSnapshot.contextCount } : {}),
      ...(message.sendSnapshot.sourceSnapshot ? { sourceSnapshot: message.sendSnapshot.sourceSnapshot } : {}),
    }
    persistVisibleTranscript((current) => current.filter((candidate) => candidate.id !== messageId))
    return request
  }, [persistVisibleTranscript])

  const refreshMedia = useCallback(async (messageId: string, imageId: string): Promise<void> => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    const message = messagesRef.current.find((candidate) => candidate.id === messageId)
    const image = message?.images?.find((candidate) => candidate.id === imageId)
    if (!client || !key || !message || !image?.reference) return
    await resolveMediaTickets(client, key, [{ ...message, images: [image] }], true)
  }, [resolveMediaTickets])

  const stop = useCallback(async () => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    if (!client || !key || stopping) return
    setStopping(true)
    updateRunTrace((current) => current ? { ...current, phase: 'stopping', status: 'running' } : current)
    setIssue(null)
    try {
      await client.request('chat.abort', { sessionKey: key, agentId: agentIdRef.current || undefined, runId: runIdRef.current || undefined })
    } catch (error) {
      setStopping(false)
      updateRunTrace((current) => current ? {
        ...current,
        phase: streamTextRef.current ? 'streaming' : 'waiting',
        status: 'running',
      } : current)
      setIssue(setupIssue(error))
    }
  }, [stopping, updateRunTrace])

  const activateSession = useCallback(async (
    client: OpenClawClientPort,
    key: string,
    agentId: string,
    projection: OpenClawRuntimeProjection,
    clearMessages: boolean,
    preserveThinking = false,
  ) => {
    const previousKey = sessionKeyRef.current
    const visibleMessages = messagesRef.current
    await vault.updateSession(options.userId, gatewayUrl, key)
    if (clearMessages) {
      if (previousKey) clearOpenClawTranscript(options.userId, gatewayUrl, previousKey)
      clearOpenClawTranscript(options.userId, gatewayUrl, key)
    } else {
      writeOpenClawTranscript(options.userId, gatewayUrl, key, visibleMessages)
    }
    sessionKeyRef.current = key
    transcriptReadyKeyRef.current = key
    setSessionKey(key)
    runIdRef.current = null
    pendingSendRef.current = false
    sendAttemptRef.current += 1
    terminalSendAttemptsRef.current.clear()
    agentEventSeqRef.current.clear()
    terminalRunIdsRef.current.clear()
    setRunId(null)
    updateRunTrace(null)
    streamTextRef.current = ''
    streamCreatedAtRef.current = null
    setStreamText('')
    setStreamCreatedAt(null)
    applyRuntime(clearMessages
      ? { ...projection, selection: { ...projection.selection, thinkingLevel: null } }
      : projection, preserveThinking)
    setModelSwitchFallback(null)
    setRuntimeIssue(null)
    void loadContextUsage(client, key)
    if (clearMessages) {
      replaceVisibleTranscript([])
      return
    }
    persistVisibleTranscript((current) => mergeOpenClawTranscript(
      readOpenClawTranscript(options.userId, gatewayUrl, key),
      current,
    ), key)
    try {
      await loadHistory(client, key, agentId)
    } catch {
      // A fork preserves the visible local history even if the first history refresh is delayed.
    }
  }, [applyRuntime, gatewayUrl, loadContextUsage, loadHistory, options.userId, persistVisibleTranscript, replaceVisibleTranscript, updateRunTrace, vault])

  const archiveFailedSession = useCallback(async (client: OpenClawClientPort, key: string, agentId: string) => {
    try {
      await client.request('sessions.patch', { key, agentId, archived: true })
    } catch {
      // Best-effort cleanup must never replace the original working conversation.
    }
  }, [])

  const setModel = useCallback(async (modelId: string | null): Promise<boolean> => {
    const client = clientRef.current
    const parentSessionKey = sessionKeyRef.current
    const agentId = agentIdRef.current
    const targetModelId = modelId ?? runtimeSelection.defaultModelId
    const selected = models.find((model) => model.id === targetModelId)
    if (!client || !parentSessionKey || !agentId || !selected || runIdRef.current || sending || runtimeUpdating) return false
    if (runtimeSelection.modelId === selected.id) return true
    setRuntimeUpdating(true)
    setRuntimeIssue(null)
    setModelSwitchFallback(null)
    let createdKey: string | null = null
    try {
      const created = await createOpenClawSession(client, {
        agentId,
        parentSessionKey,
        fork: true,
        model: selected.id,
      })
      createdKey = stringOf(created.key)
      if (!createdKey) throw new Error('OpenClaw 没有返回新对话标识。')
      const projection = await readRuntime(client, createdKey, agentId)
      if (projection.invalidSessionModel || projection.selection.modelId !== selected.id) {
        throw new Error('OpenClaw 返回的实际模型与选择不一致。')
      }
      await activateSession(client, createdKey, agentId, projection, false, true)
      return true
    } catch (error) {
      if (createdKey) await archiveFailedSession(client, createdKey, agentId)
      setRuntimeIssue(`${runtimeFailureMessage(error, 'switch')} 可新建空白对话并切换到 ${selected.name}。`)
      setModelSwitchFallback({ modelId: selected.id, modelName: selected.name })
      return false
    } finally {
      setRuntimeUpdating(false)
    }
  }, [activateSession, archiveFailedSession, models, readRuntime, runtimeSelection.defaultModelId, runtimeSelection.modelId, runtimeUpdating, sending])

  useEffect(() => {
    setModelRef.current = setModel
  }, [setModel])

  const setThinking = useCallback(async (thinkingLevel: string | null): Promise<boolean> => {
    const currentModel = models.find((model) => model.id === runtimeSelection.modelId)
    if (!clientRef.current || !sessionKeyRef.current || !agentIdRef.current || runIdRef.current || sending || runtimeUpdating) return false
    if (currentModel?.reasoning === false && thinkingLevel !== null) return false
    if (thinkingLevel !== null && !thinkingOptions.some((option) => option.id === thinkingLevel)) return false
    thinkingLevelRef.current = thinkingLevel
    setRuntimeSelection((current) => ({ ...current, thinkingLevel }))
    setRuntimeIssue(null)
    return true
  }, [models, runtimeSelection.modelId, runtimeUpdating, sending, thinkingOptions])

  const switchToBlankConversation = useCallback(async (): Promise<boolean> => {
    const client = clientRef.current
    const agentId = agentIdRef.current
    const fallback = modelSwitchFallback
    if (!client || !agentId || !fallback || runIdRef.current || sending || runtimeUpdating) return false
    setRuntimeUpdating(true)
    setRuntimeIssue(null)
    let createdKey: string | null = null
    try {
      const created = await createOpenClawSession(client, {
        agentId,
        model: fallback.modelId,
      })
      createdKey = stringOf(created.key)
      if (!createdKey) throw new Error('OpenClaw 没有返回新对话标识。')
      const projection = await readRuntime(client, createdKey, agentId)
      if (projection.invalidSessionModel || projection.selection.modelId !== fallback.modelId) {
        throw new Error('OpenClaw 返回的实际模型与选择不一致。')
      }
      await activateSession(client, createdKey, agentId, projection, true)
      return true
    } catch (error) {
      if (createdKey) await archiveFailedSession(client, createdKey, agentId)
      setRuntimeIssue(`${runtimeFailureMessage(error, 'switch')} 原对话仍然可用。`)
      return false
    } finally {
      setRuntimeUpdating(false)
    }
  }, [activateSession, archiveFailedSession, modelSwitchFallback, readRuntime, runtimeUpdating, sending])

  const newConversation = useCallback(async (): Promise<boolean> => {
    const client = clientRef.current
    const agentId = agentIdRef.current
    if (!client || !agentId || runIdRef.current || sending || runtimeUpdating) return false
    setRuntimeUpdating(true)
    setRuntimeIssue(null)
    try {
      const created = await createOpenClawSession(client, { agentId })
      const createdKey = stringOf(created.key)
      if (!createdKey) throw new Error('OpenClaw 没有返回新对话标识。')
      const projection = await readRuntime(client, createdKey, agentId)
      await activateSession(client, createdKey, agentId, projection, true)
      return true
    } catch (error) {
      setRuntimeIssue(runtimeFailureMessage(error, 'switch'))
      return false
    } finally {
      setRuntimeUpdating(false)
    }
  }, [activateSession, readRuntime, runtimeUpdating, sending])

  const clearTranscript = useCallback(() => {
    clearOpenClawTranscript(options.userId, gatewayUrl)
    transcriptReadyKeyRef.current = null
    messagesRef.current = []
    setMessages([])
  }, [gatewayUrl, options.userId])

  const forget = useCallback(async () => {
    await forgetOpenClawBrowser({
      userId: options.userId,
      gatewayUrl,
      vault,
      clearTranscripts: clearOpenClawTranscript,
      clientFactory: options.clientFactory,
    })
    clearTranscript()
    disconnect()
  }, [clearTranscript, disconnect, gatewayUrl, options.clientFactory, options.userId, vault])

  const effectiveStatus: OpenClawConnectionStatus = !options.enabled
    ? 'disabled'
    : status === 'disabled' ? 'idle' : status

  useEffect(() => {
    automaticConnectKeyRef.current = null
    gatewayUrlRef.current = gatewayUrl
  }, [gatewayUrl])

  useEffect(() => {
    return disconnect
  }, [disconnect, options.defaultGatewayUrl, options.enabled, options.userId])

  useEffect(() => {
    if (!options.enabled || effectiveStatus !== 'idle') return
    const key = `${options.userId}\n${gatewayUrl}`
    if (automaticConnectKeyRef.current === key) return
    automaticConnectKeyRef.current = key
    let active = true
    void vault.load(options.userId, gatewayUrl).then((stored) => {
      if (active && stored) void connectInternal(undefined, false, gatewayUrl)
    }).catch(() => undefined)
    return () => { active = false }
  }, [connectInternal, effectiveStatus, gatewayUrl, options.enabled, options.userId, vault])

  return {
    gatewayUrl,
    setGatewayUrl,
    status: effectiveStatus,
    toolsStatus,
    messages,
    streamText,
    streamCreatedAt,
    runTrace,
    issue,
    runtimeIssue,
    modelSwitchFallback,
    contextUsage,
    imageInputAvailable,
    currentModelSupportsImages: models.find((model) => model.id === runtimeSelection.modelId)?.supportsImages === true,
    sessionKey,
    isRunning: sending || Boolean(runId),
    isStopping: stopping,
    reconnectAttempt,
    runtimeLoading,
    runtimeUpdating,
    models,
    thinkingOptions,
    runtimeSelection,
    connect: (authInput?: string, requestedUrl?: string) => connectInternal(authInput, false, requestedUrl),
    retryConnection,
    disconnect,
    clearTranscript,
    forget,
    send,
    retry,
    takeFailedMessage,
    refreshMedia,
    stop,
    setModel,
    setThinking,
    switchToBlankConversation,
    newConversation,
  }
}
