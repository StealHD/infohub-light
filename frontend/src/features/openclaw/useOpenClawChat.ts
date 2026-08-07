import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  agentSourceReferences,
  projectAgentHandoffDisplay,
  sanitizeAgentSourceReferences,
  sanitizeSourceUrl,
  type AgentContextItem,
  type AgentSourceReference,
} from '../workbench-live/agentContext'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import { forgetOpenClawBrowser } from './openclawDevice'
import {
  OPENCLAW_CURRENT_SCOPES,
  GatewayRequestError,
  OpenClawGatewayClient,
  generateDeviceIdentity,
  gatewaySupportsMethod,
  parseOpenClawConnectionInput,
  validateGatewayUrl,
  type GatewayEvent,
  type GatewayHello,
} from './openclawGateway'
import {
  isSafeOpenClawImageDataUrl,
  parseOpenClawMediaTicket,
  releaseOpenClawImageUrl,
  ticketUrlForOpenClawMedia,
  type OpenClawImageAttachment,
  type OpenClawImageMimeType,
  type OpenClawMessageImage,
} from './openclawMedia'
import {
  createOpenClawSessionLabel,
  isOpenClawSessionLabelConflict,
} from './openclawSession'

export type OpenClawConnectionStatus = 'disabled' | 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'
export type OpenClawToolsStatus = 'unknown' | 'available' | 'missing'
export type OpenClawRunPhase =
  | 'sending'
  | 'waiting'
  | 'thinking'
  | 'using_tool'
  | 'composing'
  | 'streaming'
  | 'stopping'
  | 'completed'
  | 'aborted'
  | 'failed'

export type OpenClawRunActivity = {
  id: string
  label: string
  status: 'running' | 'completed' | 'failed' | 'stopped'
  startedAt: number
  endedAt?: number
}

export type OpenClawRunTrace = {
  runId: string | null
  phase: OpenClawRunPhase
  status: 'running' | 'completed' | 'aborted' | 'failed'
  startedAt: number
  endedAt?: number
  activities: OpenClawRunActivity[]
}

export type OpenClawChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  status?: 'pending' | 'sent' | 'failed' | 'aborted'
  contextCount?: number
  contextSources?: AgentSourceReference[]
  sendSnapshot?: OpenClawSendSnapshot
  createdAt?: number
  origin?: 'local' | 'gateway'
  mergeId?: string
  clientTurnId?: string
  images?: OpenClawMessageImage[]
}

