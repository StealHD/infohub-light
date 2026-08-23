import type { OpenClawChatMessage } from '../openclawContracts'
import {
  isSafeOpenClawImageDataUrl,
  type OpenClawImageMimeType,
  type OpenClawMessageImage,
} from '../openclawMedia'
import {
  boundChatMessages,
  messageMergeId,
  OPENCLAW_MAX_IMAGES_PER_MESSAGE,
} from '../storage/openclawTranscriptStore'
import { projectOpenClawHandoffDisplay } from './openclawHandoffProtocol'
import { recordOf, stringOf } from './openclawProjectionUtils'

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
  return images.slice(0, OPENCLAW_MAX_IMAGES_PER_MESSAGE)
}

export function projectChatMessage(
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
  const handoff = role === 'user' && rawText ? projectOpenClawHandoffDisplay(rawText) : null
  const clientTurnId = stringOf(source.clientTurnId ?? source.client_turn_id ?? source.idempotencyKey)
  const message: OpenClawChatMessage = {
    id,
    role,
    text: handoff?.displayText ?? rawText,
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
