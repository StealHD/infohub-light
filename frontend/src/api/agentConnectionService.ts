import type { ApiClient } from './client'

export type AgentConnection = {
  state: 'migration_required' | 'unconfigured' | 'pending_verification' | 'ready' | 'invalid' | 'revoked'
  agent_id?: string | null
  can_connect: boolean
  can_chat: boolean
  can_manage_setup?: boolean
  verification: { deployment: boolean; chat: boolean; own_content: boolean; information_automations: boolean; notifications: boolean }
}

export const agentConnectionApi = (client: ApiClient) => ({
  agentConnection: (signal?: AbortSignal) => client.get<AgentConnection>('/api/me/agent-connection', signal),
  prepareAgentConnection: () => client.post<AgentConnection>('/api/me/agent-connection/setup', { confirmed: true }),
  agentConnectionBundle: () => client.post<{ archive_base64: string }>('/api/me/agent-connection/setup/bundle', { confirmed: true }),
  activateAgentConnection: (receipt: string) => client.post<AgentConnection>('/api/me/agent-connection/setup/activate', { confirmed: true, receipt_json: receipt }),
})
