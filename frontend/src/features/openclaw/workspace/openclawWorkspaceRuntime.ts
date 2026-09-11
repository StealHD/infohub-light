import { projectSessionPage, sessionPageParams } from './openclawSessionDirectory'
import { gatewaySupportsMethod, GatewayRequestError, type GatewayEvent } from '../openclawGateway'
import { openClawSessionPreviewParams, projectOpenClawSessionPreview } from '../chat/openclawSessionPreview'
import type { OpenClawLifecycleRefs } from '../lifecycle/openclawLifecycleRefs'
import { OPENCLAW_WORKSPACE_METHODS, OpenClawWorkspaceError, type OpenClawArtifactScope, type OpenClawTaskStatus, type OpenClawWorkspaceController, type OpenClawWorkspaceMethod, type OpenClawWorkspaceProject } from './openclawWorkspaceContracts'
import { projectWorkspaceSessions } from './openclawWorkspaceProjection'

function stateOf(error: unknown): OpenClawWorkspaceError['state'] { return error instanceof GatewayRequestError && (error.code === 'FORBIDDEN' || error.code === 'MISSING_SCOPE') ? 'forbidden' : 'failed' }
function publicRequestMessage(state: OpenClawWorkspaceError['state']): string {
  return state === 'forbidden' ? '当前 OpenClaw 权限不允许此操作。' : 'OpenClaw 暂时无法完成此操作，请重试。'
}
function requireText(value: string, label: string): string { const normalized = value.trim(); if (!normalized) throw new OpenClawWorkspaceError('failed', `${label}不能为空。`); return normalized }
function requireArtifactScope(scope: OpenClawArtifactScope): Record<string, string> {
  const values = Object.entries(scope).filter((entry): entry is [string, string] => typeof entry[1] === 'string' && Boolean(entry[1].trim()))
  if (values.length !== 1) throw new OpenClawWorkspaceError('failed', '产物查询必须指定一个明确的 Session、Run 或 Task 来源。')
  return Object.fromEntries(values.map(([key, value]) => [key, value.trim()]))
}

