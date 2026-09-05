import { sanitizeSkillSelection, type OpenClawSkillSelection } from '../openclaw/chat/openclawSkillSelection'

export type AgentContextItem = {
  articleId: string
  title: string
  sourceName?: string
  sourceUrl?: string
  sourceAvatarUrl?: string
  publishedAt?: string
  resourceType?: 'feed_item' | 'job'
  jobId?: string
  statusLabel?: string
  detail?: string
}

export type AgentSourceSnapshotItem = {
  articleId: string
  title: string
  summary?: string
  publishedAt?: string
}

export type AgentSourceSnapshot = {
  sourceName: string
  windowLabel: string
  itemCount: number
  items: AgentSourceSnapshotItem[]
}

export type AgentContextDraftV6 = {
  selectedSkill?: OpenClawSkillSelection
  userId: string
  question: string
  items: AgentContextItem[]
  sourceSnapshot?: AgentSourceSnapshot
}

/** Import-compatible alias while persisted V5 drafts migrate to V6. */
export type AgentContextDraftV5 = AgentContextDraftV6

export type AgentSourceReference = {
  title: string
  url: string
  sourceName?: string
  sourceAvatarUrl?: string
}

export type AgentHandoffDisplay = {
  displayText: string
  contextCount: number
  imageCount?: number
  sources?: AgentSourceReference[]
}

export { INTELISCOPE_HANDOFF_MARKER }

