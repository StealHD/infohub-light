import type { ApiClient } from './client'

export type AgentCleanup = { phase: string; error?: string | null; revision: number }

export type AgentAccessRequest = {
  id: string; state: 'pending' | 'approved' | 'rejected' | 'ready'; revision: number;
  created_at: string; reason?: string | null; phase?: string | null; error?: string | null;
  username?: string; display_name?: string | null; role?: string;
  binding_id?: string | null; cleanup?: AgentCleanup | null;
}

export type AgentConnection = {
  state: 'migration_required' | 'unconfigured' | 'pending_verification' | 'ready' | 'invalid' | 'revoked'
  agent_id?: string | null
  can_connect: boolean
  can_chat: boolean
  can_manage_setup?: boolean
  can_request?: boolean
  request_available?: boolean
  cleanup?: AgentCleanup | null
  access_request?: AgentAccessRequest | null
  setup?: { available: boolean; state: 'idle' | 'running' | 'complete' | 'failed'; phase?: string | null; error?: string | null }
  verification: { deployment: boolean; chat: boolean; own_content: boolean; information_automations: boolean; notifications: boolean }
}

export const agentConnectionApi = (client: ApiClient) => ({
  revokeMemberAgent: (id: string, revision: number) => client.post<AgentCleanup>(`/api/admin/agent-access-requests/${encodeURIComponent(id)}/revoke`, { revision, confirmed: true }),
  retryMemberCleanup: (id: string, revision: number) => client.post<AgentCleanup>(`/api/admin/agent-access-requests/${encodeURIComponent(id)}/cleanup-retry`, { revision, confirmed: true }),
  requestAgentAccess: () => client.post<AgentAccessRequest>('/api/me/agent-access-requests', {}),
  agentAccessRequests: (group: string, search: string, page: number, signal?: AbortSignal) =>
    client.get<{ items: AgentAccessRequest[]; total: number; pending_count: number }>(`/api/admin/agent-access-requests?${new URLSearchParams({ group, search, page: String(page) })}`, signal),
  decideAgentAccess: (id: string, revision: number, decision: 'approved' | 'rejected', reason = '') =>
    client.post<AgentAccessRequest>(`/api/admin/agent-access-requests/${encodeURIComponent(id)}/decision`, { revision, decision, reason }),
  retryAgentAccess: (id: string) => client.post<{ accepted: boolean }>(`/api/admin/agent-access-requests/${encodeURIComponent(id)}/retry`, {}),
  revokeAgentConnection: () => client.delete<AgentConnection>('/api/me/agent-connection'),
  reconnectManagedAgentConnection: () => client.post<NonNullable<AgentConnection['setup']>>('/api/me/agent-connection/setup/reconnect', { confirmed: true }),
  setupManagedAgentConnection: () => client.post<NonNullable<AgentConnection['setup']>>('/api/me/agent-connection/setup/managed', { confirmed: true }),
  agentConnection: (signal?: AbortSignal) => client.get<AgentConnection>('/api/me/agent-connection', signal),
  prepareAgentConnection: () => client.post<AgentConnection>('/api/me/agent-connection/setup', { confirmed: true }),
  agentConnectionBundle: () => client.post<{ archive_base64: string }>('/api/me/agent-connection/setup/bundle', { confirmed: true }),
  activateAgentConnection: (receipt: string) => client.post<AgentConnection>('/api/me/agent-connection/setup/activate', { confirmed: true, receipt_json: receipt }),
})
