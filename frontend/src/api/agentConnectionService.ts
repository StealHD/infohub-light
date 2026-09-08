import type { ApiClient } from './client'

export type AgentConnection = {
  state: 'migration_required' | 'unconfigured' | 'pending_verification' | 'ready' | 'invalid' | 'revoked'
  agent_id?: string | null
  can_connect: boolean
  can_chat: boolean
  verification: { deployment: boolean; chat: boolean; own_content: boolean; information_automations: boolean; notifications: boolean }
}

export const agentConnectionApi = (client: ApiClient) => ({
  agentConnection: (signal?: AbortSignal) => client.get<AgentConnection>('/api/me/agent-connection', signal),
})
