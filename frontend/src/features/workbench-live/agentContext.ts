export type AgentModelPreference = 'auto' | 'fast' | 'deep'

export type AgentContextItem = {
  articleId: string
  title: string
  sourceName?: string
  publishedAt?: string
}

export type AgentContextDraftV2 = {
  userId: string
  question: string
  items: AgentContextItem[]
  modelPreference: AgentModelPreference
}

const storageKey = (userId: string) => `inteliscope.agent-context.v2:${userId}`
const legacyStorageKey = (userId: string) => `inteliscope.agent-context.v1:${userId}`
const maxItems = 8
const maxQuestionLength = 1200

function emptyDraft(userId: string): AgentContextDraftV2 {
  return { userId, question: '', items: [], modelPreference: 'auto' }
}

function sanitizeModelPreference(value: unknown): AgentModelPreference {
  return value === 'fast' || value === 'deep' ? value : 'auto'
}

function safeText(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function sanitizeItem(value: unknown): AgentContextItem | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<AgentContextItem>
  const articleId = safeText(candidate.articleId, 256)
  if (!articleId) return null
  return {
    articleId,
    title: safeText(candidate.title, 300) || articleId,
    ...(safeText(candidate.sourceName, 160) ? { sourceName: safeText(candidate.sourceName, 160) } : {}),
    ...(safeText(candidate.publishedAt, 80) ? { publishedAt: safeText(candidate.publishedAt, 80) } : {}),
  }
}

type DraftInput = Partial<AgentContextDraftV2> & { itemIds?: unknown }

function sanitizeDraft(userId: string, value?: DraftInput | null): AgentContextDraftV2 {
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
  return {
    userId,
    question: typeof value?.question === 'string' ? value.question.slice(0, maxQuestionLength) : '',
    items,
    modelPreference: sanitizeModelPreference(value?.modelPreference),
  }
}

export function readAgentContextDraft(userId: string): AgentContextDraftV2 {
  try {
    const stored = window.sessionStorage.getItem(storageKey(userId))
      ?? window.sessionStorage.getItem(legacyStorageKey(userId))
    return sanitizeDraft(userId, JSON.parse(stored || 'null') as DraftInput | null)
  } catch {
    return emptyDraft(userId)
  }
}

export function writeAgentContextDraft(userId: string, draft: AgentContextDraftV2): AgentContextDraftV2 {
  const next = sanitizeDraft(userId, draft)
  try {
    window.sessionStorage.setItem(storageKey(userId), JSON.stringify(next))
    window.sessionStorage.removeItem(legacyStorageKey(userId))
  } catch {
    // A private or restricted browser session may reject storage; keep the in-memory caller state usable.
  }
  return next
}

export function updateAgentContextDraft(draft: AgentContextDraftV2, item: AgentContextItem): AgentContextDraftV2 {
  const current = sanitizeDraft(draft.userId, draft)
  const normalized = sanitizeItem(item)
  if (!normalized) return current
  const exists = current.items.some((candidate) => candidate.articleId === normalized.articleId)
  const items = exists
    ? current.items.filter((candidate) => candidate.articleId !== normalized.articleId)
    : current.items.length < maxItems ? [...current.items, normalized] : current.items
  return { ...current, items }
}

export function clearAgentContextDraft(userId: string): void {
  try {
    window.sessionStorage.removeItem(storageKey(userId))
    window.sessionStorage.removeItem(legacyStorageKey(userId))
  } catch {
    // Storage cleanup is best-effort when the browser blocks access.
  }
}

export function buildAgentHandoffPrompt(draft: AgentContextDraftV2): string {
  const value = sanitizeDraft(draft.userId, draft)
  const question = value.question.trim() || '请基于这些信息提炼关键变化、机会和风险。'
  const calls = value.items.map((item, index) => `${index + 1}. 调用 get_item，article_id="${item.articleId}"`).join('\n')
  const preference = value.modelPreference === 'fast'
    ? '速度优先'
    : value.modelPreference === 'deep' ? '深度分析' : '自动，由 OpenClaw 决定'
  return [
    '请使用 Inteliscope Remote MCP 完成以下任务。',
    `问题：${question}`,
    `模型偏好：${preference}`,
    '必须按顺序读取上下文，不要把标题或摘要当作完整正文：',
    calls || '（尚未加入上下文条目）',
    '读取完成后，基于工具返回的安全投影回答；无法读取时明确指出对应 article_id。',
  ].join('\n')
}
