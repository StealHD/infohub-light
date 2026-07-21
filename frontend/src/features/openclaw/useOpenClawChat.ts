import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  projectAgentHandoffDisplay,
  type AgentContextItem,
} from '../workbench-live/agentContext'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import {
  GatewayRequestError,
  OpenClawGatewayClient,
  generateDeviceIdentity,
  parseOpenClawConnectionInput,
  validateGatewayUrl,
  type GatewayEvent,
  type GatewayHello,
} from './openclawGateway'

export type OpenClawConnectionStatus = 'disabled' | 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'
export type OpenClawToolsStatus = 'unknown' | 'available' | 'missing'

export type OpenClawChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  status?: 'pending' | 'sent' | 'failed' | 'aborted'
  contextCount?: number
  sendSnapshot?: OpenClawSendSnapshot
}

export type OpenClawSendRequest = {
  displayText: string
  gatewayPrompt: string
  contextItems: AgentContextItem[]
}

export type OpenClawSendSnapshot = OpenClawSendRequest & {
  idempotencyKey: string
  modelId: string | null
  thinkingLevel: string | null
}

export type OpenClawModelOption = {
  id: string
  name: string
  provider: string
  alias?: string
  contextWindow?: number
  reasoning?: boolean
  thinkingLevels?: OpenClawThinkingOption[]
  thinkingDefault?: string
}

export type OpenClawThinkingOption = {
  id: string
  label: string
}

export type OpenClawRuntimeSelection = {
  modelId: string | null
  thinkingLevel: string | null
  defaultModelId: string | null
  defaultThinkingLevel: string | null
}

export type OpenClawModelSwitchFallback = {
  modelId: string
  modelName: string
}

export type OpenClawSetupIssue = {
  kind: 'origin' | 'pairing' | 'auth' | 'protocol' | 'permission' | 'network' | 'unknown'
  message: string
  requestId?: string
}

type ChatEventPayload = {
  state?: 'delta' | 'final' | 'aborted' | 'error'
  sessionKey?: string
  runId?: string
  deltaText?: string
  replace?: boolean
  errorMessage?: string
}

type OpenClawChatOptions = {
  enabled: boolean
  userId: string
  defaultGatewayUrl: string
  vault?: OpenClawCredentialVault
  clientFactory?: (options: ConstructorParameters<typeof OpenClawGatewayClient>[0]) => OpenClawGatewayClient
}

export const OPENCLAW_GATEWAY_URL_KEY_PREFIX = 'inteliscope.openclaw.gateway.v1:'
const MAX_MESSAGES = 100
const MAX_HISTORY_CHARS = 100_000

export function boundChatMessages(messages: OpenClawChatMessage[]): OpenClawChatMessage[] {
  const newest = messages.slice(-MAX_MESSAGES)
  const bounded: OpenClawChatMessage[] = []
  let remaining = MAX_HISTORY_CHARS
  for (let index = newest.length - 1; index >= 0 && remaining > 0; index -= 1) {
    const message = newest[index]
    const text = message.text.slice(0, remaining)
    if (!text) continue
    bounded.unshift({ ...message, text })
    remaining -= text.length
  }
  return bounded
}

export function readSavedGatewayUrl(userId: string, fallback: string): string {
  try {
    return validateGatewayUrl(window.localStorage.getItem(`${OPENCLAW_GATEWAY_URL_KEY_PREFIX}${userId}`) || fallback)
  } catch {
    return validateGatewayUrl(fallback)
  }
}

export function saveGatewayUrl(userId: string, value: string): void {
  try { window.localStorage.setItem(`${OPENCLAW_GATEWAY_URL_KEY_PREFIX}${userId}`, value) } catch { /* URL persistence is best-effort. */ }
}

function messageText(value: unknown): string {
  if (!value || typeof value !== 'object') return ''
  const message = value as { text?: unknown; content?: unknown }
  if (typeof message.text === 'string') return message.text
  if (!Array.isArray(message.content)) return ''
  return message.content.flatMap((part) => {
    if (!part || typeof part !== 'object') return []
    const text = (part as { text?: unknown }).text
    return typeof text === 'string' ? [text] : []
  }).join('\n')
}

