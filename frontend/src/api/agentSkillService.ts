import type { ApiClient } from './client'

export type AgentSkillCatalogItem = {
  skillKey: string
  name?: string
  description?: string
  disabled?: boolean
  enabled?: boolean
  eligible?: boolean
  blockedByAllowlist?: boolean
  blockedByAgentFilter?: boolean
  missing?: { bins?: string[]; anyBins?: string[]; env?: string[]; config?: string[]; os?: string[] }
}

export type AgentSkillPolicy = {
  revision: number
  allowed_skill_keys: string[]
  sync_state: 'pending' | 'synced' | 'failed'
  sync_in_progress: boolean
  sync_error_code: string | null
  updated_at: string
  synced_at: string | null
}

export type AgentSkillAdministration = { policy: AgentSkillPolicy; skills: AgentSkillCatalogItem[] }

export function agentSkillApi(client: ApiClient) {
  return {
    agentSkills: (signal?: AbortSignal) => client.get<AgentSkillAdministration>('/api/admin/agent-skills', signal),
    updateAgentSkillPolicy: (expectedRevision: number, allowedSkillKeys: string[]) => client.put<{ policy: AgentSkillPolicy }>(
      '/api/admin/agent-skills/policy',
      { expected_revision: expectedRevision, allowed_skill_keys: allowedSkillKeys },
    ),
  }
}
