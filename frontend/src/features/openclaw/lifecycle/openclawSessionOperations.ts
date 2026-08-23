import { projectOpenClawRuntime, type OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'
import { stringOf } from '../chat/openclawProjectionUtils'
import type { OpenClawClientPort } from '../openclawContracts'
import { createOpenClawSessionLabel, isOpenClawSessionLabelConflict } from '../openclawSession'

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
  const create = () => client.request<{ key?: string }>('sessions.create', {
    ...params,
    label: createOpenClawSessionLabel(window.location.host),
  })
  let created: { key?: string }
  try {
    created = await create()
  } catch (error) {
    if (!isOpenClawSessionLabelConflict(error)) throw error
    created = await create()
  }
  const key = stringOf(created.key)
  if (!key) throw new Error('OpenClaw 没有返回新对话标识。')
  return key
}

export async function readOpenClawRuntime(
  client: OpenClawClientPort,
  sessionKey: string,
  agentId: string,
): Promise<OpenClawRuntimeProjection> {
  const [modelsValue, agentsValue, sessionValue] = await Promise.all([
    client.request('models.list', { view: 'configured' }),
    client.request('agents.list', {}),
    client.request('sessions.describe', { key: sessionKey }),
  ])
  return projectOpenClawRuntime(modelsValue, agentsValue, sessionValue, agentId)
}
