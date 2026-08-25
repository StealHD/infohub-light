import type { ApiClient } from './client'
import { actorOpsV2Api, rsshubAccessKeyApi, systemSettingsApi } from './serviceExtensions'
import type {
  AuthStatus,
  AgentDelegation,
  AgentDelegationAccess,
  AgentDelegationCreated,
  AgentDelegationsResponse,
  ApifyActorAlertIncidents,
  ApifyActorAlertSettings,
  ApifyActorAlertSettingsPatch,
  ApifyActorSourceCapabilitiesResponse,
  ApifyKeyPool,
  CatalogSource,
  ConfigResponse,
  FeedHistory,
  FeedHistoryParams,
  FeedEndMessages,
  FeedSearch,
  FeedSearchParams,
  FeedSchedule,
  FeedSnapshot,
  FeedItem,
  IgnoredFeed,
  Job,
  NotificationTarget,
  NotificationTargetPatch,
  NotificationService,
  NotificationServiceCreate,
  NotificationServicePatch,
  NotificationServices,
  NotificationTestResult,
  SecretQuota,
  SecretRef,
  SavedFeed,
  SourceHealthResponse,
  SourceSummary,
  SourceShareResult,
  SourceTypesResponse,
  StorageArchives,
  StorageOperation,
  StoragePlan,
  StorageSummary,
  Subscription,
  SubscriptionPatch,
  User,
  UserItemState,
  UserNotificationSettings,
  UserNotificationSettingsPatch,
} from './types'

type ListResponse<T, K extends string> = Record<K, T[]>

const resource = (path: string, id: string) => `${path}/${encodeURIComponent(id)}`

