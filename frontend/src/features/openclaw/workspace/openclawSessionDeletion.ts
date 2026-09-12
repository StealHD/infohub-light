import type { OpenClawLifecycleRefs } from '../lifecycle/openclawLifecycleRefs'
import { OpenClawWorkspaceError, type OpenClawWorkspaceController, type OpenClawWorkspaceSession } from './openclawWorkspaceContracts'

export function sessionDeleteReason(session: OpenClawWorkspaceSession, current: string | null, supported: boolean): string | null {
  if (!supported) return '当前 Gateway 不支持删除会话'
  if (session.key === current) return '请先切换后删除'
  if (session.key === 'global' || session.key === 'main' || /^agent:[^:]+:main$/.test(session.key)) return '主会话不能删除'
  if (session.hasActiveRun) return '请等待会话运行结束后删除'
  if (session.worktree) return '请先在 OpenClaw 安全清理工作树后再删除会话'
  return null
}

export function verifySessionDeleted(value: unknown, key: string): void {
  const result = value as { ok?: unknown; deleted?: unknown; key?: unknown } | null
  if (!result || result.ok !== true || result.deleted !== true || (result.key !== undefined && result.key !== key)) {
    throw new OpenClawWorkspaceError('failed', 'Gateway 未确认删除。请刷新会话列表核对结果。')
  }
}

export async function deleteWorkspaceSession(refs: OpenClawLifecycleRefs, controller: OpenClawWorkspaceController, sessionKey: string,
  request: (method: 'sessions.delete', params: { key: string; deleteTranscript: boolean }) => Promise<unknown>, onDeleted: () => void): Promise<void> {
  const client = refs.connection.client; const generation = refs.connection.generation
  const session = await controller.previewSession(sessionKey)
  if (refs.connection.client !== client || refs.connection.generation !== generation) throw new OpenClawWorkspaceError('unavailable', 'OpenClaw 连接已变化，请重试。')
  const reason = sessionDeleteReason(session, refs.session.sessionKey, controller.capabilities()['sessions.delete'])
  if (reason || refs.session.operation) throw new OpenClawWorkspaceError('forbidden', reason || '正在切换会话，请稍后重试。')
  const operation = Symbol('delete-session')
  refs.session.operation = operation
  try {
    verifySessionDeleted(await request('sessions.delete', { key: session.key, deleteTranscript: true }), session.key)
    onDeleted()
  } finally { if (refs.session.operation === operation) refs.session.operation = undefined }
}
