import type { OpenClawSessionPage, OpenClawSessionPageRequest } from './openclawWorkspaceContracts'
import { projectWorkspaceSessions } from './openclawWorkspaceProjection'

export function sessionPageParams(input: OpenClawSessionPageRequest): Record<string, unknown> & { offset: number } {
  const limit = input.limit ?? 50
  const offset = input.offset ?? 0
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100 || !Number.isSafeInteger(offset) || offset < 0) throw new Error('会话分页参数无效。')
  return { limit, offset, search: input.search?.trim().slice(0, 512) ?? '', archived: input.archived ?? false, sortBy: 'updatedAt', includeDerivedTitles: true, includeLastMessage: true }
}

export function projectSessionPage(value: unknown, offset: number): OpenClawSessionPage {
  const sessions = projectWorkspaceSessions(value)
  const row = value as Record<string, unknown>
  if (new Set(sessions.map((session) => session.key)).size !== sessions.length) throw new Error('会话目录包含重复标识。')
  const hasMore = row.hasMore === true
  const nextOffset = row.nextOffset
  if (hasMore && (!Number.isSafeInteger(nextOffset) || Number(nextOffset) <= offset)) throw new Error('会话分页响应无效。')
  if (row.totalCount !== undefined && (!Number.isSafeInteger(row.totalCount) || Number(row.totalCount) < 0)) throw new Error('会话计数无效。')
  return { sessions, hasMore, ...(hasMore ? { nextOffset: Number(nextOffset) } : {}), ...(typeof row.totalCount === 'number' ? { totalCount: row.totalCount } : {}) }
}
