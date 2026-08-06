import { describe, expect, it } from 'vitest'

import {
  buildAiPayload,
  buildFeedEndMessagesPayload,
  configuredAiPayload,
  configuredFeedEndMessagesPayload,
  sameSettingsPayload,
} from './settingsAiModel'

function formWith(values: Record<string, string | boolean>): HTMLFormElement {
  const form = document.createElement('form')
  Object.entries(values).forEach(([name, value]) => {
    const input = document.createElement('input')
    input.name = name
    input.type = typeof value === 'boolean' ? 'checkbox' : 'text'
    if (typeof value === 'boolean') input.checked = value
    else input.value = value
    form.append(input)
  })
  return form
}

describe('settingsAiModel', () => {
  it('builds the existing AI settings payload without exposing key values', () => {
    const payload = buildAiPayload({
      form: formWith({ enabled: true, languages: ' zh-CN ', analysis_content_chars: '1200', analysis_comments_chars: '1600', summary_max_chars: '240', analysis_max_output_tokens: '900' }),
      draft: { provider: 'deepseek', model: 'deepseek-v4-flash', apiKeyEnv: 'DEEPSEEK_API_KEY' },
      configured: { enrichment_content_chars: 4800 },
    })

    expect(payload).toEqual({
      enabled: true,
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      api_key_env: 'DEEPSEEK_API_KEY',
      languages: 'zh-CN',
      analysis_content_chars: 1200,
      analysis_comments_chars: 1600,
      summary_max_chars: 240,
      analysis_max_output_tokens: 900,
      enrichment_content_chars: 4800,
    })
    expect(JSON.stringify(payload)).not.toContain('key_value')
  })

  it('keeps configured payload comparisons and feed-end payloads stable', () => {
    const configuredAi = configuredAiPayload({
      configured: { enabled: true, provider: 'openai', model: 'gpt-4o-mini', api_key_env: 'OPENAI_API_KEY', base_url: 'https://legacy.example.test/v1', languages: ['zh'], analysis_content_chars: 1000, analysis_comments_chars: 1500, summary_max_chars: 200, analysis_max_output_tokens: 800 },
      draft: { provider: 'openai', model: 'gpt-4o-mini', apiKeyEnv: 'OPENAI_API_KEY' },
    })
    expect(configuredAi).not.toHaveProperty('base_url')
    expect(sameSettingsPayload(configuredAi, { ...configuredAi })).toBe(true)

    const feedEnd = buildFeedEndMessagesPayload(formWith({ ai_generation_enabled: true, refresh_days: '30', style_preset: 'warm', style_prompt: ' 编辑部语气 ', list_count: '8', ai_key_env: 'DEEPSEEK_API_KEY', model: ' deepseek-v4-flash ' }))
    expect(feedEnd).toEqual({ ai_generation_enabled: true, refresh_days: 30, style_preset: 'warm', style_prompt: '编辑部语气', list_count: 8, ai_key_env: 'DEEPSEEK_API_KEY', model: 'deepseek-v4-flash' })
    expect(configuredFeedEndMessagesPayload({ refresh_days: 30, style_preset: 'warm', style_prompt: '编辑部语气', list_count: 8, ai_generation_enabled: true, ai_key_env: 'DEEPSEEK_API_KEY', model: 'deepseek-v4-flash' })).toEqual(feedEnd)
    expect(configuredFeedEndMessagesPayload({})).toEqual({ ai_generation_enabled: false, refresh_days: 7, style_preset: 'restrained', style_prompt: '', list_count: 12, ai_key_env: '', model: '' })
  })
})