export function projectChatHistory(value: unknown): OpenClawChatMessage[] {
  const records = value && typeof value === 'object' && Array.isArray((value as { messages?: unknown }).messages)
    ? (value as { messages: unknown[] }).messages
    : []
  return boundChatMessages(records.flatMap((record, index) => {
    if (!record || typeof record !== 'object') return []
    const role = (record as { role?: unknown }).role
    if (role !== 'user' && role !== 'assistant') return []
    const rawText = messageText(record).trim()
    if (!rawText) return []
    const handoff = role === 'user' ? projectAgentHandoffDisplay(rawText) : null
    const text = handoff?.displayText ?? rawText
    const id = (record as { id?: unknown }).id
    return [{
      id: typeof id === 'string' ? id : `history-${index}`,
      role,
      text,
      status: 'sent',
      ...(handoff ? { contextCount: handoff.contextCount } : {}),
    } satisfies OpenClawChatMessage]
  }))
}

function recordOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function stringOf(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function normalizeModels(value: unknown): OpenClawModelOption[] {
  const root = recordOf(value)
  const entries = Array.isArray(root?.models) ? root.models : []
  const seen = new Set<string>()
  return entries.flatMap((entry) => {
    const model = recordOf(entry)
    if (!model) return []
    const id = stringOf(model.id)
    const name = stringOf(model.name)
    const provider = stringOf(model.provider)
    if (!id || !name || !provider || model.available === false || seen.has(id)) return []
    seen.add(id)
    const contextWindow = typeof model.contextWindow === 'number' && Number.isFinite(model.contextWindow)
      ? Math.max(1, Math.floor(model.contextWindow))
      : undefined
    const thinkingLevels = normalizeThinkingOptions(model.thinkingLevels)
    const thinkingDefault = stringOf(model.thinkingDefault)
    return [{
      id,
      name,
      provider,
      ...(stringOf(model.alias) ? { alias: stringOf(model.alias)! } : {}),
      ...(contextWindow ? { contextWindow } : {}),
      ...(typeof model.reasoning === 'boolean' ? { reasoning: model.reasoning } : {}),
      ...(thinkingLevels.length ? { thinkingLevels } : {}),
      ...(thinkingDefault && thinkingLevels.some((option) => option.id === thinkingDefault) ? { thinkingDefault } : {}),
    }]
  })
}

function matchingModelId(models: OpenClawModelOption[], provider: unknown, model: unknown): string | null {
  const modelName = stringOf(model)
  const providerName = stringOf(provider)
  if (!modelName) return null
  const full = providerName ? `${providerName}/${modelName}` : modelName
  return models.find((candidate) => candidate.id === full)?.id
    ?? models.find((candidate) => candidate.id === modelName)?.id
    ?? null
}

function normalizeThinkingOptions(value: unknown): OpenClawThinkingOption[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value.flatMap((entry) => {
    const option = recordOf(entry)
    const id = stringOf(option?.id)
    const label = stringOf(option?.label)
    if (!id || !label || seen.has(id)) return []
    seen.add(id)
    return [{ id, label }]
  })
}

type RuntimeProjection = {
  models: OpenClawModelOption[]
  thinkingOptions: OpenClawThinkingOption[]
  selection: OpenClawRuntimeSelection
  invalidSessionModel: boolean
}

function projectRuntime(modelsValue: unknown, agentsValue: unknown, sessionValue: unknown, requestedAgentId: string): RuntimeProjection {
  const models = normalizeModels(modelsValue)
  const agentsRoot = recordOf(agentsValue)
  const agents = Array.isArray(agentsRoot?.agents) ? agentsRoot.agents : []
  const defaultAgentId = stringOf(agentsRoot?.defaultId)
  const agent = agents.map(recordOf).find((candidate) => (
    stringOf(candidate?.id) === requestedAgentId
    || (!agents.some((entry) => stringOf(recordOf(entry)?.id) === requestedAgentId) && stringOf(candidate?.id) === defaultAgentId)
  )) ?? null
  const agentModel = recordOf(agent?.model)
  const defaultModelId = stringOf(agentModel?.primary)
  const sessionRoot = recordOf(sessionValue)
  const session = recordOf(sessionRoot?.session) ?? sessionRoot
  const sessionThinkingOptions = normalizeThinkingOptions(session?.thinkingLevels)
  const matchedSessionModelId = matchingModelId(models, session?.modelProvider, session?.model)
  const hasExplicitSessionModel = Boolean(stringOf(session?.model))
  const defaultModelIsAvailable = Boolean(defaultModelId && models.some((candidate) => candidate.id === defaultModelId))
  const modelId = matchedSessionModelId ?? (!hasExplicitSessionModel && defaultModelIsAvailable ? defaultModelId : null)
  const selectedModel = models.find((candidate) => candidate.id === modelId)
  const modelThinkingOptions = selectedModel?.thinkingLevels ?? []
  const thinkingOptions = selectedModel?.reasoning === false
    ? []
    : modelThinkingOptions.length
      ? modelThinkingOptions
      : sessionThinkingOptions.length
        ? sessionThinkingOptions
        : normalizeThinkingOptions(agent?.thinkingLevels)
  const rawDefaultThinkingLevel = selectedModel?.thinkingDefault ?? stringOf(session?.thinkingDefault) ?? stringOf(agent?.thinkingDefault)
  const defaultThinkingLevel = rawDefaultThinkingLevel && thinkingOptions.some((option) => option.id === rawDefaultThinkingLevel)
    ? rawDefaultThinkingLevel
    : null
  const sessionThinking = stringOf(session?.thinkingLevel)
  return {
    models,
    thinkingOptions,
    selection: {
      modelId,
      thinkingLevel: sessionThinking && thinkingOptions.some((option) => option.id === sessionThinking)
        ? sessionThinking
        : null,
      defaultModelId: defaultModelIsAvailable ? defaultModelId : null,
      defaultThinkingLevel,
    },
    invalidSessionModel: Boolean(hasExplicitSessionModel && !matchedSessionModelId),
  }
}

function runtimeFailureMessage(error: unknown, action: 'load' | 'switch'): string {
  const raw = error instanceof Error ? error.message : String(error)
  const fingerprint = raw.toLowerCase()
  if (fingerprint.includes('scope') || fingerprint.includes('operator.admin') || fingerprint.includes('permission')) {
    return action === 'switch'
      ? '当前连接权限不能直接修改旧会话，原对话已保留。'
      : '当前连接权限不足，无法读取 OpenClaw 运行设置。'
  }
  if (fingerprint.includes('context') || fingerprint.includes('too long') || fingerprint.includes('fork')) {
    return '当前对话过长，无法在保留上下文的同时切换模型。'
  }
  return action === 'switch'
    ? '未能切换模型，原对话已保留。'
    : '无法读取 OpenClaw 模型设置。'
}

function setupIssue(error: unknown): OpenClawSetupIssue {
  const code = error instanceof GatewayRequestError ? error.code : ''
  const message = error instanceof Error ? error.message : String(error)
  const details = error instanceof GatewayRequestError && error.details && typeof error.details === 'object'
    ? error.details as Record<string, unknown>
    : {}
  const requestId = typeof details.requestId === 'string' ? details.requestId : undefined
  const fingerprint = `${code} ${message}`.toLowerCase()
  if (fingerprint.includes('pairing_required') || fingerprint.includes('pairing required')) return { kind: 'pairing', message: '这个浏览器需要在 OpenClaw 中批准设备配对。', requestId }
  if (fingerprint.includes('origin')) return { kind: 'origin', message: 'OpenClaw 尚未允许当前 Inteliscope 页面来源。' }
  if (fingerprint.includes('protocol')) return { kind: 'protocol', message: 'OpenClaw Gateway 协议版本不兼容，请升级到 2026.7.1 或更高兼容版本。' }
  if (fingerprint.includes('scope') || fingerprint.includes('permission') || fingerprint.includes('权限')) return { kind: 'permission', message: 'OpenClaw 返回的浏览器权限不符合最小权限要求。' }
  if (fingerprint.includes('auth') || fingerprint.includes('token') || fingerprint.includes('unauthorized')) return { kind: 'auth', message: 'OpenClaw Gateway token 无效或已轮换。' }
  if (fingerprint.includes('websocket') || fingerprint.includes('network') || fingerprint.includes('连接')) return { kind: 'network', message: '无法连接 OpenClaw Gateway；浏览器可能还在等待本地网络权限。' }
  return { kind: 'unknown', message: message || 'OpenClaw 连接失败。' }
}

function hasInteliscopeTools(value: unknown): boolean {
  try {
    if (JSON.stringify(value).toLowerCase().includes('inteliscope')) return true
  } catch {
    return false
  }
  const groups = value && typeof value === 'object' && Array.isArray((value as { groups?: unknown }).groups)
    ? (value as { groups: unknown[] }).groups
    : []
  return groups.some((group) => {
    if (!group || typeof group !== 'object' || !Array.isArray((group as { tools?: unknown }).tools)) return false
    return (group as { tools: unknown[] }).tools.some((tool) => {
      if (!tool || typeof tool !== 'object') return false
      const entry = tool as { id?: unknown; label?: unknown; source?: unknown }
      return entry.source === 'mcp' && `${String(entry.id || '')} ${String(entry.label || '')}`.toLowerCase().includes('inteliscope')
    })
  })
}

export function useOpenClawChat(options: OpenClawChatOptions) {
  const vault = useMemo(() => options.vault ?? new OpenClawCredentialVault(), [options.vault])
  const configurationKey = `${options.userId}\n${options.defaultGatewayUrl}`
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
  const [runId, setRunId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [stopping, setStopping] = useState(false)
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
  const clientRef = useRef<OpenClawGatewayClient | null>(null)
  const agentIdRef = useRef<string | null>(null)
  const sessionKeyRef = useRef<string | null>(null)
  const runIdRef = useRef<string | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const reconnectDelayRef = useRef(1000)
  const generationRef = useRef(0)
  const manualCloseRef = useRef(false)
  const automaticConnectKeyRef = useRef<string | null>(null)
  const reconnectRef = useRef<(reconnecting?: boolean) => void>(() => undefined)
  const streamTextRef = useRef('')
  const messagesRef = useRef<OpenClawChatMessage[]>([])
  const terminalRunIdsRef = useRef(new Set<string>())
  const thinkingLevelRef = useRef<string | null>(null)
  const setModelRef = useRef<(modelId: string | null) => Promise<boolean>>(async () => false)

  const setGatewayUrl = useCallback((value: string) => {
    const normalized = validateGatewayUrl(value)
    gatewayUrlRef.current = normalized
    setGatewayState({ configurationKey, value: normalized })
    saveGatewayUrl(options.userId, normalized)
  }, [configurationKey, options.userId])

  const loadHistory = useCallback(async (client: OpenClawGatewayClient, key: string, agentId: string) => {
    const history = await client.request('chat.history', { sessionKey: key, agentId, limit: MAX_MESSAGES, maxChars: MAX_HISTORY_CHARS })
    setMessages(projectChatHistory(history))
  }, [])

  const readRuntime = useCallback(async (client: OpenClawGatewayClient, key: string, agentId: string) => {
    const [modelsValue, agentsValue, sessionValue] = await Promise.all([
      client.request('models.list', { view: 'configured' }),
      client.request('agents.list', {}),
      client.request('sessions.describe', { key }),
    ])
    return projectRuntime(modelsValue, agentsValue, sessionValue, agentId)
  }, [])

  const applyRuntime = useCallback((projection: RuntimeProjection, preserveThinking = false) => {
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
    client: OpenClawGatewayClient,
    key: string,
    agentId: string,
    preserveThinking = false,
  ): Promise<RuntimeProjection | null> => {
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

  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { streamTextRef.current = streamText }, [streamText])

  const handleGatewayEvent = useCallback((event: GatewayEvent) => {
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
      setStreamText((current) => {
        const next = (payload.replace ? payload.deltaText! : `${current}${payload.deltaText}`).slice(0, MAX_HISTORY_CHARS)
        streamTextRef.current = next
        return next
      })
      return
    }
    if (payload.state === 'error') setIssue({ kind: 'unknown', message: payload.errorMessage || 'OpenClaw 对话失败。' })
    if (payload.state === 'final' || payload.state === 'aborted' || payload.state === 'error') {
      const partialText = streamTextRef.current.trim()
      const completedRunId = payload.runId || runIdRef.current || crypto.randomUUID()
      terminalRunIdsRef.current.add(completedRunId)
      if (terminalRunIdsRef.current.size > 20) terminalRunIdsRef.current.delete(terminalRunIdsRef.current.values().next().value!)
      runIdRef.current = null
      setRunId(null)
      setSending(false)
      setStopping(false)
      streamTextRef.current = ''
      setStreamText('')
      const client = clientRef.current
      const key = sessionKeyRef.current
      const agentId = agentIdRef.current
      if (client && key && agentId) void loadRuntime(client, key, agentId, true)
      if ((payload.state === 'aborted' || payload.state === 'error') && partialText) {
        setMessages((current) => boundChatMessages([...current, {
          id: `${payload.state}-${completedRunId}`,
          role: 'assistant',
          text: partialText,
          status: payload.state === 'aborted' ? 'aborted' : 'failed',
        }]))
        return
      }
      if (payload.state === 'aborted') return
      if (client && key && agentId) void loadHistory(client, key, agentId).catch(() => undefined)
    }
  }, [loadHistory, loadRuntime])

  const disconnect = useCallback(() => {
    manualCloseRef.current = true
    generationRef.current += 1
    if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current)
    reconnectTimerRef.current = null
    clientRef.current?.close()
    clientRef.current = null
    agentIdRef.current = null
    sessionKeyRef.current = null
    runIdRef.current = null
    terminalRunIdsRef.current.clear()
    setRunId(null)
    setSending(false)
    setStopping(false)
    setSessionKey(null)
    setStreamText('')
    setMessages([])
    setModels([])
    setThinkingOptions([])
    setRuntimeSelection({ modelId: null, thinkingLevel: null, defaultModelId: null, defaultThinkingLevel: null })
    setRuntimeLoading(false)
    setRuntimeUpdating(false)
    setRuntimeIssue(null)
    setModelSwitchFallback(null)
    thinkingLevelRef.current = null
    setToolsStatus('unknown')
    setStatus(options.enabled ? 'idle' : 'disabled')
  }, [options.enabled])

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
        platform: navigator.platform || 'web',
        deviceFamily: 'browser',
        onEvent: handleGatewayEvent,
        onClose: () => {
          if (manualCloseRef.current || generation !== generationRef.current) return
          setStatus('reconnecting')
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
      const agentId = hello.snapshot?.sessionDefaults?.defaultAgentId
      if (!agentId) throw new Error('OpenClaw Gateway 没有返回默认 Agent。')
      agentIdRef.current = agentId
      let key = stored?.sessionKey
      if (!key) {
        const created = await client.request<{ key?: string }>('sessions.create', { agentId, label: 'Inteliscope' })
        key = created.key
      }
      if (!key) throw new Error('OpenClaw 无法创建 Inteliscope 对话。')
      sessionKeyRef.current = key
      setSessionKey(key)
      const deviceToken = hello.auth?.deviceToken || stored?.deviceToken
      if (!deviceToken) throw new Error('OpenClaw 没有返回浏览器设备 token。')
      await vault.save(options.userId, parsed.gatewayUrl, {
        identity,
        deviceToken,
        scopes: hello.auth?.scopes ?? stored?.scopes ?? [],
        sessionKey: key,
      })
      const [tools] = await Promise.all([
        client.request('tools.effective', { sessionKey: key, agentId }),
        loadHistory(client, key, agentId),
        loadRuntime(client, key, agentId),
      ])
      setToolsStatus(hasInteliscopeTools(tools) ? 'available' : 'missing')
      reconnectDelayRef.current = 1000
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
  }, [handleGatewayEvent, loadHistory, loadRuntime, options.clientFactory, options.enabled, options.userId, setGatewayUrl, vault])

  useEffect(() => {
    reconnectRef.current = (reconnecting = true) => { void connectInternal(undefined, reconnecting) }
  }, [connectInternal])

  const submitSend = useCallback(async (snapshot: OpenClawSendSnapshot, messageId: string): Promise<boolean> => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    const agentId = agentIdRef.current
    if (!client || !key || !agentId || !snapshot.gatewayPrompt.trim() || runIdRef.current) return false
    setStreamText('')
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
      })
      setMessages((current) => current.map((message) => (
        message.id === messageId ? { ...message, status: 'sent' } : message
      )))
      runIdRef.current = result.runId || snapshot.idempotencyKey
      setRunId(runIdRef.current)
      return true
    } catch (error) {
      setIssue(setupIssue(error))
      setMessages((current) => current.map((message) => (
        message.id === messageId ? { ...message, status: 'failed' } : message
      )))
      return false
    } finally {
      setSending(false)
    }
  }, [])

  const send = useCallback(async (request: OpenClawSendRequest): Promise<boolean> => {
    if (runIdRef.current || sending) return false
    const displayText = request.displayText.trim()
    const gatewayPrompt = request.gatewayPrompt.trim()
    if (!displayText || !gatewayPrompt) return false
    const idempotencyKey = crypto.randomUUID()
    const snapshot: OpenClawSendSnapshot = {
      displayText,
      gatewayPrompt,
      contextItems: request.contextItems.map((item) => ({ ...item })),
      idempotencyKey,
      modelId: runtimeSelection.modelId,
      thinkingLevel: runtimeSelection.thinkingLevel,
    }
    const message: OpenClawChatMessage = {
      id: idempotencyKey,
      role: 'user',
      text: displayText,
      status: 'pending',
      contextCount: snapshot.contextItems.length,
      sendSnapshot: snapshot,
    }
    setMessages((current) => boundChatMessages([...current, message]))
    return submitSend(snapshot, message.id)
  }, [runtimeSelection.modelId, runtimeSelection.thinkingLevel, sending, submitSend])

  const retry = useCallback(async (messageId: string): Promise<boolean> => {
    const message = messagesRef.current.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot || runIdRef.current || sending) return false
    setMessages((current) => current.map((candidate) => (
      candidate.id === messageId ? { ...candidate, status: 'pending' } : candidate
    )))
    if (message.sendSnapshot.modelId && message.sendSnapshot.modelId !== runtimeSelection.modelId) {
      const switched = await setModelRef.current(message.sendSnapshot.modelId)
      if (!switched) {
        setMessages((current) => current.map((candidate) => (
          candidate.id === messageId ? { ...candidate, status: 'failed' } : candidate
        )))
        return false
      }
    }
    return submitSend(message.sendSnapshot, messageId)
  }, [runtimeSelection.modelId, sending, submitSend])

  const takeFailedMessage = useCallback((messageId: string): OpenClawSendRequest | null => {
    const message = messagesRef.current.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot) return null
    const request = {
      displayText: message.sendSnapshot.displayText,
      gatewayPrompt: message.sendSnapshot.gatewayPrompt,
      contextItems: message.sendSnapshot.contextItems.map((item) => ({ ...item })),
    }
    setMessages((current) => current.filter((candidate) => candidate.id !== messageId))
    return request
  }, [])

  const stop = useCallback(async () => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    if (!client || !key || stopping) return
    setStopping(true)
    setIssue(null)
    try {
      await client.request('chat.abort', { sessionKey: key, agentId: agentIdRef.current || undefined, runId: runIdRef.current || undefined })
    } catch (error) {
      setStopping(false)
      setIssue(setupIssue(error))
    }
  }, [stopping])

  const activateSession = useCallback(async (
    client: OpenClawGatewayClient,
    key: string,
    agentId: string,
    projection: RuntimeProjection,
    clearMessages: boolean,
  ) => {
    await vault.updateSession(options.userId, gatewayUrl, key)
    sessionKeyRef.current = key
    setSessionKey(key)
    runIdRef.current = null
    terminalRunIdsRef.current.clear()
    setRunId(null)
    streamTextRef.current = ''
    setStreamText('')
    applyRuntime(projection)
    setModelSwitchFallback(null)
    setRuntimeIssue(null)
    if (clearMessages) {
      setMessages([])
      return
    }
    try {
      await loadHistory(client, key, agentId)
    } catch {
      // A fork preserves the visible local history even if the first history refresh is delayed.
    }
  }, [applyRuntime, gatewayUrl, loadHistory, options.userId, vault])

  const archiveFailedSession = useCallback(async (client: OpenClawGatewayClient, key: string, agentId: string) => {
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
      const created = await client.request<{ key?: string }>('sessions.create', {
        agentId,
        label: 'Inteliscope',
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
      await activateSession(client, createdKey, agentId, projection, false)
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
      const created = await client.request<{ key?: string }>('sessions.create', {
        agentId,
        label: 'Inteliscope',
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
      const created = await client.request<{ key?: string }>('sessions.create', { agentId, label: 'Inteliscope' })
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

  const forget = useCallback(async () => {
    disconnect()
    await vault.forget(options.userId, gatewayUrl)
  }, [disconnect, gatewayUrl, options.userId, vault])

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
    issue,
    runtimeIssue,
    modelSwitchFallback,
    sessionKey,
    isRunning: sending || Boolean(runId),
    isStopping: stopping,
    runtimeLoading,
    runtimeUpdating,
    models,
    thinkingOptions,
    runtimeSelection,
    connect: (authInput?: string, requestedUrl?: string) => connectInternal(authInput, false, requestedUrl),
    disconnect,
    forget,
    send,
    retry,
    takeFailedMessage,
    stop,
    setModel,
    setThinking,
    switchToBlankConversation,
    newConversation,
  }
}
