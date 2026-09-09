import { describe, expect, it, vi } from 'vitest'

import { createOpenClawLifecycleRefs } from '../lifecycle/openclawLifecycleRefs'
import type { OpenClawClientPort } from '../openclawContracts'
import { OPENCLAW_WORKSPACE_METHODS } from './openclawWorkspaceContracts'
import { createOpenClawWorkspaceRuntime } from './openclawWorkspaceRuntime'

const project = { id: 'project-1', displayName: 'InfoHub', repoRoot: '/srv/infohub', source: 'configured' }

function runtimeWith(request: OpenClawClientPort['request']) {
  const refs = createOpenClawLifecycleRefs()
  refs.session.agentId = 'main'
  refs.session.sessionKey = 'parent-session'
  refs.connection.hello = { features: { methods: [...OPENCLAW_WORKSPACE_METHODS] } }
  refs.connection.client = { connect: vi.fn(), request, close: vi.fn() }
  return { refs, ...createOpenClawWorkspaceRuntime(refs) }
}

describe('OpenClaw Agent Workspace runtime', () => {
  it('derives capabilities only from hello.features.methods', () => {
    const refs = createOpenClawLifecycleRefs()
    refs.connection.hello = { features: { methods: ['sessions.list'] } }
    refs.connection.client = { connect: vi.fn(), request: vi.fn(), close: vi.fn() }
    const { controller } = createOpenClawWorkspaceRuntime(refs)
    expect(controller.capabilities()['sessions.list']).toBe(true)
    expect(controller.capabilities()['sessions.create']).toBe(false)
    expect(controller.createWorktreeSession({ title: 'Task', prompt: 'Do it', projectId: project.id, projectRepoRoot: project.repoRoot, baseRef: 'main', idempotencyKey: 'create-1' })).rejects.toMatchObject({ state: 'unsupported' })
  })

  it('blocks Worktree creation and retry even when the Gateway supports them', async () => {
    const request = vi.fn()
    const { controller } = runtimeWith(request)
    await expect(controller.createWorktreeSession({ title: 'Task', prompt: 'Do it', projectId: project.id, projectRepoRoot: project.repoRoot, baseRef: 'main', idempotencyKey: 'create-2' })).rejects.toMatchObject({ state: 'unsupported' })
    await expect(controller.retryWorktreeRun('existing-child', 'Do it', 'retry-1')).rejects.toMatchObject({ state: 'unsupported' })
    expect(request).not.toHaveBeenCalled()
  })

  it('requires one explicit artifact provenance and routes only public workspace events', async () => {
    const request = vi.fn(async () => ({ artifacts: [] })) as OpenClawClientPort['request']
    const { controller, routeEvent } = runtimeWith(request)
    await expect(controller.listArtifacts({})).rejects.toThrow('明确')
    await expect(controller.listArtifacts({ sessionKey: 'one', taskId: 'two' })).rejects.toThrow('明确')
    const listener = vi.fn(); const unsubscribe = controller.subscribe(listener)
    routeEvent({ type: 'event', event: 'agent', payload: { secret: 'ignored' } })
    routeEvent({ type: 'event', event: 'task' })
    expect(listener).toHaveBeenCalledOnce(); expect(listener).toHaveBeenCalledWith('task')
    unsubscribe()
  })

  it('strictly projects a session preview fixture', async () => {
    const session = { key: 'child-1', displayName: 'Child task', parentSessionKey: 'parent-session', createdVia: 'operator', createdActor: { type: 'human', label: 'Me' }, createdAt: 123, hasActiveRun: true, worktree: { id: 'wt-1', branch: 'openclaw/child' } }
    const request = vi.fn(async (method: string) => method === 'sessions.preview'
      ? { previews: [{ key: 'child-1', status: 'ok', items: [] }] }
      : { sessions: [session] }) as OpenClawClientPort['request']
    const { controller } = runtimeWith(request)
    await expect(controller.previewSession('child-1')).resolves.toMatchObject({ key: 'child-1', label: 'Child task', parentSessionKey: 'parent-session', createdActor: { type: 'human', label: 'Me' }, hasActiveRun: true })
    expect(request).toHaveBeenCalledWith('sessions.preview', { keys: ['child-1'] })
    expect(request).toHaveBeenCalledWith('sessions.list', { search: 'child-1', limit: 100, archived: 'all' })
  })

  it('rejects cross-session task and artifact responses before exposing actions', async () => {
    const request = vi.fn(async (method: string) => {
      if (method === 'tasks.list') return { tasks: [{ id: 'task-1', status: 'running', sessionKey: 'foreign-session' }] }
      if (method === 'artifacts.download') return { artifact: { id: 'artifact-1', type: 'text', title: 'Secret', sessionKey: 'foreign-session', download: { mode: 'bytes' } }, encoding: 'base64', data: 'QQ==' }
      throw new Error(`unexpected ${method}`)
    }) as OpenClawClientPort['request']
    const { controller } = runtimeWith(request)
    await expect(controller.listTasks({ sessionKey: 'trusted-session' })).rejects.toThrow('来源不匹配')
    await expect(controller.downloadArtifact('artifact-1', { sessionKey: 'trusted-session' })).rejects.toThrow('来源不匹配')
  })
})
