import type { ApiClient } from './client'
import type {
  AuthStatus,
  AgentDelegation,
  AgentDelegationAccess,
  AgentDelegationCreated,
  AgentDelegationsResponse,
  CatalogSource,
  ConfigResponse,
  FeedHistory,
  FeedSchedule,
  FeedSnapshot,
  FeedItem,
  IgnoredFeed,
  Job,
  SecretRef,
  SavedFeed,
  SourceHealthResponse,
  SourceShareResult,
  SourceTypeDefinition,
  SourceUsage,
  Subscription,
  SubscriptionPatch,
  User,
  UserItemState,
} from './types'

type ListResponse<T, K extends string> = Record<K, T[]>

const resource = (path: string, id: string) => `${path}/${encodeURIComponent(id)}`

export function createServiceApi(client: ApiClient) {
  return {
    authStatus: (signal?: AbortSignal) => client.get<AuthStatus>('/api/auth/status', signal),
    login: (username: string, password: string) => client.post<AuthStatus>('/api/auth/login', { username, password }),
    logout: () => client.post<AuthStatus>('/api/auth/logout'),

    latestFeed: (signal?: AbortSignal) => client.get<FeedSnapshot>('/api/feed/latest', signal),
    savedFeed: (limit = 200, offset = 0, signal?: AbortSignal) => client.get<SavedFeed>(
      `/api/feed/saved?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
      signal,
    ),
    ignoredFeed: (limit = 200, offset = 0, signal?: AbortSignal) => client.get<IgnoredFeed>(
      `/api/feed/ignored?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
      signal,
    ),
    feedItem: (articleId: string, signal?: AbortSignal) => client.get<FeedItem>(resource('/api/feed/items', articleId), signal),
    historyFeed: (signal?: AbortSignal) => client.get<FeedHistory>('/api/feed/history', signal),
    sourceHealth: (signal?: AbortSignal) => client.get<SourceHealthResponse>('/api/me/source-health', signal),
    jobs: (signal?: AbortSignal) => client.get<ListResponse<Job, 'jobs'>>('/api/jobs?limit=100', signal),
    job: (jobId: string, signal?: AbortSignal) => client.get<Job>(resource('/api/jobs', jobId), signal),
    createFeedRefresh: () => client.post<Job>('/api/jobs/user-feed-refresh', {
      payload: { reason: 'manual_service_refresh' },
      priority: 0,
    }),
    retryJob: (jobId: string) => client.post<Job>(`${resource('/api/jobs', jobId)}/retry`),
    createSourceTest: (sourceId: string, subscriptionId?: string) => client.post<Job>('/api/jobs/source-test', {
      source_id: sourceId,
      subscription_id: subscriptionId,
      payload: { reason: 'manual_source_test' },
      priority: 0,
    }),
    createSourceFetch: (sourceId: string, subscriptionId: string) => client.post<Job>('/api/jobs/source-fetch', {
      source_id: sourceId,
      subscription_id: subscriptionId,
      payload: { reason: 'manual_source_fetch' },
      priority: 0,
    }),
    updateItemState: (articleId: string, patch: Partial<UserItemState>) => client.patch<UserItemState>(
      `${resource('/api/me/items', articleId)}/state`, patch,
    ),

    sources: (includeDisabled = false, signal?: AbortSignal) => client.get<ListResponse<CatalogSource, 'sources'>>(
      includeDisabled ? '/api/catalog/sources?include_disabled=true' : '/api/catalog/sources',
      signal,
    ),
    sourceTypes: (signal?: AbortSignal) => client.get<ListResponse<SourceTypeDefinition, 'source_types'>>('/api/catalog/source-types', signal),
    subscriptions: (signal?: AbortSignal) => client.get<ListResponse<Subscription, 'subscriptions'>>('/api/me/subscriptions', signal),
    subscribe: (sourceId: string) => client.post<{ subscription: Subscription }>(`${resource('/api/catalog/sources', sourceId)}/subscribe`),
    unsubscribe: (subscriptionId: string) => client.delete<{ deleted: boolean }>(resource('/api/me/subscriptions', subscriptionId)),
    updateSubscription: (subscriptionId: string, patch: SubscriptionPatch) => client.patch<Subscription>(resource('/api/me/subscriptions', subscriptionId), patch),
    createSource: (payload: Record<string, unknown>) => client.post<CatalogSource>('/api/catalog/sources', payload),
    updateSource: (sourceId: string, patch: Record<string, unknown>) => client.patch<CatalogSource>(resource('/api/catalog/sources', sourceId), patch),
    sourceUsage: (sourceId: string, signal?: AbortSignal) => client.get<SourceUsage>(`${resource('/api/catalog/sources', sourceId)}/usage`, signal),
    shareSource: (sourceId: string, scope: 'workspace' | 'public') => client.post<SourceShareResult>(`${resource('/api/catalog/sources', sourceId)}/share`, { scope }),
    feedSchedule: (signal?: AbortSignal) => client.get<FeedSchedule>('/api/me/feed-schedule', signal),
    updateFeedSchedule: (patch: Pick<FeedSchedule, 'enabled' | 'interval_minutes'>) => client.patch<FeedSchedule>('/api/me/feed-schedule', patch),
    updateSourceSchedule: (subscriptionId: string, patch: Pick<FeedSchedule, 'enabled' | 'interval_minutes'>) => client.patch<FeedSchedule>(`${resource('/api/me/subscriptions', subscriptionId)}/schedule`, patch),

    agentDelegations: (signal?: AbortSignal) => client.get<AgentDelegationsResponse>('/api/me/agent-delegations', signal),
    createAgentDelegation: (name: string, access: AgentDelegationAccess = 'read') => client.post<AgentDelegationCreated>(
      '/api/me/agent-delegations',
      { name, access },
    ),
    renameAgentDelegation: (delegationId: string, name: string) => client.patch<AgentDelegation>(resource('/api/me/agent-delegations', delegationId), { name }),
    revokeAgentDelegation: (delegationId: string) => client.delete<{ revoked: boolean }>(resource('/api/me/agent-delegations', delegationId)),

    config: (signal?: AbortSignal) => client.get<ConfigResponse>('/api/config', signal),
    configAction: (action: string, payload: Record<string, unknown>) => client.post<ConfigResponse>('/api/config/action', { action, payload }),
    users: (signal?: AbortSignal) => client.get<ListResponse<User, 'users'>>('/api/users', signal),
    createUser: (payload: Record<string, unknown>) => client.post<User>('/api/users', payload),
    updateUser: (userId: string, patch: Record<string, unknown>) => client.patch<User>(resource('/api/users', userId), patch),
    changePassword: (currentPassword: string, newPassword: string) => client.post<{ changed: true }>('/api/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
    secrets: (signal?: AbortSignal) => client.get<ListResponse<SecretRef, 'secrets'>>('/api/admin/secrets', signal),
    createSecret: (payload: { name: string; kind: string; provider: string; env_name: string; value: string }) => client.post<SecretRef>('/api/admin/secrets', payload),
    rotateSecret: (secretId: string, value: string) => client.put<SecretRef>(`${resource('/api/admin/secrets', secretId)}/value`, { value }),
    deleteSecret: (secretId: string) => client.delete<{ deleted: boolean }>(resource('/api/admin/secrets', secretId)),
  }
}

export type ServiceApi = ReturnType<typeof createServiceApi>
