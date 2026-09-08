import type { ApiClient } from './client'

export type InformationRuleConfig = {
  name: string
  mode: 'keyword' | 'semantic'
  source_ids: string[]
  target_id: string | null
  conditions: { all: string[]; any: string[]; exclude: string[] }
  requirement: string
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
}
export type InformationEvidence = { article_id: string; title?: string; status: 'matched' | 'not_matched' | 'insufficient'; reason?: string }
export type InformationRun = {
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
export type InformationTest = { preview_id?: string; status?: 'pending' | 'judging' | 'completed' | 'failed' | 'quota_wait'; reason?: string | null; version: number; results: InformationEvidence[]; sends_notification: false; advances_cursor: false }

const base = '/api/me/information-automations'
const path = (id: string) => `${base}/${encodeURIComponent(id)}`
export const informationAutomationApi = (client: ApiClient) => ({
  informationRules: (offset = 0, signal?: AbortSignal) => client.get<InformationPage<InformationRule>>(`${base}?limit=50&offset=${offset}`, signal),
  informationRule: (id: string, signal?: AbortSignal) => client.get<InformationRule>(path(id), signal),
  createInformationRule: (config: InformationRuleConfig) => client.post<InformationRule>(base, config),
  updateInformationRule: (id: string, version: number, config: InformationRuleConfig) => client.put<InformationRule>(path(id), { version, config }),
  transitionInformationRule: (id: string, version: number, action: 'enable' | 'pause' | 'archive') => client.post<InformationRule>(`${path(id)}/transition`, { version, action }),
  testInformationRule: (id: string, version: number, article_ids: string[]) => client.post<InformationTest>(`${path(id)}/test`, { version, article_ids }),
  informationTestPreview: (id: string, previewId: string, signal?: AbortSignal) => client.get<InformationTest>(`${path(id)}/test/${encodeURIComponent(previewId)}`, signal),
  informationRuns: (id: string, offset = 0, signal?: AbortSignal) => client.get<InformationPage<InformationRun>>(`${path(id)}/runs?limit=50&offset=${offset}`, signal),
})
