export type FeedQueryOptions = {
  hideDismissed: boolean
  unreadFirst: boolean
}

const userKey = (userId: string) => ['user', userId] as const

export const queryKeys = {
  auth: ['auth'] as const,
  feed: (userId: string, options: FeedQueryOptions) => [
    ...userKey(userId), 'feed', options,
  ] as const,
  history: (userId: string) => [...userKey(userId), 'history'] as const,
  saved: (userId: string) => [...userKey(userId), 'saved'] as const,
  ignored: (userId: string) => [...userKey(userId), 'ignored'] as const,
  feedItem: (userId: string, articleId: string) => [...userKey(userId), 'feed-item', articleId] as const,
  subscriptions: (userId: string) => [...userKey(userId), 'subscriptions'] as const,
  sources: (userId: string) => [...userKey(userId), 'sources'] as const,
  sourceUsage: (userId: string, sourceId: string) => [...userKey(userId), 'source-usage', sourceId] as const,
  sourceTypes: (userId: string) => [...userKey(userId), 'source-types'] as const,
  sourceHealth: (userId: string) => [...userKey(userId), 'source-health'] as const,
  jobs: (userId: string) => [...userKey(userId), 'jobs'] as const,
  job: (userId: string, jobId: string) => [...userKey(userId), 'job', jobId] as const,
  feedSchedule: (userId: string) => [...userKey(userId), 'feed-schedule'] as const,
  agentDelegations: (userId: string) => [...userKey(userId), 'agent-delegations'] as const,
  config: (userId: string) => [...userKey(userId), 'config'] as const,
  users: (userId: string) => [...userKey(userId), 'users'] as const,
  secrets: (userId: string) => [...userKey(userId), 'secrets'] as const,
}
