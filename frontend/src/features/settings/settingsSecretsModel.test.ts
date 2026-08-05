import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import {
  apifyPoolActionError,
  emptySecretDraft,
  secretCreateErrorMessage,
  secretQuotaStaleTime,
  validateSecretDraft,
} from './settingsSecretsModel'

describe('settingsSecretsModel', () => {
  it('validates secret metadata and write-only values without performing requests', () => {
    expect(validateSecretDraft(emptySecretDraft)).toMatchObject({
      name: 'Key 名称不能为空。',
      provider: 'Provider 不能为空。',
      envName: '环境变量名不能为空。',
      value: 'Key 值不能为空。',
    })
    expect(validateSecretDraft({
      name: 'Apify', kind: 'apify', provider: 'openai', envName: '1BAD_NAME', baseUrl: 'https://gateway.example.test/v1', value: 'line\nvalue',
    })).toMatchObject({
      provider: 'Apify Key 的 Provider 必须是 apify。',
      envName: '环境变量名必须以字母或下划线开头，且只能包含字母、数字和下划线。',
      baseUrl: '只有 AI Key 可以设置 Base URL。',
      value: 'Key 值必须为不含换行或空字符的单行文本。',
    })
    expect(validateSecretDraft({
      name: 'Apify', kind: 'apify', provider: 'apify', envName: 'APIFY_TOKEN', baseUrl: '', value: 'write-only',
    })).toEqual({})
    expect(validateSecretDraft({
      name: 'Gateway', kind: 'ai', provider: 'openai', envName: 'OPENAI_KEY', baseUrl: 'https://gateway.example.test/v1?token=no', value: 'write-only',
    })).toMatchObject({ baseUrl: 'Base URL 必须是无凭据、查询参数或片段的 http/https 地址。' })
  })

  it('keeps API error mapping and the five-minute quota cache policy deterministic', () => {
    expect(secretQuotaStaleTime).toBe(5 * 60 * 1000)
    expect(secretCreateErrorMessage(new ApiError(409, {
      code: 'secret_env_conflict', message: 'conflict',
    }))).toBe('环境变量名已被其他 Key 使用，请更换后重试。')
    expect(apifyPoolActionError(new ApiError(409, {
      code: 'apify_key_pool_generation_conflict', message: 'stale pool',
    }), 'fallback')).toBe('Key 池刚刚发生变化，已刷新最新顺序，请重试。')
  })
})
