export type AiSettingsSection = 'ai' | 'feed_end_messages'

export type AiDraft = {
  provider: string
  model: string
  apiKeyEnv: string
}

export type AiSettingsBundle = Partial<Record<AiSettingsSection, Record<string, unknown>>>

export const aiSettingsOrder: readonly AiSettingsSection[] = ['ai', 'feed_end_messages']

export const recordOf = (value: unknown): Record<string, unknown> => value && typeof value === 'object'
  ? value as Record<string, unknown>
  : {}

export const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()

export const sameSettingsPayload = (left: Record<string, unknown>, right: Record<string, unknown>) => (
  JSON.stringify(left) === JSON.stringify(right)
)

export function buildAiPayload({ form, draft, configured }: {
  form: HTMLFormElement
  draft: AiDraft
  configured: Record<string, unknown>
}): Record<string, unknown> {
  const data = new FormData(form)
  return {
    enabled: data.has('enabled'),
    provider: draft.provider,
    model: draft.model,
    api_key_env: draft.apiKeyEnv,
    languages: inputValue(data, 'languages') || 'zh',
    analysis_content_chars: Number(data.get('analysis_content_chars')),
    analysis_comments_chars: Number(data.get('analysis_comments_chars')),
    summary_max_chars: Number(data.get('summary_max_chars')),
    analysis_max_output_tokens: Number(data.get('analysis_max_output_tokens')),
    enrichment_content_chars: Number(configured.enrichment_content_chars ?? 4000),
  }
}

export function configuredAiPayload({ configured, draft }: {
  configured: Record<string, unknown>
  draft: AiDraft
}): Record<string, unknown> {
  return {
    enabled: configured.enabled !== false,
    provider: draft.provider,
    model: draft.model,
    api_key_env: draft.apiKeyEnv,
    languages: Array.isArray(configured.languages) ? configured.languages.join(',').trim() || 'zh' : 'zh',
    analysis_content_chars: Number(configured.analysis_content_chars ?? 1000),
    analysis_comments_chars: Number(configured.analysis_comments_chars ?? 1500),
    summary_max_chars: Number(configured.summary_max_chars ?? 200),
    analysis_max_output_tokens: Number(configured.analysis_max_output_tokens ?? 800),
    enrichment_content_chars: Number(configured.enrichment_content_chars ?? 4000),
  }
}

export function buildFeedEndMessagesPayload(form: HTMLFormElement): Record<string, unknown> {
  const data = new FormData(form)
  return {
    ai_generation_enabled: data.has('ai_generation_enabled'),
    refresh_days: Number(data.get('refresh_days')),
    style_preset: String(data.get('style_preset') || 'restrained'),
    style_prompt: inputValue(data, 'style_prompt'),
    list_count: Number(data.get('list_count')),
    ai_key_env: inputValue(data, 'ai_key_env'),
    model: inputValue(data, 'model'),
  }
}

export function configuredFeedEndMessagesPayload(configured: Record<string, unknown>): Record<string, unknown> {
  return {
    ai_generation_enabled: configured.ai_generation_enabled === true,
    refresh_days: Number(configured.refresh_days ?? 7),
    style_preset: String(configured.style_preset ?? 'restrained'),
    style_prompt: String(configured.style_prompt ?? '').trim(),
    list_count: Number(configured.list_count ?? 12),
    ai_key_env: String(configured.ai_key_env ?? '').trim(),
    model: String(configured.model ?? '').trim(),
  }
}
