import { type OpenClawWorkspaceSession, type OpenClawWorktreeResult } from './openclawWorkspaceContracts'

import { recordOf, stringOf, numberOf, arrayOf, type UnknownRecord } from './openclawWorkspaceValues'

export function projectWorkspaceSessions(value: unknown): OpenClawWorkspaceSession[] {
  return arrayOf(recordOf(value, 'sessions.list').sessions, 'sessions.list').map((candidate) => {
    const row = recordOf(candidate, 'sessions.list'); const key = stringOf(row.key); if (!key || key !== row.key) throw new Error('sessions.list 包含无效会话。')
    const actorValue = row.createdActor && typeof row.createdActor === 'object' ? row.createdActor as UnknownRecord : null; const actorType = actorValue?.type
    const worktreeValue = row.worktree && typeof row.worktree === 'object' ? row.worktree as UnknownRecord : null; const worktreeId = stringOf(worktreeValue?.id); const worktreeBranch = stringOf(worktreeValue?.branch)
    return { key, label: stringOf(row.label) ?? stringOf(row.displayName) ?? key,
      ...Object.fromEntries(['displayName', 'derivedTitle', 'lastMessagePreview', 'agentId'].flatMap((field) => stringOf(row[field]) ? [[field, stringOf(row[field])]] : [])),
      ...(numberOf(row.updatedAt) !== undefined ? { updatedAt: numberOf(row.updatedAt) } : {}),
      ...(typeof row.archived === 'boolean' ? { archived: row.archived } : {}), ...(stringOf(row.parentSessionKey) ? { parentSessionKey: stringOf(row.parentSessionKey) } : {}),
      ...(row.createdVia === 'operator' || row.createdVia === 'agent' || row.createdVia === 'claw' ? { createdVia: row.createdVia } : {}),
      ...(actorValue && (actorType === 'human' || actorType === 'agent' || actorType === 'system') ? { createdActor: { type: actorType, ...(stringOf(actorValue.id) ? { id: stringOf(actorValue.id) } : {}), ...(stringOf(actorValue.label) ? { label: stringOf(actorValue.label) } : {}) } } : {}),
      ...(numberOf(row.createdAt) !== undefined ? { createdAt: numberOf(row.createdAt) } : {}), hasActiveRun: row.hasActiveRun === true,
      ...(worktreeId && worktreeBranch ? { worktree: { id: worktreeId, branch: worktreeBranch, ...(stringOf(worktreeValue?.repoRoot) ? { repoRoot: stringOf(worktreeValue?.repoRoot) } : {}) } } : {}) }
  })
}

export function projectWorktreeResult(value: unknown): OpenClawWorktreeResult {
  const root = recordOf(value, 'sessions.create'); const sessionKey = stringOf(root.key); if (root.ok !== true || !sessionKey) throw new Error('sessions.create 没有返回已创建会话。')
  if (typeof root.runStarted !== 'boolean') throw new Error('sessions.create 没有返回明确的任务启动状态。')
  const worktreeValue = root.worktree && typeof root.worktree === 'object' ? root.worktree as UnknownRecord : null; const errorValue = root.runError && typeof root.runError === 'object' ? root.runError as UnknownRecord : null
  const id = stringOf(worktreeValue?.id); const path = stringOf(worktreeValue?.path); const branch = stringOf(worktreeValue?.branch)
  const runId = stringOf(root.runId)
  if (root.runStarted && !runId) throw new Error('sessions.create 没有返回可信的 Run 回执。')
  return { sessionKey, runStarted: root.runStarted, ...(runId ? { runId } : {}), ...(stringOf(errorValue?.message) ? { runError: 'Worktree 已创建，但 Gateway 未能启动任务。' } : {}), ...(id && path && branch ? { worktree: { id, path, branch } } : {}) }
}
