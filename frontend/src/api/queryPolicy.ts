export const queryStaleTime = {
  feed: 15_000,
  collection: 30_000,
  catalog: 30_000,
  sourceTypes: 30 * 60_000,
  settings: 5 * 60_000,
  jobs: 30_000,
  jobDetail: 60_000,
} as const
