import type { ApiClient } from './client'

export type InformationTrigger = {
  kind: 'each' | 'count' | 'interval' | 'calendar'
  count: number; max_wait_seconds: number | null; interval_seconds: number
  time: string; weekdays: number[]; timezone: string
}
export type InformationModel = { id: string; thinking: string | null }
export type InformationModelCatalog = {
  requested?: boolean
  reason?: 'not_configured' | 'offline' | 'no_authorized_models' | 'catalog_stale' | null
  recovery_action?: 'repair_connection' | 'check_service' | 'review_models' | 'refresh_catalog' | null
  models: { id: string; name: string; thinking_levels: string[] }[]
  status: 'ready' | 'stale' | 'unavailable'; updated_at: string | null
}
export type InformationRuleConfig = {
  schema_version: 2; name: string; source_ids: string[]; target_id: string | null
  requirement: string; trigger: InformationTrigger; model: InformationModel | null
}
export type InformationBatchResult = {
  status: 'matched' | 'not_matched' | 'insufficient'; summary: string; reason: string
  evidence: { article_id: string; quote: string; note: string; title?: string; url?: string }[]
}
export type InformationBatch = {
  range?: { item_count: number; first_event_id: number | null; last_event_id: number | null }
  batch_id?: string; progress?: { total: number; completed: number }
  result?: InformationBatchResult | null; model?: InformationModel
}
export type InformationRule = {
  id: string
  version: number
  state: 'draft' | 'active' | 'paused' | 'archived'
  issue: string | null
  config: InformationRuleConfig
  created_at: string
  updated_at: string
  confirmed_at: string | null
  source_names?: string[]
  pending_count?: number
  next_due?: string | null
  latest_run?: InformationRun | null
}
export type InformationEvidence = { article_id: string; title?: string; status: 'matched' | 'not_matched' | 'insufficient'; reason?: string }
export type InformationRun = InformationBatch & {
  id: string
  version: number
  status: 'pending' | 'judging' | 'matched' | 'not_matched' | 'insufficient' | 'failed' | 'cancelled' | 'quota_wait'
  notification_status: 'not_required' | 'pending' | 'sending' | 'sent' | 'failed' | 'unknown' | 'cancelled' | 'quota_wait'
  reason: string | null
  evidence: InformationEvidence[]
  receipt: { channel: string; verification: string; message_id?: number; provider?: string } | null
  created_at: string
  updated_at: string
}
export type InformationPage<T> = { items: T[]; has_more: boolean; next_offset: number | null }
export type InformationTest = InformationBatch & { preview_id?: string; status?: 'pending' | 'judging' | 'completed' | 'failed' | 'quota_wait'; reason?: string | null; version: number; results: InformationEvidence[]; sends_notification: false; advances_cursor: false }

const base = '/api/me/information-automations'
const path = (id: string) => `${base}/${encodeURIComponent(id)}`
export const informationAutomationApi = (client: ApiClient) => ({
  informationModels: (signal?: AbortSignal) => client.get<InformationModelCatalog>(`${base}/models`, signal),
  refreshInformationModels: () => client.post<InformationModelCatalog>(`${base}/models/refresh`, {}),
  informationRules: (offset = 0, signal?: AbortSignal) => client.get<InformationPage<InformationRule>>(`${base}?limit=50&offset=${offset}`, signal),
  informationRule: (id: string, signal?: AbortSignal) => client.get<InformationRule>(path(id), signal),
  createInformationRule: (config: InformationRuleConfig) => client.post<InformationRule>(base, config),
  updateInformationRule: (id: string, version: number, config: InformationRuleConfig) => client.put<InformationRule>(path(id), { version, config }),
  transitionInformationRule: (id: string, version: number, action: 'enable' | 'pause' | 'archive' | 'restore') => client.post<InformationRule>(`${path(id)}/transition`, { version, action }),
  testInformationRule: (id: string, version: number, article_ids: string[]) => client.post<InformationTest>(`${path(id)}/test`, { version, article_ids }),
  informationTestPreview: (id: string, previewId: string, signal?: AbortSignal) => client.get<InformationTest>(`${path(id)}/test/${encodeURIComponent(previewId)}`, signal),
  informationRuns: (id: string, offset = 0, signal?: AbortSignal) => client.get<InformationPage<InformationRun>>(`${path(id)}/runs?limit=50&offset=${offset}`, signal),
})