export function createOpenClawWorkspaceRuntime(refs: OpenClawLifecycleRefs): { controller: OpenClawWorkspaceController; routeEvent(event: GatewayEvent): void } {
  const listeners = new Set<(eventName: string) => void>()
  async function request<T>(method: OpenClawWorkspaceMethod, params: Record<string, unknown>): Promise<T> {
    const client = refs.connection.client
    const generation = refs.connection.generation
    if (!client) throw new OpenClawWorkspaceError('unavailable', 'OpenClaw Gateway 尚未连接。')
    if (!gatewaySupportsMethod(refs.connection.hello, method)) throw new OpenClawWorkspaceError('unsupported', `当前 OpenClaw Gateway 不支持 ${method}。`)
    try {
      const value = await client.request<T>(method, params)
      if (refs.connection.client !== client || refs.connection.generation !== generation) throw new OpenClawWorkspaceError('unavailable', 'OpenClaw 连接已变化，请重试。')
      return value
    } catch (error) {
      if (error instanceof OpenClawWorkspaceError) throw error
      const state = stateOf(error)
      throw new OpenClawWorkspaceError(state, publicRequestMessage(state))
    }
  }
  const controller: OpenClawWorkspaceController = {
    skillScope: () => refs.connection.client && refs.session.agentId ? { agentId: refs.session.agentId, generation: refs.connection.generation } : null,
    invalidateSkills() { for (const listener of listeners) listener('skills.changed') },
    capabilities: () => Object.fromEntries(OPENCLAW_WORKSPACE_METHODS.map((method) => [method, gatewaySupportsMethod(refs.connection.hello, method)])) as ReturnType<OpenClawWorkspaceController['capabilities']>,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    async listSessions() { return projectWorkspaceSessions(await request('sessions.list', { limit: 200 })) },
    async listSessionPage(input = {}) {
      const params = sessionPageParams(input)
      return projectSessionPage(await request('sessions.list', params), params.offset)
    },
    async previewSession(sessionKey) {
      const key = requireText(sessionKey, 'Session')
      const status = projectOpenClawSessionPreview(
        await request('sessions.preview', openClawSessionPreviewParams(key)),
        key,
      )
      if (status !== 'present') throw new OpenClawWorkspaceError('failed', 'OpenClaw 会话已不存在或暂时无法读取。')
      const session = projectWorkspaceSessions(await request('sessions.list', { search: key, limit: 100, archived: 'all' })).find((candidate) => candidate.key === key)
      if (!session) throw new OpenClawWorkspaceError('failed', 'OpenClaw 会话不在当前可信列表中。')
      return session
    },
    async listProjects() { return (await import('./openclawWorkspaceDetails')).projectWorkspaceProjects(await request('projects.list', { includeObserved: false })) },
    async listBranches(project: OpenClawWorkspaceProject) {
      const trusted = (await controller.listProjects()).find((candidate) => candidate.id === project.id && candidate.repoRoot === project.repoRoot)
      if (!trusted) throw new OpenClawWorkspaceError('forbidden', '所选项目不在 Gateway 注册项目中。')
      return (await import('./openclawWorkspaceDetails')).projectWorkspaceBranches(await request('worktrees.branches', { repoRoot: trusted.repoRoot, includeRepositoryStatus: true }))
    },
    async createWorktreeSession() {
      throw new OpenClawWorkspaceError('unsupported', '此工作区不提供 Worktree 任务。')
    },
    async retryWorktreeRun() {
      throw new OpenClawWorkspaceError('unsupported', '此工作区不提供 Worktree 任务。')
    },
    async listTasks(input = {}) { const params = { limit: 50, ...(input.status ? { status: input.status satisfies OpenClawTaskStatus } : {}), ...(input.sessionKey ? { sessionKey: input.sessionKey } : {}), ...(input.cursor ? { cursor: input.cursor } : {}) }; return (await import('./openclawWorkspaceDetails')).projectTaskPage(await request('tasks.list', params), input.sessionKey) },
    async getTask(taskId, sessionKey) { const id = requireText(taskId, 'Task'); const scope = requireText(sessionKey, 'Session'); return (await import('./openclawWorkspaceDetails')).projectTaskDetail(await request('tasks.get', { taskId: id, sessionKey: scope }), id, scope) },
    async cancelTask(taskId, sessionKey, reason) { const id = requireText(taskId, 'Task'); const scope = requireText(sessionKey, 'Session'); await controller.getTask(id, scope); const result = await request<Record<string, unknown>>('tasks.cancel', { taskId: id, sessionKey: scope, ...(reason?.trim() ? { reason: reason.trim() } : {}) }); return result.found === true && result.cancelled === true },
    async listArtifacts(scope) { const trustedScope = requireArtifactScope(scope); return (await import('./openclawWorkspaceDetails')).projectArtifacts(await request('artifacts.list', trustedScope), trustedScope) },
    async getArtifact(artifactId, scope) { const id = requireText(artifactId, 'Artifact'); const trustedScope = requireArtifactScope(scope); return (await import('./openclawWorkspaceDetails')).projectArtifactDetail(await request('artifacts.get', { artifactId: id, ...trustedScope }), { artifactId: id, ...trustedScope }) },
    async downloadArtifact(artifactId, scope) { const id = requireText(artifactId, 'Artifact'); const trustedScope = requireArtifactScope(scope); return (await import('./openclawWorkspaceDetails')).projectArtifactDownload(await request('artifacts.download', { artifactId: id, ...trustedScope }), { artifactId: id, ...trustedScope }) },
    async skillsStatus() {
      const agentId = refs.session.agentId; const sessionKey = refs.session.sessionKey
      const result = (await import('./openclawWorkspaceDetails')).projectSkillsStatus(await request('skills.status', { agentId: agentId ?? undefined }))
      if (refs.session.agentId !== agentId || refs.session.sessionKey !== sessionKey) throw new OpenClawWorkspaceError('unavailable', '当前 Agent 已变化，请重试。')
      return result
    },
  }
  return { controller, routeEvent(event) { if (event.event === 'task' || event.event === 'sessions.changed' || event.event === 'skills.changed' || event.event === 'artifact') for (const listener of listeners) listener(event.event) } }
}
