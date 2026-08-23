import type {
  OpenClawContextItem,
  OpenClawSourceReference,
} from '../openclawContracts'

export type OpenClawHandoffDisplay = {
  displayText: string
  contextCount: number
  imageCount?: number
  sources?: OpenClawSourceReference[]
}

export const INTELISCOPE_HANDOFF_MARKER = '[INTELISCOPE_HANDOFF_V8]'
const PREVIOUS_HANDOFF_MARKERS = [
  '[INTELISCOPE_HANDOFF_V7]',
  '[INTELISCOPE_HANDOFF_V6]',
  '[INTELISCOPE_HANDOFF_V5]',
  '[INTELISCOPE_HANDOFF_V4]',
  '[INTELISCOPE_HANDOFF_V3]',
] as const
const MAX_CONTEXT_ITEMS = 8
const MAX_SNAPSHOT_ITEMS = 100
const MAX_QUESTION_LENGTH = 1200
const MAX_SOURCE_URL_LENGTH = 2048
const SENSITIVE_QUERY_PARAMETER = /(?:^|[_-])(?:access[_-]?token|auth|authorization|code|credential|key|password|secret|session|sig|signature|token)(?:$|[_-])/iu
const TRACKING_QUERY_PARAMETER = /^(?:fbclid|gclid|mc_[a-z]+|utm_[a-z]+)$/iu

function safeText(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

export function sanitizeOpenClawSourceUrl(value: unknown): string {
  const raw = safeText(value, 4096)
  if (!raw) return ''
  try {
    const parsed = new URL(raw)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) return ''
    parsed.hash = ''
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (TRACKING_QUERY_PARAMETER.test(key) || SENSITIVE_QUERY_PARAMETER.test(key)) parsed.searchParams.delete(key)
    }
    const normalized = parsed.toString()
    return normalized.length <= MAX_SOURCE_URL_LENGTH ? normalized : ''
  } catch {
    return ''
  }
}

export function sanitizeOpenClawSourceAvatarUrl(value: unknown): string {
  const avatarUrl = safeText(value, 256)
  return /^\/api\/media\/[A-Za-z0-9_-]{1,128}$/u.test(avatarUrl) ? avatarUrl : ''
}

export function openClawSourceReferences(items: OpenClawContextItem[]): OpenClawSourceReference[] {
  return items.flatMap((item) => {
    const url = sanitizeOpenClawSourceUrl(item.sourceUrl)
    if (item.resourceType === 'job' || !url) return []
    const sourceName = safeText(item.sourceName, 160)
    const sourceAvatarUrl = sanitizeOpenClawSourceAvatarUrl(item.sourceAvatarUrl)
    return [{
      title: safeText(item.title, 300) || url,
      url,
      ...(sourceName ? { sourceName } : {}),
      ...(sourceAvatarUrl ? { sourceAvatarUrl } : {}),
    }]
  }).slice(0, MAX_CONTEXT_ITEMS)
}

export function sanitizeOpenClawSourceReferences(value: unknown): OpenClawSourceReference[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object') return []
    const source = candidate as Partial<OpenClawSourceReference>
    const url = sanitizeOpenClawSourceUrl(source.url)
    if (!url) return []
    const sourceName = safeText(source.sourceName, 160)
    const sourceAvatarUrl = sanitizeOpenClawSourceAvatarUrl(source.sourceAvatarUrl)
    return [{
      title: safeText(source.title, 300) || url,
      url,
      ...(sourceName ? { sourceName } : {}),
      ...(sourceAvatarUrl ? { sourceAvatarUrl } : {}),
    }]
  }).slice(0, MAX_CONTEXT_ITEMS)
}

function safeCount(value: unknown, maximum: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, Math.min(maximum, Math.floor(value)))
    : 0
}

export function projectOpenClawHandoffDisplay(text: string): OpenClawHandoffDisplay | null {
  const normalized = text.trim()
  const versionedMarker = [INTELISCOPE_HANDOFF_MARKER, ...PREVIOUS_HANDOFF_MARKERS]
    .find((marker) => normalized.startsWith(marker))
  if (versionedMarker) {
    const metadata = normalized.slice(versionedMarker.length).trimStart().split('\n', 1)[0]
    try {
      const parsed = JSON.parse(metadata) as {
        displayText?: unknown
        contextCount?: unknown
        imageCount?: unknown
        sources?: unknown
      }
      const displayText = safeText(parsed.displayText, MAX_QUESTION_LENGTH)
      if (!displayText) return null
      const sources = sanitizeOpenClawSourceReferences(parsed.sources)
      const imageCount = safeCount(parsed.imageCount, 4)
      return {
        displayText,
        contextCount: safeCount(parsed.contextCount, MAX_SNAPSHOT_ITEMS),
        ...(imageCount ? { imageCount } : {}),
        ...(sources.length ? { sources } : {}),
      }
    } catch {
      return null
    }
  }

  if (!normalized.startsWith('请使用 Inteliscope Remote MCP 完成以下任务。')) return null
  const questionMatch = normalized.match(/(?:^|\n)问题：([\s\S]*?)(?:\n模型偏好：|\n必须按顺序读取上下文)/u)
  const displayText = safeText(questionMatch?.[1], MAX_QUESTION_LENGTH)
  if (!displayText) return null
  const contextCount = Math.min(
    MAX_CONTEXT_ITEMS,
    normalized.match(/调用 (?:get_item，article_id|get_job，job_id|diagnose_job，job_id)=/gu)?.length ?? 0,
  )
  return { displayText, contextCount }
}
