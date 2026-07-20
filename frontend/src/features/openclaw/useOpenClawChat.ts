import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { AgentModelPreference } from '../workbench-live/agentContext'
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
    const text = messageText(record).trim()
    if (!text) return []
    const id = (record as { id?: unknown }).id
    return [{ id: typeof id === 'string' ? id : `history-${index}`, role, text } satisfies OpenClawChatMessage]
  }))
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
  const [issue, setIssue] = useState<OpenClawSetupIssue | null>(null)
  const [sessionKey, setSessionKey] = useState<string | null>(null)
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

  const handleGatewayEvent = useCallback((event: GatewayEvent) => {
    if (event.event !== 'chat' || !event.payload || typeof event.payload !== 'object') return
    const payload = event.payload as ChatEventPayload
    if (!payload.sessionKey || payload.sessionKey !== sessionKeyRef.current) return
    if (runIdRef.current && payload.runId && payload.runId !== runIdRef.current) return
    if (!runIdRef.current && payload.runId) {
      runIdRef.current = payload.runId
      setRunId(payload.runId)
    }
    if (payload.state === 'delta' && typeof payload.deltaText === 'string') {
      setStreamText((current) => (
        payload.replace ? payload.deltaText! : `${current}${payload.deltaText}`
      ).slice(0, MAX_HISTORY_CHARS))
      return
    }
    if (payload.state === 'error') setIssue({ kind: 'unknown', message: payload.errorMessage || 'OpenClaw 对话失败。' })
    if (payload.state === 'final' || payload.state === 'aborted' || payload.state === 'error') {
      runIdRef.current = null
      setRunId(null)
      setStreamText('')
      const client = clientRef.current
      const key = sessionKeyRef.current
      const agentId = agentIdRef.current
      if (client && key && agentId) void loadHistory(client, key, agentId).catch(() => undefined)
    }
  }, [loadHistory])

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
    setRunId(null)
    setSending(false)
    setSessionKey(null)
    setStreamText('')
    setMessages([])
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
  }, [handleGatewayEvent, loadHistory, options.clientFactory, options.enabled, options.userId, setGatewayUrl, vault])

  useEffect(() => {
    reconnectRef.current = (reconnecting = true) => { void connectInternal(undefined, reconnecting) }
  }, [connectInternal])

  const send = useCallback(async (message: string, preference: AgentModelPreference): Promise<void> => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    const agentId = agentIdRef.current
    const text = message.trim()
    if (!client || !key || !agentId || !text || runIdRef.current) return
    const idempotencyKey = crypto.randomUUID()
    setMessages((current) => boundChatMessages([...current, { id: idempotencyKey, role: 'user' as const, text }]))
    setStreamText('')
    setIssue(null)
    setSending(true)
    try {
      const result = await client.request<{ runId?: string }>('chat.send', {
        sessionKey: key,
        agentId,
        message: text,
        ...(preference === 'auto' ? {} : { thinking: preference === 'fast' ? 'low' : 'high' }),
        deliver: false,
        idempotencyKey,
      })
      runIdRef.current = result.runId || idempotencyKey
      setRunId(runIdRef.current)
    } catch (error) {
      setIssue(setupIssue(error))
      await loadHistory(client, key, agentId).catch(() => undefined)
    } finally {
      setSending(false)
    }
  }, [loadHistory])

  const stop = useCallback(async () => {
    const client = clientRef.current
    const key = sessionKeyRef.current
    if (!client || !key) return
    await client.request('chat.abort', { sessionKey: key, agentId: agentIdRef.current || undefined, runId: runIdRef.current || undefined })
  }, [])

  const newConversation = useCallback(async () => {
    const client = clientRef.current
    const agentId = agentIdRef.current
    if (!client || !agentId) return
    const created = await client.request<{ key?: string }>('sessions.create', { agentId, label: 'Inteliscope' })
    if (!created.key) return
    sessionKeyRef.current = created.key
    setSessionKey(created.key)
    runIdRef.current = null
    setRunId(null)
    setMessages([])
    setStreamText('')
    await vault.updateSession(options.userId, gatewayUrl, created.key)
  }, [gatewayUrl, options.userId, vault])

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
    sessionKey,
    isRunning: sending || Boolean(runId),
    connect: (authInput?: string, requestedUrl?: string) => connectInternal(authInput, false, requestedUrl),
    disconnect,
    forget,
    send,
    stop,
    newConversation,
  }
}
