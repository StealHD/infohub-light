import type { OpenClawLifecycleRefs } from '../lifecycle/openclawLifecycleRefs'
import type { OpenClawWorkspaceController, OpenClawWorkspaceSession } from './openclawWorkspaceContracts'
import { deleteWorkspaceSession, sessionDeleteReason } from './openclawSessionDeletion'

const DAY = 86_400_000
type Options = { lastUsedAt(key: string): number; isEnabled(): boolean }
type Request = (method: 'sessions.preview' | 'sessions.delete', params: Record<string, unknown>) => Promise<unknown>

export async function cleanupWorkspaceSessions(refs: OpenClawLifecycleRefs, controller: OpenClawWorkspaceController,
  request: Request, options: Options, onDeleted: (key: string) => void, progress = { lastKey: '' }): Promise<number> {
  const client = refs.connection.client, generation = refs.connection.generation, agent = refs.session.agentId
  const ready = () => Boolean(options.isEnabled() && client && agent && refs.connection.client === client
    && refs.connection.generation === generation && refs.session.agentId === agent && refs.session.sessionKey
    && !refs.session.operation && !refs.run.runId && !refs.run.pendingSend)
  if (!ready() || !controller.capabilities()['sessions.delete']) return 0
  const rows: OpenClawWorkspaceSession[] = []
  // Read the complete bounded directory before deleting so child references are protected.
  for (const archived of [false, true]) {
    let offset = 0
    for (;;) {
      const page = await controller.listSessionPage({ limit: 100, archived, offset })
      if (!ready()) return 0
      rows.push(...page.sessions)
      if (rows.length > 1000) throw new Error('会话目录超过自动清理扫描上限。')
      if (!page.hasMore) break
      if (rows.length >= 1000 || page.nextOffset === undefined) throw new Error('会话目录尚未完整读取。')
      offset = page.nextOffset
    }
  }
  const sessions = [...new Map(rows.map((row) => [row.key, row])).values()]
  const parents = new Set(sessions.map((row) => row.parentSessionKey).filter(Boolean))
  const candidates = sessions.filter((row) => row.key.startsWith(`agent:${agent}:`) && row.activityKnown
    && !row.hasAutomation && !parents.has(row.key) && row.updatedAt && row.updatedAt > 0)
    .sort((a, b) => a.updatedAt! - b.updatedAt!)
  let deleted = 0, checked = 0
  const start = (candidates.findIndex((row) => row.key === progress.lastKey) + 1) % (candidates.length || 1)
  for (const row of [...candidates.slice(start), ...candidates.slice(0, start)]) {
    if (!ready() || deleted >= 10 || checked >= 20) break
    progress.lastKey = row.key
    if (sessionDeleteReason(row, refs.session.sessionKey, true)) continue
    const idle = Date.now() - Math.max(row.updatedAt!, options.lastUsedAt(row.key))
    if (idle < 7 * DAY) continue
    checked += 1
    if (idle < 90 * DAY) {
      const preview = await request('sessions.preview', { keys: [row.key] }) as { previews?: { key?: unknown; status?: unknown }[] }
      if (!Array.isArray(preview?.previews) || preview.previews.length !== 1
        || preview.previews[0].key !== row.key || preview.previews[0].status !== 'empty') continue
    }
    if (!ready() || Date.now() - options.lastUsedAt(row.key) < 7 * DAY) continue
    try {
      await deleteWorkspaceSession(refs, controller, row.key, request, () => onDeleted(row.key), row.updatedAt,
        () => ready() && Date.now() - options.lastUsedAt(row.key) >= (idle < 90 * DAY ? 7 : 90) * DAY)
      deleted += 1
    } catch { break /* A changed or unconfirmed session is retried only on the next bounded pass. */ }
  }
  return deleted
}