export function createServiceApi(client: ApiClient) {
  return {
    ...actorOpsV2Api(client), ...rsshubAccessKeyApi(client), ...systemSettingsApi(client),
    authStatus: (signal?: AbortSignal) => client.get<AuthStatus>('/api/auth/status', signal),
    login: (username: string, password: string) => client.post<AuthStatus>('/api/auth/login', { username, password }),
    logout: () => client.post<AuthStatus>('/api/auth/logout'),

    latestFeed: (signal?: AbortSignal) => client.get<FeedSnapshot>('/api/feed/latest?view=canonical', signal),
    feedEndMessages: (signal?: AbortSignal) => client.get<FeedEndMessages>('/api/feed/end-messages', signal),
    refreshFeedEndMessages: () => client.post<FeedEndMessages>('/api/admin/feed-end-messages/refresh'),
    savedFeed: (limit = 200, offset = 0, signal?: AbortSignal) => client.get<SavedFeed>(
      `/api/feed/saved?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
      signal,
    ),
    ignoredFeed: (limit = 200, offset = 0, signal?: AbortSignal) => client.get<IgnoredFeed>(
      `/api/feed/ignored?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
      signal,
    ),
    feedItem: (articleId: string, signal?: AbortSignal) => client.get<FeedItem>(resource('/api/feed/items', articleId), signal),
    sourceSummary: (articleIds: string[], signal?: AbortSignal) => client.post<SourceSummary>(
      '/api/feed/source-summary',
      { article_ids: articleIds },
      signal,
    ),
    historyFeed: (params: FeedHistoryParams = {}, signal?: AbortSignal) => {
      const search = new URLSearchParams()
      if (params.q?.trim()) search.set('q', params.q.trim())
      if (params.sourceId?.trim()) search.set('source_id', params.sourceId.trim())
      if (params.limit !== undefined) search.set('limit', String(params.limit))
      if (params.offset !== undefined) search.set('offset', String(params.offset))
      const suffix = search.toString()
      return client.get<FeedHistory>(`/api/feed/history${suffix ? `?${suffix}` : ''}`, signal)
    },
    searchFeed: (params: FeedSearchParams, signal?: AbortSignal) => {
      const search = new URLSearchParams({ q: params.q })
      if (params.limit !== undefined) search.set('limit', String(params.limit))
      if (params.cursor) search.set('cursor', params.cursor)
      if (params.submitted) search.set('submitted', 'true')
      return client.get<FeedSearch>(`/api/feed/search?${search.toString()}`, signal)
    },
    sourceHealth: (signal?: AbortSignal) => client.get<SourceHealthResponse>('/api/me/source-health', signal),
    feedJobs: (signal?: AbortSignal) => client.get<ListResponse<Job, 'jobs'>>(
      '/api/jobs?view=summary&scope=me&limit=20&include_active=true&job_type=user_feed_refresh&job_type=source_fetch',
      signal,
    ),
    jobs: (signal?: AbortSignal) => client.get<ListResponse<Job, 'jobs'>>('/api/jobs?view=summary&scope=me&limit=100&include_active=true', signal),
    job: (jobId: string, signal?: AbortSignal) => client.get<Job>(resource('/api/jobs', jobId), signal),
    createFeedRefresh: () => client.post<Job>('/api/jobs/user-feed-refresh', {
      payload: { reason: 'manual_service_refresh' },
      priority: 0,
    }),
    retryJob: (jobId: string) => client.post<Job>(`${resource('/api/jobs', jobId)}/retry`),
    cancelJob: (jobId: string) => client.post<Job>(`${resource('/api/jobs', jobId)}/cancel`),
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
    sourceTypes: (signal?: AbortSignal) => client.get<SourceTypesResponse>('/api/catalog/source-types', signal),
    sourceCapabilities: (signal?: AbortSignal) => client.get<ApifyActorSourceCapabilitiesResponse>(
      '/api/catalog/source-capabilities',
      signal,
    ),
    subscriptions: (signal?: AbortSignal) => client.get<ListResponse<Subscription, 'subscriptions'>>('/api/me/subscriptions?schedule_view=summary', signal),
    subscribe: (sourceId: string) => client.post<{ subscription: Subscription; source_activation?: { state: 'enabled' | 'preparing' | 'disabled'; reason?: string | null; source_enabled?: boolean } | null }>(`${resource('/api/catalog/sources', sourceId)}/subscribe`),
    unsubscribe: (subscriptionId: string) => client.delete<{ deleted: boolean }>(resource('/api/me/subscriptions', subscriptionId)),
    updateSubscription: (subscriptionId: string, patch: SubscriptionPatch) => client.patch<Subscription>(resource('/api/me/subscriptions', subscriptionId), patch),
    createSource: (payload: Record<string, unknown>) => client.post<CatalogSource>('/api/catalog/sources', payload),
    updateSource: (sourceId: string, patch: Record<string, unknown>) => client.patch<CatalogSource>(resource('/api/catalog/sources', sourceId), patch),
    shareSource: (sourceId: string, scope: 'workspace' | 'public') => client.post<SourceShareResult>(`${resource('/api/catalog/sources', sourceId)}/share`, { scope }),
    feedSchedule: (signal?: AbortSignal) => client.get<FeedSchedule>('/api/me/feed-schedule?view=summary', signal),
    updateFeedSchedule: (patch: Pick<FeedSchedule, 'enabled' | 'interval_minutes'>) => client.patch<FeedSchedule>('/api/me/feed-schedule', patch),
    updateSourceSchedule: (subscriptionId: string, patch: Pick<FeedSchedule, 'enabled' | 'interval_minutes'>) => client.patch<FeedSchedule>(`${resource('/api/me/subscriptions', subscriptionId)}/schedule`, patch),
    notificationSettings: (signal?: AbortSignal) => client.get<UserNotificationSettings>('/api/me/notification-settings', signal),
    updateNotificationSettings: (patch: UserNotificationSettingsPatch) => client.patch<UserNotificationSettings>('/api/me/notification-settings', patch),
    notificationServices: (signal?: AbortSignal) => client.get<NotificationServices>(
      '/api/notification-services',
      signal,
    ),
    createNotificationService: (payload: NotificationServiceCreate) => client.post<NotificationService>(
      '/api/admin/notification-services',
      payload,
    ),
    updateNotificationService: (serviceId: string, patch: NotificationServicePatch) => client.patch<NotificationService>(
      resource('/api/admin/notification-services', serviceId),
      patch,
    ),
    testAndEnableNotificationService: (serviceId: string) => client.post<NotificationTestResult>(
      `${resource('/api/admin/notification-services', serviceId)}/test-and-enable`,
    ),
    archiveNotificationService: (serviceId: string) => client.delete<{ service_id: string; archived: boolean }>(
      resource('/api/admin/notification-services', serviceId),
    ),
    updateNotificationTarget: (targetId: string, patch: NotificationTargetPatch) => client.patch<NotificationTarget>(
      resource('/api/notification-targets', targetId),
      patch,
    ),
    archiveNotificationTarget: (targetId: string) => client.delete<{ target_id: string; archived: boolean }>(
      resource('/api/notification-targets', targetId),
    ),
    agentDelegations: (signal?: AbortSignal) => client.get<AgentDelegationsResponse>('/api/me/agent-delegations', signal),
    createAgentDelegation: (
      name: string,
      access: AgentDelegationAccess = 'read',
      diagnosticsScope: 'self' | 'workspace' = 'self',
    ) => client.post<AgentDelegationCreated>(
      '/api/me/agent-delegations',
      { name, access, diagnostics_scope: diagnosticsScope },
    ),
    renameAgentDelegation: (delegationId: string, name: string) => client.patch<AgentDelegation>(resource('/api/me/agent-delegations', delegationId), { name }),
    revokeAgentDelegation: (delegationId: string) => client.delete<{ revoked: boolean }>(resource('/api/me/agent-delegations', delegationId)),
    deleteAgentDelegationRecord: (delegationId: string) => client.delete<{ deleted: boolean }>(
      `${resource('/api/me/agent-delegations', delegationId)}/record`,
    ),

    config: (signal?: AbortSignal) => client.get<ConfigResponse>('/api/config', signal),
    configAction: (action: string, payload: Record<string, unknown>) => client.post<ConfigResponse>('/api/config/action', { action, payload }),
    storageSummary: (signal?: AbortSignal) => client.get<StorageSummary>('/api/admin/storage/summary', signal),
    storageArchives: (signal?: AbortSignal) => client.get<StorageArchives>('/api/admin/storage/archives', signal),
    createStoragePlan: (operation: StorageOperation, payload: Record<string, unknown> = {}) => client.post<StoragePlan>(
      '/api/admin/storage/plans',
      { operation, payload },
    ),
    applyStoragePlan: (planId: string, confirmation = '') => client.post<StoragePlan>(
      `${resource('/api/admin/storage/plans', planId)}/apply`,
      { confirmation },
    ),
    users: (signal?: AbortSignal) => client.get<ListResponse<User, 'users'>>('/api/users', signal),
    createUser: (payload: Record<string, unknown>) => client.post<User>('/api/users', payload),
    updateUser: (userId: string, patch: Record<string, unknown>) => client.patch<User>(resource('/api/users', userId), patch),
    deleteUser: (userId: string) => client.delete<{ deleted: boolean; id: string }>(resource('/api/users', userId)),
    changePassword: (currentPassword: string, newPassword: string) => client.post<{ changed: true }>('/api/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
    secrets: (signal?: AbortSignal) => client.get<ListResponse<SecretRef, 'secrets'>>('/api/admin/secrets', signal),
    secretQuota: (secretId: string, signal?: AbortSignal) => client.get<SecretQuota>(
      `${resource('/api/admin/secrets', secretId)}/quota`,
      signal,
    ),
    apifyKeyPool: (signal?: AbortSignal) => client.get<ApifyKeyPool>('/api/admin/apify-key-pool', signal),
    setApifyValidationKey: (secretId: string | null, expectedGeneration: number) => client.put<ApifyKeyPool>(
      '/api/admin/apify-key-pool/validation-key',
      { secret_id: secretId, expected_generation: expectedGeneration },
    ),
    reorderApifyKeyPool: (secretIds: string[], expectedGeneration: number) => client.put<ApifyKeyPool>(
      '/api/admin/apify-key-pool/order',
      { secret_ids: secretIds, expected_generation: expectedGeneration },
    ),
    drainApifyKey: (secretId: string) => client.post<ApifyKeyPool>(
      `${resource('/api/admin/apify-key-pool', secretId)}/drain`,
    ),
    apifyActorAlertSettings: (signal?: AbortSignal) => client.get<ApifyActorAlertSettings>(
      '/api/admin/apify-actor-alert-settings',
      signal,
    ),
    updateApifyActorAlertSettings: (patch: ApifyActorAlertSettingsPatch) => client.patch<ApifyActorAlertSettings>(
      '/api/admin/apify-actor-alert-settings',
      patch,
    ),
    apifyActorAlertIncidents: (signal?: AbortSignal) => client.get<ApifyActorAlertIncidents>(
      '/api/admin/apify-actor-alert-incidents?limit=20',
      signal,
    ),
    createSecret: (payload: { name: string; kind: string; provider: string; env_name: string; value: string; base_url?: string }) => client.post<SecretRef>('/api/admin/secrets', payload),
    rotateSecret: (secretId: string, value: string) => client.put<SecretRef>(`${resource('/api/admin/secrets', secretId)}/value`, { value }),
    updateSecretConnection: (secretId: string, baseUrl: string) => client.patch<SecretRef>(`${resource('/api/admin/secrets', secretId)}/connection`, { base_url: baseUrl }),
    deleteSecret: (secretId: string) => client.delete<{ deleted: boolean }>(resource('/api/admin/secrets', secretId)),
  }
}

export type ServiceApi = ReturnType<typeof createServiceApi>
