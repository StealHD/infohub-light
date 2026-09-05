import type { OpenClawClientPort } from '../openclawContracts'

/** Canonical Gateway keys encode the owning Agent; legacy keys retain their default. */
export async function restoredSessionAgent(client: OpenClawClientPort, key: string, defaultAgent: string): Promise<string> {
  const agent = /^agent:([^:]+):/u.exec(key)?.[1]
  if (!agent) return defaultAgent
  const value = await client.request<{ session?: { key?: unknown; agentId?: unknown } }>('sessions.describe', { key })
  if (value.session?.key !== key || (value.session.agentId !== undefined && value.session.agentId !== agent)) throw new Error('OpenClaw 返回了不匹配的会话。')
  return agent
}
