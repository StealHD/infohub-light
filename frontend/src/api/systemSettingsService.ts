import type { ApiClient } from './client'

export type SystemSettingValue = boolean | number

export type SystemSetting = {
  key: string
  env_name: string
  kind: 'boolean' | 'integer'
  default: SystemSettingValue
  category: 'capacity' | 'jobs' | 'retention' | 'storage' | 'acquisition'
  minimum: number | null
  maximum: number | null
  risk: 'low' | 'medium' | 'high'
  effect_timing: string
  description: string
  value: SystemSettingValue
  fallback_value: SystemSettingValue
  source: 'override' | 'environment' | 'default'
  override: SystemSettingValue | null
}

export type SystemSettingsResponse = {
  generation: number
  settings: SystemSetting[]
}

export type SystemSettingChange = {
  key: string
  value: SystemSettingValue | null
}

export type SystemSettingProposal = {
  proposal_id: string
  base_generation: number
  changes: Array<{
    key: string
    env_name: string
    before: SystemSettingValue
    after: SystemSettingValue
    reset: boolean
    risk: string
    effect_timing: string
  }>
  warnings: string[]
  confirmation: string
  expires_at: string
}

export type SystemSettingApplyResult = {
  proposal_id: string
  generation: number
  changed_keys: string[]
}

export function systemSettingsApi(client: ApiClient) {
  return {
    systemSettings: (signal?: AbortSignal) => client.get<SystemSettingsResponse>(
      '/api/admin/system-settings', signal,
    ),
    prepareSystemSettings: (expectedGeneration: number, changes: SystemSettingChange[]) => client.post<SystemSettingProposal>(
      '/api/admin/system-settings/proposals',
      { expected_generation: expectedGeneration, changes },
    ),
    applySystemSettings: (proposalId: string, confirmation: string) => client.post<SystemSettingApplyResult>(
      `/api/admin/system-settings/proposals/${encodeURIComponent(proposalId)}/apply`,
      { confirmation },
    ),
  }
}
