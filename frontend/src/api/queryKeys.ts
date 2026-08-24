export type FeedQueryOptions = {
  hideDismissed: boolean
  unreadFirst: boolean
}

export type HistoryQueryOptions = {
  q: string
  sourceId: string
  limit: number
}

export type SearchQueryOptions = {
  q: string
  limit: number
  submitted: boolean
}

const userKey = (userId: string) => ['user', userId] as const

export const queryKeys = {
  auth: ['auth'] as const,
  feedRoot: (userId: string) => [...userKey(userId), 'feed'] as const,
  feed: (userId: string, options: FeedQueryOptions) => [
    ...userKey(userId), 'feed', options,
  ] as const,
  feedEndMessages: (userId: string) => [...userKey(userId), 'feed-end-messages'] as const,
  history: (userId: string, options: HistoryQueryOptions = { q: '', sourceId: '', limit: 50 }) => [
    ...userKey(userId), 'history', options,
  ] as const,
  historyRoot: (userId: string) => [...userKey(userId), 'history'] as const,
  search: (userId: string, options: SearchQueryOptions) => [
    ...userKey(userId), 'search', options,
  ] as const,
  searchRoot: (userId: string) => [...userKey(userId), 'search'] as const,
  saved: (userId: string) => [...userKey(userId), 'saved'] as const,
  ignored: (userId: string) => [...userKey(userId), 'ignored'] as const,
  feedItem: (userId: string, articleId: string) => [...userKey(userId), 'feed-item', articleId] as const,
  subscriptions: (userId: string) => [...userKey(userId), 'subscriptions'] as const,
  sources: (userId: string) => [...userKey(userId), 'sources'] as const,
  sourceTypes: (userId: string) => [...userKey(userId), 'source-types'] as const,
  sourceCapabilities: (userId: string) => [
    ...userKey(userId), 'source-capabilities',
  ] as const,
  sourceHealth: (userId: string) => [...userKey(userId), 'source-health'] as const,
  feedJobs: (userId: string) => [...userKey(userId), 'feed-jobs'] as const,
  jobs: (userId: string) => [...userKey(userId), 'jobs'] as const,
  job: (userId: string, jobId: string) => [...userKey(userId), 'job', jobId] as const,
  feedSchedule: (userId: string) => [...userKey(userId), 'feed-schedule'] as const,
  notificationSettings: (userId: string) => [...userKey(userId), 'notification-settings'] as const,
  notificationServices: (userId: string) => [...userKey(userId), 'notification-services'] as const,
  agentDelegations: (userId: string) => [...userKey(userId), 'agent-delegations'] as const,
  systemSettings: (userId: string) => [...userKey(userId), 'system-settings'] as const,
  config: (userId: string) => [...userKey(userId), 'config'] as const,
  storageSummary: (userId: string) => [...userKey(userId), 'storage-summary'] as const,
  storageArchives: (userId: string) => [...userKey(userId), 'storage-archives'] as const,
  users: (userId: string) => [...userKey(userId), 'users'] as const,
  secrets: (userId: string) => [...userKey(userId), 'secrets'] as const,
  apifyKeyPool: (userId: string) => [...userKey(userId), 'apify-key-pool'] as const,
  actorOpsV2Routes: (userId: string) => [
    ...userKey(userId), 'actorops-v2-routes',
  ] as const,
  actorOpsV2Route: (userId: string, routeId: string) => [
    ...userKey(userId), 'actorops-v2-routes', routeId,
  ] as const,
  actorOpsV2Events: (userId: string, sourceId = '') => [
    ...userKey(userId), 'actorops-v2-events', sourceId,
  ] as const,
  apifyActorAlertSettings: (userId: string) => [
    ...userKey(userId), 'apify-actor-alert-settings',
  ] as const,
  apifyActorAlertIncidents: (userId: string) => [
    ...userKey(userId), 'apify-actor-alert-incidents',
  ] as const,
  secretQuota: (userId: string, secretId: string) => [
    ...userKey(userId), 'secret-quota', secretId,
  ] as const,
}
