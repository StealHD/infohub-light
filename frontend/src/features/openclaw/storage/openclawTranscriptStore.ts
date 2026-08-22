import type { OpenClawChatMessage } from '../openclawContracts'
import { sanitizeOpenClawSourceReferences } from '../chat/openclawHandoffProtocol'

export const OPENCLAW_TRANSCRIPT_KEY_PREFIX = 'inteliscope.openclaw.transcript.v1:'
export const OPENCLAW_MAX_MESSAGES = 100
export const OPENCLAW_MAX_HISTORY_CHARS = 100_000
export const OPENCLAW_MAX_IMAGES_PER_MESSAGE = 12

type StoredOpenClawTranscriptV1 = {
  version: 1
  messages: OpenClawChatMessage[]
}

export function boundChatMessages(messages: OpenClawChatMessage[]): OpenClawChatMessage[] {
  const newest = messages.slice(-OPENCLAW_MAX_MESSAGES)
  const bounded: OpenClawChatMessage[] = []
  let remaining = OPENCLAW_MAX_HISTORY_CHARS
  for (let index = newest.length - 1; index >= 0 && (remaining > 0 || newest[index]?.images?.length); index -= 1) {
    const message = newest[index]
    const text = message.text.slice(0, remaining)
    const images = message.images?.slice(0, OPENCLAW_MAX_IMAGES_PER_MESSAGE) ?? []
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
  const contextSources = sanitizeOpenClawSourceReferences(message.contextSources)
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

export function messageMergeId(message: OpenClawChatMessage): string {
  return message.mergeId || message.clientTurnId || [
    messageSignature(message),
    message.createdAt ?? message.id,
  ].join('\n')
}

function persistedMessage(message: OpenClawChatMessage): OpenClawChatMessage {
  const keepRetrySnapshot = (message.status === 'pending' || message.status === 'failed')
    && Boolean(message.sendSnapshot)
    && !message.sendSnapshot?.attachments?.length
  const contextSources = sanitizeOpenClawSourceReferences(message.contextSources)
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
      !matchedLocalIndexes.has(index) && candidate.role === remote.role && candidate.id === remote.id
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
    const preserveLocalQuestion = existing.role === 'user' && existing.origin === 'local' && remote.role === 'user'
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