const storageKey = (userId: string) => `inteliscope.agent-context.v6:${userId}`
const v5StorageKey = (userId: string) => `inteliscope.agent-context.v5:${userId}`
const v4StorageKey = (userId: string) => `inteliscope.agent-context.v4:${userId}`
const v3StorageKey = (userId: string) => `inteliscope.agent-context.v3:${userId}`
const v2StorageKey = (userId: string) => `inteliscope.agent-context.v2:${userId}`
const legacyStorageKey = (userId: string) => `inteliscope.agent-context.v1:${userId}`
const maxItems = 8
export const MAX_AGENT_SOURCE_SNAPSHOT_ITEMS = 100
export const MAX_AGENT_SOURCE_SNAPSHOT_CHARS = 32_000
const maxQuestionLength = 1200
const inlineUrlPattern = /(?:https?:\/\/|www\.)[^\s<>"']+/giu

function emptyDraft(userId: string): AgentContextDraftV6 {
  return { userId, question: '', items: [] }
}

function safeText(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function safeSnapshotText(value: unknown, maxLength: number): string {
  return safeText(typeof value === 'string' ? value.replace(inlineUrlPattern, '').replace(/\s+/gu, ' ') : value, maxLength)
}

export function sanitizeSourceUrl(value: unknown): string {
  return sanitizeOpenClawSourceUrl(value)
}

export function sanitizeSourceAvatarUrl(value: unknown): string {
  return sanitizeOpenClawSourceAvatarUrl(value)
}

function sanitizeItem(value: unknown): AgentContextItem | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<AgentContextItem>
  const resourceType = candidate.resourceType === 'job' ? 'job' : 'feed_item'
  const jobId = resourceType === 'job'
    ? safeText(candidate.jobId, 256) || safeText(candidate.articleId, 256).replace(/^job:/u, '')
    : ''
  const articleId = resourceType === 'job'
    ? jobId ? `job:${jobId}` : ''
    : safeText(candidate.articleId, 256)
  if (!articleId) return null
  const sourceUrl = resourceType === 'feed_item' ? sanitizeSourceUrl(candidate.sourceUrl) : ''
  const sourceAvatarUrl = resourceType === 'feed_item' ? sanitizeSourceAvatarUrl(candidate.sourceAvatarUrl) : ''
  return {
    articleId,
    title: safeText(candidate.title, 300) || articleId,
    ...(safeText(candidate.sourceName, 160) ? { sourceName: safeText(candidate.sourceName, 160) } : {}),
    ...(sourceUrl ? { sourceUrl } : {}),
    ...(sourceAvatarUrl ? { sourceAvatarUrl } : {}),
    ...(safeText(candidate.publishedAt, 80) ? { publishedAt: safeText(candidate.publishedAt, 80) } : {}),
    ...(resourceType === 'job' ? { resourceType, jobId } : {}),
    ...(safeText(candidate.statusLabel, 80) ? { statusLabel: safeText(candidate.statusLabel, 80) } : {}),
    ...(safeText(candidate.detail, 600) ? { detail: safeText(candidate.detail, 600) } : {}),
  }
}

type DraftInput = Partial<AgentContextDraftV6> & { itemIds?: unknown; modelPreference?: unknown }

function sanitizeSourceSnapshot(value: unknown): AgentSourceSnapshot | undefined {
  if (!value || typeof value !== 'object') return undefined
  const candidate = value as Partial<AgentSourceSnapshot>
  if (!Array.isArray(candidate.items)) return undefined
  const seen = new Set<string>()
  const items = candidate.items.flatMap((raw) => {
    if (!raw || typeof raw !== 'object') return []
    const item = raw as Partial<AgentSourceSnapshotItem>
    const articleId = safeText(item.articleId, 128)
    if (!articleId || seen.has(articleId)) return []
    seen.add(articleId)
    const summary = safeSnapshotText(item.summary, 2_000)
    const publishedAt = safeText(item.publishedAt, 80)
    return [{
      articleId,
      title: safeSnapshotText(item.title, 240) || articleId,
      ...(summary ? { summary } : {}),
      ...(publishedAt ? { publishedAt } : {}),
    }]
  }).slice(0, MAX_AGENT_SOURCE_SNAPSHOT_ITEMS)
  if (!items.length) return undefined
  return {
    sourceName: safeSnapshotText(candidate.sourceName, 160) || '未知来源',
    windowLabel: safeText(candidate.windowLabel, 80) || '当前筛选结果',
    itemCount: items.length,
    items,
  }
}

export function createAgentSourceSnapshot(input: {
  sourceName: string
  windowLabel: string
  items: AgentSourceSnapshotItem[]
}): AgentSourceSnapshot | null {
  if (input.items.length < 1 || input.items.length > MAX_AGENT_SOURCE_SNAPSHOT_ITEMS) return null
  const sanitized = sanitizeSourceSnapshot({ ...input, itemCount: input.items.length })
  if (!sanitized) return null
  const baseSize = sanitized.sourceName.length + sanitized.windowLabel.length + sanitized.items.reduce(
    (total, item) => total + item.articleId.length + item.title.length + (item.publishedAt?.length ?? 0) + 12,
    0,
  )
  const remaining = Math.max(0, MAX_AGENT_SOURCE_SNAPSHOT_CHARS - baseSize)
  const perSummary = Math.floor(remaining / sanitized.items.length)
  let snapshot: AgentSourceSnapshot = {
    ...sanitized,
    items: sanitized.items.map((item) => {
      const summary = item.summary && perSummary > 0 ? item.summary.slice(0, perSummary).trim() : ''
      return { ...item, ...(summary ? { summary } : { summary: undefined }) }
    }),
  }
  let previousSize = Number.POSITIVE_INFINITY
  let serializedSize = JSON.stringify(snapshot).length
  while (serializedSize > MAX_AGENT_SOURCE_SNAPSHOT_CHARS && serializedSize < previousSize) {
    previousSize = serializedSize
    const overage = serializedSize - MAX_AGENT_SOURCE_SNAPSHOT_CHARS
    const reduction = Math.max(1, Math.ceil(overage / snapshot.items.length))
    const hasSummaryBudget = snapshot.items.some((item) => Boolean(item.summary))
    snapshot = {
      ...snapshot,
      items: snapshot.items.map((item) => {
        if (hasSummaryBudget) {
          const summary = item.summary?.slice(0, Math.max(0, item.summary.length - reduction)).trim()
          return { ...item, ...(summary ? { summary } : { summary: undefined }) }
        }
        return { ...item, title: item.title.slice(0, Math.max(24, item.title.length - reduction)).trim() }
      }),
    }
    serializedSize = JSON.stringify(snapshot).length
  }
  if (serializedSize > MAX_AGENT_SOURCE_SNAPSHOT_CHARS) {
    snapshot = {
      ...snapshot,
      sourceName: snapshot.sourceName.slice(0, 80),
      windowLabel: snapshot.windowLabel.slice(0, 40),
      items: snapshot.items.map((item) => ({
        articleId: item.articleId.slice(0, 64),
        title: item.title.slice(0, 24),
        ...(item.publishedAt ? { publishedAt: item.publishedAt.slice(0, 40) } : {}),
      })),
    }
  }
  return snapshot
}

export function sanitizeDraft(userId: string, value?: DraftInput | null): AgentContextDraftV6 {
  const seen = new Set<string>()
  const sourceItems: unknown[] = Array.isArray(value?.items)
    ? value.items
    : Array.isArray(value?.itemIds)
      ? value.itemIds.map((articleId) => ({ articleId, title: articleId }))
      : []
  const items = sourceItems.flatMap((candidate) => {
    const item = sanitizeItem(candidate)
    if (!item || seen.has(item.articleId)) return []
    seen.add(item.articleId)
    return [item]
  }).slice(0, maxItems)
  const sourceSnapshot = sanitizeSourceSnapshot(value?.sourceSnapshot)
  return {
    userId,
    question: typeof value?.question === 'string' ? value.question.slice(0, maxQuestionLength) : '',
    ...(sanitizeSkillSelection(value?.selectedSkill) ? { selectedSkill: sanitizeSkillSelection(value?.selectedSkill) } : {}),
    items,
    ...(sourceSnapshot ? { sourceSnapshot } : {}),
  }
}

export function readAgentContextDraft(userId: string): AgentContextDraftV6 {
  try {
    const stored = window.sessionStorage.getItem(storageKey(userId))
      ?? window.sessionStorage.getItem(v5StorageKey(userId))
      ?? window.sessionStorage.getItem(v4StorageKey(userId))
      ?? window.sessionStorage.getItem(v3StorageKey(userId))
      ?? window.sessionStorage.getItem(v2StorageKey(userId))
      ?? window.sessionStorage.getItem(legacyStorageKey(userId))
    return sanitizeDraft(userId, JSON.parse(stored || 'null') as DraftInput | null)
  } catch {
    return emptyDraft(userId)
  }
}

export function writeAgentContextDraft(userId: string, draft: AgentContextDraftV6): AgentContextDraftV6 {
  const next = sanitizeDraft(userId, draft)
  try {
    window.sessionStorage.setItem(storageKey(userId), JSON.stringify(next))
    window.sessionStorage.removeItem(v5StorageKey(userId))
    window.sessionStorage.removeItem(v4StorageKey(userId))
    window.sessionStorage.removeItem(v3StorageKey(userId))
    window.sessionStorage.removeItem(v2StorageKey(userId))
    window.sessionStorage.removeItem(legacyStorageKey(userId))
  } catch {
    // A private or restricted browser session may reject storage; keep the in-memory caller state usable.
  }
  return next
}

export function updateAgentContextDraft(draft: AgentContextDraftV6, item: AgentContextItem): AgentContextDraftV6 {
  const current = sanitizeDraft(draft.userId, draft)
  const normalized = sanitizeItem(item)
  if (!normalized) return current
  const exists = current.items.some((candidate) => candidate.articleId === normalized.articleId)
  const items = exists
    ? current.items.filter((candidate) => candidate.articleId !== normalized.articleId)
    : current.items.length < maxItems ? [...current.items, normalized] : current.items
  return { ...current, items, sourceSnapshot: undefined }
}

export function clearAgentContextDraft(userId: string): void {
  try {
    window.sessionStorage.removeItem(storageKey(userId))
    window.sessionStorage.removeItem(v5StorageKey(userId))
    window.sessionStorage.removeItem(v4StorageKey(userId))
    window.sessionStorage.removeItem(v3StorageKey(userId))
    window.sessionStorage.removeItem(v2StorageKey(userId))
    window.sessionStorage.removeItem(legacyStorageKey(userId))
  } catch {
    // Storage cleanup is best-effort when the browser blocks access.
  }
}

export function agentSourceReferences(items: AgentContextItem[]): AgentSourceReference[] {
  return openClawSourceReferences(items)
}

export function sanitizeAgentSourceReferences(value: unknown): AgentSourceReference[] {
  return sanitizeOpenClawSourceReferences(value)
}


export function projectAgentHandoffDisplay(text: string): AgentHandoffDisplay | null {
  return projectOpenClawHandoffDisplay(text)
}
import {
  INTELISCOPE_HANDOFF_MARKER,
  openClawSourceReferences,
  projectOpenClawHandoffDisplay,
  sanitizeOpenClawSourceAvatarUrl,
  sanitizeOpenClawSourceReferences,
  sanitizeOpenClawSourceUrl,
} from '../openclaw/chat/openclawHandoffProtocol'
