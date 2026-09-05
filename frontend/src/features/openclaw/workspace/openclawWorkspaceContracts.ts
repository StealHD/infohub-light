export const OPENCLAW_WORKSPACE_METHODS = [
  'projects.list', 'sessions.create', 'sessions.list', 'sessions.preview', 'sessions.send', 'worktrees.branches',
  'tasks.list', 'tasks.get', 'tasks.cancel', 'artifacts.list', 'artifacts.get', 'artifacts.download', 'skills.status',
] as const

export const OPENCLAW_ADMIN_METHODS = [
  'skills.upload.begin', 'skills.upload.chunk', 'skills.upload.commit', 'skills.install', 'skills.update',
  'cron.get', 'cron.list', 'cron.status', 'cron.add', 'cron.update', 'cron.remove', 'cron.run', 'cron.runs',
] as const

export type OpenClawWorkspaceMethod = typeof OPENCLAW_WORKSPACE_METHODS[number]
export type OpenClawAdminMethod = typeof OPENCLAW_ADMIN_METHODS[number]
export type OpenClawWorkspaceCapabilityMap = Record<OpenClawWorkspaceMethod, boolean>

export class OpenClawWorkspaceError extends Error {
  constructor(public state: 'unavailable' | 'unsupported' | 'forbidden' | 'failed', message: string) {
    super(message)
    this.name = 'OpenClawWorkspaceError'
  }
}

export type OpenClawWorkspaceProject = { id: string; displayName: string; repoRoot: string; source: string; agentId?: string }
export type OpenClawWorkspaceBranch = { name: string; kind: 'local' | 'remote' }
export type OpenClawWorkspaceBranches = { branches: OpenClawWorkspaceBranch[]; defaultBranch?: string; headBranch?: string; repositoryStatus?: string }
export type OpenClawWorkspaceActor = { type: 'human' | 'agent' | 'system'; id?: string; label?: string }
export type OpenClawWorkspaceSession = {
  key: string
  label: string
  parentSessionKey?: string
  createdVia?: 'operator' | 'agent' | 'claw'
  createdActor?: OpenClawWorkspaceActor
  createdAt?: number
  hasActiveRun: boolean
  worktree?: { id: string; branch: string; repoRoot?: string }
}

export type OpenClawWorktreeRequest = { title: string; prompt: string; projectId: string; projectRepoRoot: string; baseRef: string; worktreeName?: string; idempotencyKey: string }
export type OpenClawWorktreeResult = { sessionKey: string; runStarted: boolean; runId?: string; runError?: string; worktree?: { id: string; path: string; branch: string } }
export type OpenClawRunReceipt = { runId: string }
export const OPENCLAW_TASK_STATUSES = ['queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out'] as const
export type OpenClawTaskStatus = typeof OPENCLAW_TASK_STATUSES[number]
export type OpenClawTask = {
  id: string; status: OpenClawTaskStatus; title?: string; kind?: string; agentId?: string; sessionKey?: string; childSessionKey?: string; runId?: string
  createdAt?: string | number; updatedAt?: string | number; progressSummary?: string; terminalSummary?: string; error?: string; prompt?: string; result?: string
}
export type OpenClawTaskPage = { tasks: OpenClawTask[]; nextCursor?: string }
export type OpenClawArtifactScope = { sessionKey?: string; runId?: string; taskId?: string }
export type OpenClawArtifact = OpenClawArtifactScope & { id: string; type: string; title: string; mimeType?: string; sizeBytes?: number; downloadMode: 'bytes' | 'url' | 'unsupported' }
export type OpenClawArtifactDownload = { artifact: OpenClawArtifact; encoding?: 'base64'; data?: string; url?: string; expiresAt?: string }
export type OpenClawSkill = {
  userInvocable?: boolean; commandVisible?: boolean; modelVisible?: boolean
  key: string; name: string; description?: string; enabled: boolean; eligible: boolean
  missingBins: string[]; missingEnv: string[]; installOptions: string[]
  missingAnyBins?: string[]; missingConfig?: string[]; missingOs?: string[]
  blockedByAllowlist?: boolean; blockedByAgentFilter?: boolean
}
export type OpenClawSkillsStatus = { skills: OpenClawSkill[]; uploadedArchivesAllowed: boolean; maxUploadBytes?: number }

export interface OpenClawWorkspaceController {
  skillScope?(): { agentId: string; generation: number } | null
  capabilities(): OpenClawWorkspaceCapabilityMap
  subscribe(listener: (eventName: string) => void): () => void
  listSessions(): Promise<OpenClawWorkspaceSession[]>
  previewSession(sessionKey: string): Promise<OpenClawWorkspaceSession>
  listProjects(): Promise<OpenClawWorkspaceProject[]>
  listBranches(project: OpenClawWorkspaceProject): Promise<OpenClawWorkspaceBranches>
  createWorktreeSession(request: OpenClawWorktreeRequest): Promise<OpenClawWorktreeResult>
  retryWorktreeRun(sessionKey: string, prompt: string, idempotencyKey: string): Promise<OpenClawRunReceipt>
  listTasks(input?: { status?: OpenClawTaskStatus; sessionKey?: string; cursor?: string }): Promise<OpenClawTaskPage>
  getTask(taskId: string, sessionKey: string): Promise<OpenClawTask>
  cancelTask(taskId: string, sessionKey: string, reason?: string): Promise<boolean>
  listArtifacts(scope: OpenClawArtifactScope): Promise<OpenClawArtifact[]>
  getArtifact(artifactId: string, scope: OpenClawArtifactScope): Promise<OpenClawArtifact>
  downloadArtifact(artifactId: string, scope: OpenClawArtifactScope): Promise<OpenClawArtifactDownload>
  skillsStatus(): Promise<OpenClawSkillsStatus>
}
