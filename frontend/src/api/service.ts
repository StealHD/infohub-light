import type { ApiClient } from './client'
import type {
  AuthStatus,
  AgentDelegation,
  AgentDelegationAccess,
  AgentDelegationCreated,
  AgentDelegationsResponse,
  ApifyActorAlertIncidents,
  ApifyActorAlertSettings,
  ApifyActorAlertSettingsPatch,
  ApifyActorActivePoolUpdate,
  ApifyActorCanaryBatch,
  ApifyActorCanaryBatchRequest,
  ApifyActorCanaryBatchResponse,
  ApifyActorCanaryPlan,
  ApifyActorDiscoveryRun,
  ApifyActorDiscoveryMeasurementRequest,
  ApifyActorDiscoveryMeasurementResponse,
  ApifyActorDiscoverySettings,
  ApifyActorDiscoverySettingsPatch,
  ApifyActorPaidCanaryRequest,
  ApifyActorPaidCanaryResponse,
  ApifyActorPoolGoal,
  ApifyActorPoolCandidateRefresh,
  ApifyActorPoolCandidates,
  ApifyActorRecommendedPoolActivation,
  ApifyActorRouteDetail,
  ApifyActorRoutesResponse,
  ApifyActorSourceCapabilitiesResponse,
  ApifyActorSourceBindingActivation,
  ApifyActorSourceBindingActivationResponse,
  ApifyActorSourceSupport,
  ApifyActorSupportCheckRequest,
  ApifyActorSupportCheckResponse,
  ApifyActorValidationProfileRequest,
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
  NotificationChannel,
  NotificationTarget,
  NotificationTargetCreate,
  NotificationTargetPatch,
  NotificationTargets,
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
  SourceUsage,
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
    subscribe: (sourceId: string) => client.post<{ subscription: Subscription }>(`${resource('/api/catalog/sources', sourceId)}/subscribe`),
    unsubscribe: (subscriptionId: string) => client.delete<{ deleted: boolean }>(resource('/api/me/subscriptions', subscriptionId)),
    updateSubscription: (subscriptionId: string, patch: SubscriptionPatch) => client.patch<Subscription>(resource('/api/me/subscriptions', subscriptionId), patch),
    createSource: (payload: Record<string, unknown>) => client.post<CatalogSource>('/api/catalog/sources', payload),
    updateSource: (sourceId: string, patch: Record<string, unknown>) => client.patch<CatalogSource>(resource('/api/catalog/sources', sourceId), patch),
    sourceUsage: (sourceId: string, signal?: AbortSignal) => client.get<SourceUsage>(`${resource('/api/catalog/sources', sourceId)}/usage`, signal),
    shareSource: (sourceId: string, scope: 'workspace' | 'public') => client.post<SourceShareResult>(`${resource('/api/catalog/sources', sourceId)}/share`, { scope }),
    feedSchedule: (signal?: AbortSignal) => client.get<FeedSchedule>('/api/me/feed-schedule?view=summary', signal),
    updateFeedSchedule: (patch: Pick<FeedSchedule, 'enabled' | 'interval_minutes'>) => client.patch<FeedSchedule>('/api/me/feed-schedule', patch),
    updateSourceSchedule: (subscriptionId: string, patch: Pick<FeedSchedule, 'enabled' | 'interval_minutes'>) => client.patch<FeedSchedule>(`${resource('/api/me/subscriptions', subscriptionId)}/schedule`, patch),
    notificationSettings: (signal?: AbortSignal) => client.get<UserNotificationSettings>('/api/me/notification-settings', signal),
    updateNotificationSettings: (patch: UserNotificationSettingsPatch) => client.patch<UserNotificationSettings>('/api/me/notification-settings', patch),
    notificationTargets: (signal?: AbortSignal) => client.get<NotificationTargets>(
      '/api/notification-targets',
      signal,
    ),
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
    createNotificationTarget: (payload: NotificationTargetCreate) => client.post<NotificationTarget>(
      '/api/notification-targets',
      payload,
    ),
    updateNotificationTarget: (targetId: string, patch: NotificationTargetPatch) => client.patch<NotificationTarget>(
      resource('/api/notification-targets', targetId),
      patch,
    ),
    testNotificationTarget: (targetId: string) => client.post<NotificationTestResult>(
      `${resource('/api/notification-targets', targetId)}/test`,
    ),
    archiveNotificationTarget: (targetId: string) => client.delete<{ target_id: string; archived: boolean }>(
      resource('/api/notification-targets', targetId),
    ),
    testNotificationSettings: (channel?: NotificationChannel) => client.post<NotificationTestResult>(
      '/api/me/notification-settings/test',
      channel ? { channel } : undefined,
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
    reorderApifyKeyPool: (secretIds: string[], expectedGeneration: number) => client.put<ApifyKeyPool>(
      '/api/admin/apify-key-pool/order',
      { secret_ids: secretIds, expected_generation: expectedGeneration },
    ),
    drainApifyKey: (secretId: string) => client.post<ApifyKeyPool>(
      `${resource('/api/admin/apify-key-pool', secretId)}/drain`,
    ),
    apifyActorRoutes: (signal?: AbortSignal) => client.get<ApifyActorRoutesResponse>(
      '/api/admin/apify-routes',
      signal,
    ),
    apifyActorRoute: (routeId: string, signal?: AbortSignal) => client.get<ApifyActorRouteDetail>(
      resource('/api/admin/apify-routes', routeId),
      signal,
    ),
    requestApifyActorSupportCheck: (payload: ApifyActorSupportCheckRequest) => (
      client.post<ApifyActorSupportCheckResponse>('/api/admin/apify-support-checks', payload)
    ),
    apifyActorDiscoveryRun: (runId: string, signal?: AbortSignal) => client.get<ApifyActorDiscoveryRun>(
      resource('/api/admin/apify-discovery-runs', runId),
      signal,
    ),
    apifyActorCanaryPlan: (
      runId: string,
      goal: ApifyActorPoolGoal = 'initial_pool',
      signal?: AbortSignal,
    ) => client.get<ApifyActorCanaryPlan>(
      `${resource('/api/admin/apify-discovery-runs', runId)}/canary-plan?goal=${encodeURIComponent(goal)}`,
      signal,
    ),
    apifyActorPoolCandidates: (
      routeId: string,
      goal: ApifyActorPoolGoal,
      signal?: AbortSignal,
    ) => client.get<ApifyActorPoolCandidates>(
      `${resource('/api/admin/apify-routes', routeId)}/pool-candidates?goal=${encodeURIComponent(goal)}`,
      signal,
    ),
    refreshApifyActorPoolCandidates: (
      routeId: string,
      expectedGeneration: number,
      goal: ApifyActorPoolGoal = 'initial_pool',
    ) => client.post<ApifyActorPoolCandidateRefresh>(
      `${resource('/api/admin/apify-routes', routeId)}/pool-candidates/refresh`,
      { expected_generation: expectedGeneration, goal },
    ),
    reconcileApifyActorValidation: (
      routeId: string,
      expectedGeneration: number,
      candidateId: string,
    ) => client.post<{
      schema_version: 1
      status: string
      semantic_outcome: string
      cost_usd: number | null
      continued: boolean
    }>(
      `${resource('/api/admin/apify-routes', routeId)}/validations/reconcile`,
      { expected_generation: expectedGeneration, candidate_id: candidateId },
    ),
    createApifyActorManualCanaryPlan: (
      runId: string,
      payload: {
        goal: ApifyActorPoolGoal
        candidate_ids: string[]
        candidate_validation_profiles: ApifyActorValidationProfileRequest[]
        expected_generation: number
        target_slot_count: 3
      },
    ) => client.post<ApifyActorCanaryPlan>(
      `${resource('/api/admin/apify-discovery-runs', runId)}/canary-plan`,
      payload,
    ),
    createApifyActorCanaryBatch: (
      runId: string,
      payload: ApifyActorCanaryBatchRequest,
    ) => client.post<ApifyActorCanaryBatchResponse>(
      `${resource('/api/admin/apify-discovery-runs', runId)}/canary-batches`,
      payload,
    ),
    apifyActorCanaryBatch: (batchId: string, signal?: AbortSignal) => client.get<ApifyActorCanaryBatch>(
      resource('/api/admin/apify-canary-batches', batchId),
      signal,
    ),
    canaryApifyActorDiscoveryCandidate: (
      runId: string,
      revisionId: string,
      payload: ApifyActorPaidCanaryRequest,
    ) => client.post<ApifyActorPaidCanaryResponse>(
      `${resource('/api/admin/apify-discovery-runs', runId)}/candidates/${encodeURIComponent(revisionId)}/canary`,
      payload,
    ),
    updateApifyActorRouteActivePool: (
      routeId: string,
      payload: ApifyActorActivePoolUpdate,
    ) => client.put<ApifyActorRouteDetail>(
      `${resource('/api/admin/apify-routes', routeId)}/active-pool`,
      payload,
    ),
    activateApifyActorRouteRecommendedPool: (
      routeId: string,
      payload: ApifyActorRecommendedPoolActivation,
    ) => client.post<ApifyActorRouteDetail>(
      `${resource('/api/admin/apify-routes', routeId)}/active-pool/activate`,
      payload,
    ),
    apifyActorSourceSupport: (sourceId: string, signal?: AbortSignal) => client.get<ApifyActorSourceSupport>(
      `${resource('/api/admin/sources', sourceId)}/apify-support`,
      signal,
    ),
    canaryApifyActorSourceRevision: (
      sourceId: string,
      revisionId: string,
      payload: ApifyActorPaidCanaryRequest,
    ) => client.post<ApifyActorPaidCanaryResponse>(
      `${resource('/api/admin/sources', sourceId)}/apify-validations/${encodeURIComponent(revisionId)}/canary`,
      payload,
    ),
    activateApifyActorSourceBinding: (
      sourceId: string,
      payload: ApifyActorSourceBindingActivation,
    ) => client.post<ApifyActorSourceBindingActivationResponse>(
      `${resource('/api/admin/sources', sourceId)}/apify-binding/activate`,
      payload,
    ),
    apifyActorDiscoverySettings: (signal?: AbortSignal) => client.get<ApifyActorDiscoverySettings>(
      '/api/admin/apify-discovery-settings',
      signal,
    ),
    updateApifyActorDiscoverySettings: (payload: ApifyActorDiscoverySettingsPatch) => (
      client.patch<ApifyActorDiscoverySettings>('/api/admin/apify-discovery-settings', payload)
    ),
    measureApifyActorDiscovery: (payload: ApifyActorDiscoveryMeasurementRequest) => (
      client.post<ApifyActorDiscoveryMeasurementResponse>(
        '/api/admin/apify-discovery-measurements',
        payload,
      )
    ),
    apifyActorAlertSettings: (signal?: AbortSignal) => client.get<ApifyActorAlertSettings>(
      '/api/admin/apify-actor-alert-settings',
      signal,
    ),
    updateApifyActorAlertSettings: (patch: ApifyActorAlertSettingsPatch) => client.patch<ApifyActorAlertSettings>(
      '/api/admin/apify-actor-alert-settings',
      patch,
    ),
    testApifyActorAlertSettings: (channel?: NotificationChannel) => client.post<NotificationTestResult>(
      '/api/admin/apify-actor-alert-settings/test',
      channel ? { channel } : undefined,
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
