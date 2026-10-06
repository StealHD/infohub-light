import type { ApiClient, ApiErrorBody } from './client'

export type FeedTranslation = {
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed'
  job_id: string | null
  translation: string | null
  scope: 'body' | 'excerpt'
  source_truncated: boolean
  cached: boolean
  expires_at: string | null
  error: ApiErrorBody | null
}

export function feedTranslationApi(client: ApiClient) {
  const path = (id: string) => `/api/feed/items/${encodeURIComponent(id)}/translation`
  return {
    feedTranslation: (id: string, signal?: AbortSignal) => client.get<FeedTranslation>(path(id), signal),
    translateFeedItem: (id: string, requestId: string) => client.post<FeedTranslation>(path(id), { request_id: requestId }),
  }
}
