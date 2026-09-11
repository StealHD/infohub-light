import { projectOpenClawRuntime, type OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'
import { stringOf } from '../chat/openclawProjectionUtils'
import type { OpenClawClientPort } from '../openclawContracts'
export type OpenClawSessionCreateParams = {
  agentId: string
  parentSessionKey?: string
  fork?: true
  model?: string
}

export async function createOpenClawSession(
  client: OpenClawClientPort,
  params: OpenClawSessionCreateParams,
): Promise<string> {
  // Gateway assigns the unique key and generates a title after the first turn.
  const created = await client.request<{ key?: string }>('sessions.create', { ...params })
  const key = stringOf(created.key)
  if (!key) throw new Error('OpenClaw 没有返回新对话标识。')
  return key
}

export async function readOpenClawRuntime(
  client: OpenClawClientPort,
  sessionKey: string,
  agentId: string,
  verifyIdentity = false,
  requireRoot = false,
): Promise<OpenClawRuntimeProjection> {
  const [modelsValue, agentsValue, sessionValue] = await Promise.all([
    client.request('models.list', { view: 'configured' }),
    client.request('agents.list', {}),
    client.request('sessions.describe', { key: sessionKey }),
  ])
  if (verifyIdentity) {
    const root = sessionValue as { session?: { key?: unknown; agentId?: unknown; parentSessionKey?: unknown } } | null
    if (root?.session?.key !== sessionKey || (root.session.agentId !== agentId && (requireRoot || root.session.agentId !== undefined))) throw new Error('OpenClaw 返回了不匹配的会话。')
    if (requireRoot && root.session.parentSessionKey != null && root.session.parentSessionKey !== '') throw new Error('OpenClaw 未创建独立对话。')
  }
  return projectOpenClawRuntime(modelsValue, agentsValue, sessionValue, agentId, sessionKey)
}