export type OpenClawSendRequest = {
  displayText: string
  gatewayPrompt: string
  contextItems: AgentContextItem[]
  attachments?: OpenClawImageAttachment[]
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
  supportsImages: boolean
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

export type OpenClawContextUsage = {
  sessionKey: string
  usedTokens: number
  contextTokens: number
  percent: number
  modelId?: string
}

export type OpenClawModelSwitchFallback = {
  modelId: string
  modelName: string
}

export type OpenClawSetupIssue = {
  kind: 'origin' | 'pairing' | 'auth' | 'protocol' | 'permission' | 'network' | 'session' | 'unknown'
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
  message?: unknown
}

export type OpenClawSanitizedAgentEvent = {
  runId: string
  seq: number
  stream: string
  phase: string | null
  timestamp: number
  toolCallId: string | null
  toolKey: string | null
  toolLabel: string | null
  failed: boolean
}

type OpenClawChatOptions = {
  enabled: boolean
  imageIoEnabled?: boolean
  mediaOrigins?: string[]
  userId: string
  defaultGatewayUrl: string
  vault?: OpenClawCredentialVault
  clientFactory?: (options: ConstructorParameters<typeof OpenClawGatewayClient>[0]) => OpenClawGatewayClient
}

export const OPENCLAW_GATEWAY_URL_KEY_PREFIX = 'inteliscope.openclaw.gateway.v1:'
export const OPENCLAW_TRANSCRIPT_KEY_PREFIX = 'inteliscope.openclaw.transcript.v1:'
const MAX_MESSAGES = 100
const MAX_HISTORY_CHARS = 100_000
const MAX_RUN_ACTIVITIES = 20
const MAX_IMAGES_PER_MESSAGE = 12

const INTELISCOPE_TOOL_LABELS: Record<string, string> = {
  get_my_feed: '读取信息流',
  get_item: '读取文章详情',
  list_subscriptions: '查看订阅',
  source_health: '检查来源健康',
  list_jobs: '查找运行记录',
  get_job: '读取任务详情',
  get_source_setup_guide: '读取来源配置指引',
  search_bilibili_users: '查找 Bilibili 账号',
  resolve_source: '验证公开来源',
  web_search: '搜索公开网页',
  list_available_sources: '查找可用来源',
  diagnose_source: '诊断来源',
  diagnose_job: '诊断任务',
  query_operation_logs: '查询脱敏操作事件',
  prepare_create_subscription: '准备创建订阅',
  prepare_update_subscription: '准备更新订阅',
  prepare_delete_subscription: '准备删除订阅',
  apply_subscription_change: '应用订阅变更',
}

type StoredOpenClawTranscriptV1 = {
  version: 1
  messages: OpenClawChatMessage[]
}

export function boundChatMessages(messages: OpenClawChatMessage[]): OpenClawChatMessage[] {
  const newest = messages.slice(-MAX_MESSAGES)
  const bounded: OpenClawChatMessage[] = []
  let remaining = MAX_HISTORY_CHARS
  for (let index = newest.length - 1; index >= 0 && (remaining > 0 || newest[index]?.images?.length); index -= 1) {
    const message = newest[index]
    const text = message.text.slice(0, remaining)
    const images = message.images?.slice(0, MAX_IMAGES_PER_MESSAGE) ?? []
    if (!text && !images.length) continue
    bounded.unshift({ ...message, text, ...(images.length ? { images } : {}) })
    remaining -= text.length
  }
  return bounded
}

function transcriptHash(value: string): string {
  let hash = 0x811c9dc5
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(36)
}

export function openClawTranscriptStorageKey(userId: string, gatewayUrl: string, sessionKey: string): string {
  return `${OPENCLAW_TRANSCRIPT_KEY_PREFIX}${encodeURIComponent(userId)}:${transcriptHash(gatewayUrl)}:${transcriptHash(sessionKey)}`
}

function normalizedMessageText(value: string): string {
  return value.normalize('NFKC').replace(/\s+/g, ' ').trim()
}

function messageSignature(message: OpenClawChatMessage): string {
  const contextSources = sanitizeAgentSourceReferences(message.contextSources)
  return [
    message.role,
    normalizedMessageText(message.text),
    message.contextCount ?? 0,
    contextSources.map((source) => source.url).join('\n'),
    (message.images ?? []).map((image) => image.reference
      ? `${image.reference.messageId}:${image.reference.partIndex}`
      : image.id).join('\n'),
  ].join('\n')
}

function messageMergeId(message: OpenClawChatMessage): string {
  return message.mergeId || message.clientTurnId || [
    messageSignature(message),
    message.createdAt ?? message.id,
  ].join('\n')
}

function persistedMessage(message: OpenClawChatMessage): OpenClawChatMessage {
  const keepRetrySnapshot = (message.status === 'pending' || message.status === 'failed')
    && Boolean(message.sendSnapshot)
    && !message.sendSnapshot?.attachments?.length
  const contextSources = sanitizeAgentSourceReferences(message.contextSources)
  const images = (message.images ?? []).flatMap((image) => image.reference ? [{
    id: image.id,
    alt: image.alt,
    ...(image.mimeType ? { mimeType: image.mimeType } : {}),
    ...(image.width ? { width: image.width } : {}),
    ...(image.height ? { height: image.height } : {}),
    reference: { ...image.reference },
  }] : [])
  return {
    id: message.id,
    role: message.role,
    text: message.text,
    status: message.status,
    contextCount: message.contextCount,
    ...(contextSources.length ? { contextSources } : {}),
    createdAt: message.createdAt,
    origin: message.origin,
    mergeId: message.mergeId || messageMergeId(message),
    clientTurnId: message.clientTurnId,
    ...(images.length ? { images } : {}),
    ...(keepRetrySnapshot ? { sendSnapshot: message.sendSnapshot } : {}),
  }
}

export function mergeOpenClawTranscript(
  local: OpenClawChatMessage[],
  gateway: OpenClawChatMessage[],
): OpenClawChatMessage[] {
  const merged = boundChatMessages(local).map((message) => ({ ...message }))
  const matchedLocalIndexes = new Set<number>()
  for (const remote of boundChatMessages(gateway)) {
    const remoteMergeId = messageMergeId(remote)
    let existingIndex = merged.findIndex((candidate, index) => (
      !matchedLocalIndexes.has(index)
      && candidate.role === remote.role
      && candidate.id === remote.id
    ))
    if (existingIndex < 0) {
      existingIndex = remote.clientTurnId
        ? merged.findIndex((candidate, index) => (
            !matchedLocalIndexes.has(index)
            && candidate.role === remote.role
            && candidate.clientTurnId === remote.clientTurnId
          ))
        : -1
    }
    if (existingIndex < 0) {
      existingIndex = merged.findIndex((candidate, index) => (
        !matchedLocalIndexes.has(index)
        && candidate.role === remote.role
        && messageMergeId(candidate) === remoteMergeId
      ))
    }
    if (existingIndex < 0) {
      const signature = messageSignature(remote)
      const candidates = merged
        .map((candidate, index) => ({ candidate, index }))
        .filter(({ candidate, index }) => !matchedLocalIndexes.has(index) && messageSignature(candidate) === signature)
      const remoteCreatedAt = remote.createdAt
      if (remoteCreatedAt !== undefined) {
        candidates.sort((left, right) => {
          const leftDistance = left.candidate.createdAt === undefined ? Number.POSITIVE_INFINITY : Math.abs(left.candidate.createdAt - remoteCreatedAt)
          const rightDistance = right.candidate.createdAt === undefined ? Number.POSITIVE_INFINITY : Math.abs(right.candidate.createdAt - remoteCreatedAt)
          return leftDistance - rightDistance
        })
      }
      existingIndex = candidates[0]?.index ?? -1
    }
    if (existingIndex < 0) {
      const appendedIndex = merged.length
      merged.push({ ...remote, mergeId: remote.mergeId || remoteMergeId })
      matchedLocalIndexes.add(appendedIndex)
      continue
    }
    matchedLocalIndexes.add(existingIndex)
    const existing = merged[existingIndex]
    const remoteConfirmsDelivery = remote.status === 'sent'
    const preserveLocalQuestion = existing.role === 'user'
      && existing.origin === 'local'
      && remote.role === 'user'
    merged[existingIndex] = {
      ...existing,
      ...remote,
      id: existing.id,
      role: existing.role,
      text: preserveLocalQuestion ? existing.text : remote.text,
      createdAt: existing.createdAt ?? remote.createdAt,
      contextCount: existing.contextCount ?? remote.contextCount,
      contextSources: existing.contextSources ?? remote.contextSources,
      origin: existing.origin ?? remote.origin,
      mergeId: existing.mergeId || remote.mergeId || remoteMergeId,
      clientTurnId: existing.clientTurnId ?? remote.clientTurnId,
      images: remote.images?.length ? remote.images : existing.images,
      ...(remoteConfirmsDelivery ? { sendSnapshot: undefined } : { sendSnapshot: existing.sendSnapshot ?? remote.sendSnapshot }),
    }
  }
  return boundChatMessages(merged)
}

export function readOpenClawTranscript(userId: string, gatewayUrl: string, sessionKey: string): OpenClawChatMessage[] {
  try {
    const raw = window.sessionStorage.getItem(openClawTranscriptStorageKey(userId, gatewayUrl, sessionKey))
    if (!raw) return []
    const parsed = JSON.parse(raw) as Partial<StoredOpenClawTranscriptV1>
    if (parsed.version !== 1 || !Array.isArray(parsed.messages)) return []
    return boundChatMessages(parsed.messages.flatMap((message) => (
      message
      && typeof message === 'object'
      && (message.role === 'user' || message.role === 'assistant')
      && typeof message.id === 'string'
      && typeof message.text === 'string'
        ? [persistedMessage(message)]
        : []
    )))
  } catch {
    return []
  }
}

export function writeOpenClawTranscript(
  userId: string,
  gatewayUrl: string,
  sessionKey: string,
  messages: OpenClawChatMessage[],
): void {
  try {
    const transcript: StoredOpenClawTranscriptV1 = {
      version: 1,
      messages: boundChatMessages(messages).map(persistedMessage),
    }
    window.sessionStorage.setItem(
      openClawTranscriptStorageKey(userId, gatewayUrl, sessionKey),
      JSON.stringify(transcript),
    )
  } catch {
    // Conversation persistence is best-effort and must never block chat.
  }
}

export function clearOpenClawTranscript(userId: string, gatewayUrl: string, sessionKey?: string | null): void {
  try {
    if (sessionKey) {
      window.sessionStorage.removeItem(openClawTranscriptStorageKey(userId, gatewayUrl, sessionKey))
      return
    }
    const prefix = `${OPENCLAW_TRANSCRIPT_KEY_PREFIX}${encodeURIComponent(userId)}:${transcriptHash(gatewayUrl)}:`
    for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = window.sessionStorage.key(index)
      if (key?.startsWith(prefix)) window.sessionStorage.removeItem(key)
    }
  } catch {
    // Conversation cleanup is best-effort.
  }
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

function messageCreatedAt(value: Record<string, unknown>): number | undefined {
  const candidate = value.createdAt ?? value.created_at ?? value.timestamp
  if (typeof candidate === 'number' && Number.isFinite(candidate)) return candidate
  if (typeof candidate !== 'string') return undefined
  const parsed = Date.parse(candidate)
  return Number.isFinite(parsed) ? parsed : undefined
}

function imageMimeType(value: unknown): OpenClawImageMimeType | undefined {
  return value === 'image/jpeg' || value === 'image/png' || value === 'image/webp'
    ? value
    : undefined
}

function imageDimension(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : undefined
}

function projectMessageImages(source: Record<string, unknown>, messageId: string): OpenClawMessageImage[] {
  const content = Array.isArray(source.content) ? source.content : []
  const images: OpenClawMessageImage[] = []
  content.forEach((candidate, partIndex) => {
    const part = recordOf(candidate)
    if (!part) return
    const type = stringOf(part.type)?.toLowerCase()
    if (type !== 'image' && type !== 'image_url' && type !== 'input_image') return
    const embedded = recordOf(part.image_url ?? part.imageUrl ?? part.media)
    const rawUrl = stringOf(part.url ?? embedded?.url)
    const mimeType = imageMimeType(part.mimeType ?? embedded?.mimeType)
    const width = imageDimension(part.width ?? embedded?.width)
    const height = imageDimension(part.height ?? embedded?.height)
    const alt = stringOf(part.alt ?? part.name) ?? ''
    if (rawUrl && isSafeOpenClawImageDataUrl(rawUrl)) {
      images.push({
        id: `${messageId}:image:${partIndex}`,
        alt,
        ...(mimeType ? { mimeType } : {}),
        ...(width ? { width } : {}),
        ...(height ? { height } : {}),
        url: rawUrl,
      })
      return
    }
    const mediaRef = recordOf(part.mediaRef ?? part.media_ref)
    const refMessageId = stringOf(mediaRef?.messageId ?? mediaRef?.message_id) ?? messageId
    const refPartIndex = mediaRef?.partIndex ?? mediaRef?.part_index ?? partIndex
    if (!refMessageId || typeof refPartIndex !== 'number' || !Number.isInteger(refPartIndex) || refPartIndex < 0) return
    images.push({
      id: `${refMessageId}:image:${refPartIndex}`,
      alt,
      ...(mimeType ? { mimeType } : {}),
      ...(width ? { width } : {}),
      ...(height ? { height } : {}),
      reference: { messageId: refMessageId, partIndex: refPartIndex },
    })
  })
  return images.slice(0, MAX_IMAGES_PER_MESSAGE)
}

function projectChatMessage(
  record: unknown,
  fallback: { id: string; role: 'user' | 'assistant'; text?: string; createdAt?: number } | null = null,
): OpenClawChatMessage | null {
  const source = recordOf(record)
  if (!source) {
    if (!fallback?.text) return null
    const message: OpenClawChatMessage = {
      id: fallback.id,
      role: fallback.role,
      text: fallback.text,
      status: 'sent',
      origin: 'local',
      createdAt: fallback.createdAt,
    }
    return { ...message, mergeId: messageMergeId(message) }
  }
  const role = source.role === 'user' || source.role === 'assistant' ? source.role : fallback?.role
  if (!role) return null
  const id = stringOf(source.id) ?? fallback?.id
  if (!id) return null
  const rawText = (messageText(record).trim() || fallback?.text || '').trim()
  const images = projectMessageImages(source, id)
  if (!rawText && !images.length) return null
  const handoff = role === 'user' && rawText ? projectAgentHandoffDisplay(rawText) : null
  const text = handoff?.displayText ?? rawText
  const clientTurnId = stringOf(source.clientTurnId ?? source.client_turn_id ?? source.idempotencyKey)
  const message: OpenClawChatMessage = {
    id,
    role,
    text,
    status: 'sent',
    origin: 'gateway',
    createdAt: messageCreatedAt(source) ?? fallback?.createdAt,
    ...(clientTurnId ? { clientTurnId } : {}),
    ...(handoff ? { contextCount: handoff.contextCount } : {}),
    ...(handoff?.sources?.length ? { contextSources: handoff.sources } : {}),
    ...(images.length ? { images } : {}),
  }
  return { ...message, mergeId: messageMergeId(message) }
}

export function projectChatHistory(value: unknown): OpenClawChatMessage[] {
  const records = value && typeof value === 'object' && Array.isArray((value as { messages?: unknown }).messages)
    ? (value as { messages: unknown[] }).messages
    : []
  return boundChatMessages(records.flatMap((record, index) => {
    const source = recordOf(record)
    const role = source?.role
    if (role !== 'user' && role !== 'assistant') return []
    const message = projectChatMessage(record, { id: `history-${index}`, role })
    return message ? [message] : []
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

function safeAgentIdentifier(value: unknown, maxLength = 160): string | null {
  const candidate = stringOf(value)
  if (!candidate || candidate.length > maxLength || !/^[a-zA-Z0-9_.:/-]+$/u.test(candidate)) return null
  return candidate
}

function projectToolLabel(value: unknown): { key: string | null; label: string } {
  const identifier = safeAgentIdentifier(value, 200)?.toLocaleLowerCase() ?? null
  if (!identifier) return { key: null, label: '使用工具' }
  for (const [key, label] of Object.entries(INTELISCOPE_TOOL_LABELS)) {
    if (
      identifier === key
      || identifier.endsWith(`__${key}`)
      || identifier.endsWith(`.${key}`)
      || identifier.endsWith(`/${key}`)
      || identifier.endsWith(`:${key}`)
    ) return { key, label }
  }
  return { key: null, label: '使用工具' }
}

export function projectOpenClawAgentEvent(
  event: GatewayEvent,
  expectedSessionKey: string,
): OpenClawSanitizedAgentEvent | null {
  if (event.event !== 'agent') return null
  const payload = recordOf(event.payload)
  if (!payload || stringOf(payload.sessionKey) !== expectedSessionKey) return null
  const runId = safeAgentIdentifier(payload.runId)
  const stream = safeAgentIdentifier(payload.stream, 48)?.toLocaleLowerCase()
  const seqCandidate = payload.seq ?? event.seq
  const seq = typeof seqCandidate === 'number' && Number.isFinite(seqCandidate) && seqCandidate >= 0
    ? Math.floor(seqCandidate)
    : null
  if (!runId || !stream || seq === null) return null
  const data = recordOf(payload.data) ?? {}
  const phase = safeAgentIdentifier(data.phase ?? data.state, 32)?.toLocaleLowerCase() ?? null
  const tool = stream === 'tool' ? projectToolLabel(data.name) : { key: null, label: '' }
  const timestamp = typeof payload.ts === 'number' && Number.isFinite(payload.ts) && payload.ts > 0
    ? payload.ts
    : Date.now()
  const status = safeAgentIdentifier(data.status, 32)?.toLocaleLowerCase()
  return {
    runId,
    seq,
    stream,
    phase,
    timestamp,
    toolCallId: safeAgentIdentifier(data.toolCallId ?? data.callId),
    toolKey: tool.key,
    toolLabel: stream === 'tool' ? tool.label : null,
    failed: data.isError === true || status === 'error' || status === 'failed' || phase === 'error',
  }
}

function mergeRunActivity(
  activities: OpenClawRunActivity[],
  event: OpenClawSanitizedAgentEvent,
): OpenClawRunActivity[] {
  const terminal = event.phase === 'result' || event.phase === 'end' || event.phase === 'done' || event.failed
  const status: OpenClawRunActivity['status'] = event.failed ? 'failed' : terminal ? 'completed' : 'running'
  const id = event.toolCallId
    ?? [...activities].reverse().find((activity) => activity.status === 'running' && activity.id.startsWith(`tool:${event.toolKey ?? 'unknown'}:`))?.id
    ?? `tool:${event.toolKey ?? 'unknown'}:${event.seq}`
  const existingIndex = activities.findIndex((activity) => activity.id === id)
  const next = activities.map((activity) => ({ ...activity }))
  const activity: OpenClawRunActivity = {
    id,
    label: event.toolLabel ?? '使用工具',
    status,
    startedAt: existingIndex >= 0 ? next[existingIndex].startedAt : event.timestamp,
    ...(terminal ? { endedAt: event.timestamp } : {}),
  }
  if (existingIndex >= 0) next[existingIndex] = activity
  else next.push(activity)
  return next.slice(-MAX_RUN_ACTIVITIES)
}

function applyAgentEventToTrace(
  trace: OpenClawRunTrace | null,
  event: OpenClawSanitizedAgentEvent,
): OpenClawRunTrace {
  const current: OpenClawRunTrace = trace ?? {
    runId: event.runId,
    phase: 'waiting',
    status: 'running',
    startedAt: event.timestamp,
    activities: [],
  }
  if (event.stream === 'tool') {
    return {
      ...current,
      runId: event.runId,
      phase: 'using_tool',
      status: 'running',
      activities: mergeRunActivity(current.activities, event),
    }
  }
  if (event.stream === 'thinking' || event.stream === 'plan') {
    return { ...current, runId: event.runId, phase: 'thinking', status: 'running' }
  }
  if (event.stream === 'assistant') {
    return { ...current, runId: event.runId, phase: 'composing', status: 'running' }
  }
  if (event.stream === 'lifecycle') {
    if (event.failed || event.phase === 'error') {
      return { ...current, runId: event.runId, phase: 'failed', status: 'failed', endedAt: event.timestamp }
    }
    if (event.phase === 'end' || event.phase === 'done') {
      return { ...current, runId: event.runId, phase: 'composing', status: 'running' }
    }
    return { ...current, runId: event.runId, phase: 'thinking', status: 'running' }
  }
  if (event.stream === 'error') {
    return { ...current, runId: event.runId, phase: 'failed', status: 'failed', endedAt: event.timestamp }
  }
  return { ...current, runId: event.runId, phase: 'waiting', status: 'running' }
}

function contextUsageRecord(value: unknown, expectedSessionKey: string): Record<string, unknown> | null {
  const root = recordOf(value)
  if (!root) return null
  if (Array.isArray(root.sessions)) {
    return root.sessions
      .map(recordOf)
      .find((candidate) => stringOf(candidate?.key ?? candidate?.sessionKey) === expectedSessionKey)
      ?? null
  }
  const session = recordOf(root.session) ?? root
  const sessionKey = stringOf(session.key ?? session.sessionKey ?? root.sessionKey)
  return sessionKey === expectedSessionKey ? session : null
}

function contextUsagePayloadMatchesSession(value: unknown, expectedSessionKey: string): boolean {
  return contextUsageRecord(value, expectedSessionKey) !== null
}

export function projectOpenClawContextUsage(
  value: unknown,
  expectedSessionKey: string,
): OpenClawContextUsage | null {
  const session = contextUsageRecord(value, expectedSessionKey)
  if (!session || session.totalTokensFresh === false) return null
  const usedTokens = session.totalTokens
  const contextTokens = session.contextTokens
  if (
    typeof usedTokens !== 'number'
    || !Number.isFinite(usedTokens)
    || usedTokens <= 0
    || typeof contextTokens !== 'number'
    || !Number.isFinite(contextTokens)
    || contextTokens <= 0
  ) return null
  const provider = stringOf(session.modelProvider ?? session.provider)
  const model = stringOf(session.modelId ?? session.model)
  const modelId = model && provider && !model.includes('/') ? `${provider}/${model}` : model
  return {
    sessionKey: expectedSessionKey,
    usedTokens: Math.floor(usedTokens),
    contextTokens: Math.floor(contextTokens),
    percent: Math.min(999, Math.max(0, Math.round((usedTokens / contextTokens) * 100))),
    ...(modelId ? { modelId } : {}),
  }
}

function normalizeModels(value: unknown): OpenClawModelOption[] {
  const root = recordOf(value)
  const entries = Array.isArray(root?.models) ? root.models : []
  const seen = new Set<string>()
  return entries.flatMap((entry) => {
    const model = recordOf(entry)
    if (!model) return []
    const rawId = stringOf(model.id)
    const provider = stringOf(model.provider)
    if (!rawId || !provider || model.available === false) return []
    const id = rawId.includes('/') ? rawId : `${provider}/${rawId}`
    const name = stringOf(model.name) ?? rawId
    if (seen.has(id)) return []
    seen.add(id)
    const contextWindow = typeof model.contextWindow === 'number' && Number.isFinite(model.contextWindow)
      ? Math.max(1, Math.floor(model.contextWindow))
      : undefined
    const thinkingLevels = normalizeThinkingOptions(model.thinkingLevels)
    const thinkingDefault = stringOf(model.thinkingDefault)
    const input = Array.isArray(model.input) ? model.input : []
    return [{
      id,
      name,
      provider,
      supportsImages: input.some((capability) => capability === 'image'),
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
  const full = providerName && !modelName.includes('/') ? `${providerName}/${modelName}` : modelName
  const exact = models.find((candidate) => candidate.id === full)?.id
    ?? models.find((candidate) => candidate.id === modelName)?.id
  if (exact) return exact
  if (providerName || modelName.includes('/')) return null
  const suffixMatches = models.filter((candidate) => candidate.id.endsWith(`/${modelName}`))
  return suffixMatches.length === 1 ? suffixMatches[0].id : null
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

export function projectOpenClawRuntime(
  modelsValue: unknown,
  agentsValue: unknown,
  sessionValue: unknown,
  requestedAgentId: string,
): RuntimeProjection {
  const models = normalizeModels(modelsValue)
  const agentsRoot = recordOf(agentsValue)
  const agents = Array.isArray(agentsRoot?.agents) ? agentsRoot.agents : []
  const defaultAgentId = stringOf(agentsRoot?.defaultId)
  const agent = agents.map(recordOf).find((candidate) => (
    stringOf(candidate?.id) === requestedAgentId
    || (!agents.some((entry) => stringOf(recordOf(entry)?.id) === requestedAgentId) && stringOf(candidate?.id) === defaultAgentId)
  )) ?? null
  const agentModel = recordOf(agent?.model)
  const defaultModelId = matchingModelId(models, null, agentModel?.primary)
  const sessionRoot = recordOf(sessionValue)
  const session = recordOf(sessionRoot?.session) ?? sessionRoot
  const sessionThinkingOptions = normalizeThinkingOptions(session?.thinkingLevels)
  const matchedSessionModelId = matchingModelId(models, session?.modelProvider, session?.model)
  const hasExplicitSessionModel = Boolean(stringOf(session?.model))
  const defaultModelIsAvailable = Boolean(defaultModelId)
  const modelId = matchedSessionModelId ?? (!hasExplicitSessionModel && defaultModelIsAvailable ? defaultModelId : null)
  const selectedModel = models.find((candidate) => candidate.id === modelId)
  const modelThinkingOptions = selectedModel?.thinkingLevels ?? []
  const thinkingOptions = !selectedModel || selectedModel.reasoning === false
    ? []
    : modelThinkingOptions.length
      ? modelThinkingOptions
      : sessionThinkingOptions.length
        ? sessionThinkingOptions
        : []
  const rawDefaultThinkingLevel = selectedModel?.thinkingDefault ?? stringOf(session?.thinkingDefault)
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
  if (isOpenClawSessionLabelConflict(error)) return { kind: 'session', message: 'OpenClaw 会话名称冲突，请重新连接。', requestId }
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

type OpenClawSessionCreateParams = {
  agentId: string
  parentSessionKey?: string
  fork?: true
  model?: string
}

async function createOpenClawSession(
  client: OpenClawGatewayClient,
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

export function useOpenClawChat(options: OpenClawChatOptions) {
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
  const clientRef = useRef<OpenClawGatewayClient | null>(null)
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
    client: OpenClawGatewayClient,
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

  const loadHistory = useCallback(async (client: OpenClawGatewayClient, key: string, agentId: string) => {
    const history = await client.request('chat.history', { sessionKey: key, agentId, limit: MAX_MESSAGES, maxChars: MAX_HISTORY_CHARS })
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

  const readRuntime = useCallback(async (client: OpenClawGatewayClient, key: string, agentId: string) => {
    const [modelsValue, agentsValue, sessionValue] = await Promise.all([
      client.request('models.list', { view: 'configured' }),
      client.request('agents.list', {}),
      client.request('sessions.describe', { key }),
    ])
    return projectOpenClawRuntime(modelsValue, agentsValue, sessionValue, agentId)
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

  const loadContextUsage = useCallback(async (client: OpenClawGatewayClient, key: string) => {
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
        const next = (payload.replace ? payload.deltaText! : `${current}${payload.deltaText}`).slice(0, MAX_HISTORY_CHARS)
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
        if (!createdKey) throw new Error('OpenClaw 无法创建 Inteliscope 对话。')
        key = createdKey
        await vault.save(options.userId, parsed.gatewayUrl, { ...credential, sessionKey: key })
      }
      if (!key) throw new Error('OpenClaw 无法创建 Inteliscope 对话。')
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
    beginRunTrace(snapshot.contextItems.length)
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
      const sourceUrl = sanitizeSourceUrl(item.sourceUrl)
      return { ...item, sourceUrl: sourceUrl || undefined }
    })
    const snapshot: OpenClawSendSnapshot = {
      displayText,
      gatewayPrompt,
      contextItems,
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
      contextCount: snapshot.contextItems.length,
      contextSources: agentSourceReferences(snapshot.contextItems),
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
    client: OpenClawGatewayClient,
    key: string,
    agentId: string,
    projection: RuntimeProjection,
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
