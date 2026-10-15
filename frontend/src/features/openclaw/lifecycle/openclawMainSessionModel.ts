import type { OpenClawClientPort } from '../openclawContracts'
import { recordOf } from '../chat/openclawProjectionUtils'
import { projectOpenClawRuntime, type OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'

// Dashboard sessions can link to main without copying its transcript.
export function isIndependentConversation(session: Record<string, unknown>, agentId: string): boolean {
  if (session.forkedFromParent || session.forkSource) return false
  return session.parentSessionKey == null || session.parentSessionKey === ''
    || (session.key !== `agent:${agentId}:main` && session.parentSessionKey === `agent:${agentId}:main`)
}

export async function verifyMainSessionModel(client: OpenClawClientPort, sessionValue: unknown, agentId: string,
  projection: OpenClawRuntimeProjection, models: unknown, agents: unknown): Promise<void> {
  const session = recordOf(recordOf(sessionValue)?.session)
  if (!session || !isIndependentConversation(session, agentId) || !session.parentSessionKey
    || projection.selection.modelSafety !== 'unsafe_fork') return
  const key = String(session.parentSessionKey)
  try {
    // Listing first also establishes ownership in the managed relay.
    const directory = recordOf(await client.request('sessions.list', { search: key, limit: 100, archived: 'all' }))
    if (!directory || !Array.isArray(directory.sessions) || directory.hasMore === true) return
    const matches = directory.sessions.map(recordOf).filter((row) => row?.key === key)
    if (!matches.length) {
      if (directory.sessions.length === 0 && directory.totalCount === 0) projection.selection.modelSafety = 'verified'
      return
    }
    if (matches.length !== 1) return
    const parentValue = await client.request('sessions.describe', { key })
    const parent = recordOf(recordOf(parentValue)?.session)
    if (!parent || parent.key !== key || (parent.agentId !== undefined && parent.agentId !== agentId) || parent.parentSessionKey) return
    const runtime = projectOpenClawRuntime(models, agents, parentValue, agentId, key)
    if (runtime.selection.modelSafety === 'verified' && runtime.selection.modelId === projection.selection.modelId) {
      projection.selection.modelSafety = 'verified'
    }
  } catch { /* Preserve the safety warning when inheritance cannot be verified. */ }
}
