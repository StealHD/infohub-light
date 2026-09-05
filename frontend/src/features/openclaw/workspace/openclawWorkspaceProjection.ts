import { OPENCLAW_TASK_STATUSES, type OpenClawArtifact, type OpenClawArtifactDownload, type OpenClawSkill, type OpenClawSkillsStatus, type OpenClawTask, type OpenClawTaskPage, type OpenClawWorkspaceBranches, type OpenClawWorkspaceProject, type OpenClawWorkspaceSession, type OpenClawWorktreeResult } from './openclawWorkspaceContracts'

type UnknownRecord = Record<string, unknown>
function recordOf(value: unknown, label: string): UnknownRecord { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} 返回格式无效。`); return value as UnknownRecord }
function stringOf(value: unknown, maxLength = 512): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = Array.from(value).filter((character) => { const code = character.charCodeAt(0); return (code > 31 && code !== 127) || code === 9 || code === 10 || code === 13 }).join('').trim()
  return normalized ? normalized.slice(0, maxLength) : undefined
}
function numberOf(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) ? value : undefined }
function arrayOf(value: unknown, label: string): unknown[] { if (!Array.isArray(value)) throw new Error(`${label} 返回格式无效。`); return value }
function optionalStringArray(value: unknown): string[] { return Array.isArray(value) ? value.flatMap((candidate) => stringOf(candidate) ?? []) : [] }

export function projectWorkspaceProjects(value: unknown): OpenClawWorkspaceProject[] {
  return arrayOf(recordOf(value, 'projects.list').projects, 'projects.list').map((candidate) => {
    const row = recordOf(candidate, 'projects.list'); const id = stringOf(row.id); const displayName = stringOf(row.displayName); const repoRoot = stringOf(row.repoRoot); const source = stringOf(row.source)
    if (!id || !displayName || !repoRoot || !source) throw new Error('projects.list 缺少可信项目字段。')
    return { id, displayName, repoRoot, source, ...(stringOf(row.agentId) ? { agentId: stringOf(row.agentId) } : {}) }
  })
}

export function projectWorkspaceBranches(value: unknown): OpenClawWorkspaceBranches {
  const root = recordOf(value, 'worktrees.branches')
  const branches = arrayOf(root.branches, 'worktrees.branches').map((candidate) => { const row = recordOf(candidate, 'worktrees.branches'); const name = stringOf(row.name); if (!name || (row.kind !== 'local' && row.kind !== 'remote')) throw new Error('worktrees.branches 包含无效分支。'); return { name, kind: row.kind as 'local' | 'remote' } })
  return { branches, ...(stringOf(root.defaultBranch) ? { defaultBranch: stringOf(root.defaultBranch) } : {}), ...(stringOf(root.headBranch) ? { headBranch: stringOf(root.headBranch) } : {}), ...(stringOf(root.repositoryStatus) ? { repositoryStatus: stringOf(root.repositoryStatus) } : {}) }
}

export function projectWorkspaceSessions(value: unknown): OpenClawWorkspaceSession[] {
  return arrayOf(recordOf(value, 'sessions.list').sessions, 'sessions.list').map((candidate) => {
    const row = recordOf(candidate, 'sessions.list'); const key = stringOf(row.key); if (!key) throw new Error('sessions.list 包含无效会话。')
    const actorValue = row.createdActor && typeof row.createdActor === 'object' ? row.createdActor as UnknownRecord : null; const actorType = actorValue?.type
    const worktreeValue = row.worktree && typeof row.worktree === 'object' ? row.worktree as UnknownRecord : null; const worktreeId = stringOf(worktreeValue?.id); const worktreeBranch = stringOf(worktreeValue?.branch)
    return { key, label: stringOf(row.displayName) ?? stringOf(row.label) ?? key, ...(stringOf(row.parentSessionKey) ? { parentSessionKey: stringOf(row.parentSessionKey) } : {}),
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

function projectTask(value: unknown, includeDetails = false): OpenClawTask {
  const row = recordOf(value, 'tasks'); const id = stringOf(row.id); if (!id || !OPENCLAW_TASK_STATUSES.some((status) => status === row.status)) throw new Error('tasks 返回了无效任务。')
  const strings = Object.fromEntries(['title', 'kind', 'agentId', 'sessionKey', 'childSessionKey', 'runId', 'progressSummary', 'terminalSummary'].flatMap((key) => stringOf(row[key], key.includes('Summary') ? 1_000 : 512) ? [[key, stringOf(row[key], key.includes('Summary') ? 1_000 : 512)]] : []))
  return { id, status: row.status as OpenClawTask['status'], ...strings, ...(stringOf(row.error) ? { error: 'Gateway 报告任务执行失败。' } : {}), ...(typeof row.createdAt === 'string' || typeof row.createdAt === 'number' ? { createdAt: row.createdAt } : {}), ...(typeof row.updatedAt === 'string' || typeof row.updatedAt === 'number' ? { updatedAt: row.updatedAt } : {}), ...(includeDetails && stringOf(row.prompt, 20_000) ? { prompt: stringOf(row.prompt, 20_000) } : {}), ...(includeDetails && stringOf(row.result, 20_000) ? { result: stringOf(row.result, 20_000) } : {}) }
}
function requireTaskScope(task: OpenClawTask, taskId?: string, sessionKey?: string): OpenClawTask {
  if ((taskId && task.id !== taskId) || (sessionKey && task.sessionKey !== sessionKey)) throw new Error('tasks 返回了来源不匹配的任务。')
  return task
}
export function projectTaskPage(value: unknown, sessionKey?: string): OpenClawTaskPage { const root = recordOf(value, 'tasks.list'); return { tasks: arrayOf(root.tasks, 'tasks.list').map((task) => requireTaskScope(projectTask(task), undefined, sessionKey)), ...(stringOf(root.nextCursor) ? { nextCursor: stringOf(root.nextCursor) } : {}) } }
export function projectTaskDetail(value: unknown, taskId?: string, sessionKey?: string): OpenClawTask { return requireTaskScope(projectTask(recordOf(value, 'tasks.get').task, true), taskId, sessionKey) }

function projectArtifact(value: unknown): OpenClawArtifact {
  const row = recordOf(value, 'artifacts'); const download = recordOf(row.download, 'artifacts'); const id = stringOf(row.id); const type = stringOf(row.type); const title = stringOf(row.title)
  if (!id || !type || !title || (download.mode !== 'bytes' && download.mode !== 'url' && download.mode !== 'unsupported')) throw new Error('artifacts 返回了无效产物。')
  return { id, type, title, downloadMode: download.mode, ...(stringOf(row.mimeType) ? { mimeType: stringOf(row.mimeType) } : {}), ...(numberOf(row.sizeBytes) !== undefined ? { sizeBytes: numberOf(row.sizeBytes) } : {}), ...(stringOf(row.sessionKey) ? { sessionKey: stringOf(row.sessionKey) } : {}), ...(stringOf(row.runId) ? { runId: stringOf(row.runId) } : {}), ...(stringOf(row.taskId) ? { taskId: stringOf(row.taskId) } : {}) }
}
function requireArtifactScope(artifact: OpenClawArtifact, expected?: { artifactId?: string; sessionKey?: string; runId?: string; taskId?: string }): OpenClawArtifact {
  if (expected?.artifactId && artifact.id !== expected.artifactId) throw new Error('artifacts 返回了不匹配的产物。')
  for (const key of ['sessionKey', 'runId', 'taskId'] as const) if (expected?.[key] && artifact[key] !== expected[key]) throw new Error('artifacts 返回了来源不匹配的产物。')
  return artifact
}
export function projectArtifacts(value: unknown, expected?: { sessionKey?: string; runId?: string; taskId?: string }): OpenClawArtifact[] { return arrayOf(recordOf(value, 'artifacts.list').artifacts, 'artifacts.list').map((row) => requireArtifactScope(projectArtifact(row), expected)) }
export function projectArtifactDetail(value: unknown, expected?: { artifactId?: string; sessionKey?: string; runId?: string; taskId?: string }): OpenClawArtifact { return requireArtifactScope(projectArtifact(recordOf(value, 'artifacts.get').artifact), expected) }
export function projectArtifactDownload(value: unknown, expected?: { artifactId?: string; sessionKey?: string; runId?: string; taskId?: string }): OpenClawArtifactDownload {
  const root = recordOf(value, 'artifacts.download')
  const artifact = requireArtifactScope(projectArtifact(root.artifact), expected)
  if (artifact.downloadMode === 'bytes') {
    const data = stringOf(root.data, 70 * 1024 * 1024)
    if (root.encoding !== 'base64' || !data) throw new Error('artifacts.download 没有返回可信字节内容。')
    return { artifact, encoding: 'base64', data }
  }
  if (artifact.downloadMode === 'url') {
    const url = stringOf(root.url, 4_096); const expiresAt = stringOf(root.expiresAt, 128)
    if (!url || !expiresAt) throw new Error('artifacts.download 没有返回可信临时地址。')
    return { artifact, url, expiresAt }
  }
  throw new Error('Artifact 不支持下载。')
}

function projectSkill(candidate: unknown): OpenClawSkill {
  const row = recordOf(candidate, 'skills.status')
  const key = stringOf(row.skillKey) ?? stringOf(row.key)
  const enabled = typeof row.disabled === 'boolean' ? !row.disabled : row.enabled
  if (!key || typeof enabled !== 'boolean' || typeof row.eligible !== 'boolean'
    || (row.disabled !== undefined && typeof row.disabled !== 'boolean')
    || (row.enabled !== undefined && row.enabled !== enabled)) throw new Error('Skills 状态格式无效，请刷新重试。')
  const missing = row.missing && typeof row.missing === 'object' ? row.missing as UnknownRecord : {}
  return {
    userInvocable: row.userInvocable === true && typeof row.name === 'string' && row.name === stringOf(row.name),
    commandVisible: row.commandVisible === true, modelVisible: row.modelVisible === true,
    key, name: stringOf(row.name) ?? key, description: stringOf(row.description, 1_000), enabled, eligible: row.eligible,
    blockedByAllowlist: row.blockedByAllowlist === true, blockedByAgentFilter: row.blockedByAgentFilter === true,
    missingBins: optionalStringArray(missing.bins ?? row.missingBins), missingEnv: optionalStringArray(missing.env ?? row.missingEnv),
    missingAnyBins: optionalStringArray(missing.anyBins), missingConfig: optionalStringArray(missing.config), missingOs: optionalStringArray(missing.os),
    installOptions: Array.isArray(row.install) ? row.install.flatMap((option) => stringOf(recordOf(option, 'skills.status').label) ?? []) : optionalStringArray(row.installOptions),
  }
}

export function projectSkillsStatus(value: unknown): OpenClawSkillsStatus {
  const root = recordOf(value, 'skills.status'); const install = root.install && typeof root.install === 'object' ? root.install as UnknownRecord : {}
  const skills = arrayOf(root.skills, 'skills.status').map(projectSkill)
  return { skills, uploadedArchivesAllowed: install.allowUploadedArchives === true || root.allowUploadedArchives === true, ...(numberOf(install.maxUploadBytes ?? root.maxUploadBytes) !== undefined ? { maxUploadBytes: numberOf(install.maxUploadBytes ?? root.maxUploadBytes) } : {}) }
}
