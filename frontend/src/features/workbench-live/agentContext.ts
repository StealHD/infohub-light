export type AgentContextDraftV1 = {
  userId: string
  question: string
  itemIds: string[]
}

const storageKey = (userId: string) => `inteliscope.agent-context.v1:${userId}`
const maxItems = 8
const maxQuestionLength = 1200

function emptyDraft(userId: string): AgentContextDraftV1 {
  return { userId, question: '', itemIds: [] }
}

function sanitizeDraft(userId: string, value?: Partial<AgentContextDraftV1> | null): AgentContextDraftV1 {
  const seen = new Set<string>()
  const itemIds = Array.isArray(value?.itemIds)
    ? value.itemIds.filter((id): id is string => typeof id === 'string' && Boolean(id) && !seen.has(id) && Boolean(seen.add(id))).slice(0, maxItems)
    : []
  return {
    userId,
    question: typeof value?.question === 'string' ? value.question.slice(0, maxQuestionLength) : '',
    itemIds,
  }
}

export function readAgentContextDraft(userId: string): AgentContextDraftV1 {
  try {
    return sanitizeDraft(userId, JSON.parse(window.sessionStorage.getItem(storageKey(userId)) || 'null') as Partial<AgentContextDraftV1> | null)
  } catch {
    return emptyDraft(userId)
  }
}

export function writeAgentContextDraft(userId: string, draft: AgentContextDraftV1): AgentContextDraftV1 {
  const next = sanitizeDraft(userId, draft)
  try {
    window.sessionStorage.setItem(storageKey(userId), JSON.stringify(next))
  } catch {
    // A private or restricted browser session may reject storage; keep the in-memory caller state usable.
  }
  return next
}

export function updateAgentContextDraft(draft: AgentContextDraftV1, itemId: string): AgentContextDraftV1 {
  const current = sanitizeDraft(draft.userId, draft)
  const itemIds = current.itemIds.includes(itemId)
    ? current.itemIds.filter((id) => id !== itemId)
    : current.itemIds.length < maxItems ? [...current.itemIds, itemId] : current.itemIds
  return { ...current, itemIds }
}

export function clearAgentContextDraft(userId: string): void {
  try {
    window.sessionStorage.removeItem(storageKey(userId))
  } catch {
    // Storage cleanup is best-effort when the browser blocks access.
  }
}

export function buildAgentHandoffPrompt(draft: AgentContextDraftV1): string {
  const value = sanitizeDraft(draft.userId, draft)
  const question = value.question.trim() || '请基于这些信息提炼关键变化、机会和风险。'
  const calls = value.itemIds.map((itemId, index) => `${index + 1}. 调用 get_item，item_id="${itemId}"`).join('\n')
  return [
    '请使用 Inteliscope Remote MCP 完成以下任务。',
    `问题：${question}`,
    '必须按顺序读取上下文，不要把标题或摘要当作完整正文：',
    calls || '（尚未加入上下文条目）',
    '读取完成后，基于工具返回的安全投影回答；无法读取时明确指出对应 item_id。',
  ].join('\n')
}
