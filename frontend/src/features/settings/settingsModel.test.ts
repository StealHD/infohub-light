import { describe, expect, it } from 'vitest'

import type { SecretRef, User } from '../../api/types'
import { DEFAULT_DEEPSEEK_MODEL, DEFAULT_GEMINI_MODEL, aiDefaultsForProvider, canAdministerWorkspace, secretPresentation } from './settingsModel'

const user = (role: User['role']): User => ({ id: role, username: role, role, enabled: true })

describe('settings model', () => {
  it('uses the current stable Gemini Flash model for an empty config', () => {
    expect(DEFAULT_GEMINI_MODEL).toBe('gemini-3.5-flash')
  })

  it('uses the official DeepSeek V4 Flash identifier and key environment', () => {
    expect(DEFAULT_DEEPSEEK_MODEL).toBe('deepseek-v4-flash')
    expect(aiDefaultsForProvider('deepseek')).toEqual({ model: 'deepseek-v4-flash', apiKeyEnv: 'DEEPSEEK_API_KEY' })
  })

  it('allows only owner and admin to mutate workspace settings', () => {
    expect(canAdministerWorkspace(user('owner'))).toBe(true)
    expect(canAdministerWorkspace(user('admin'))).toBe(true)
    expect(canAdministerWorkspace(user('member'))).toBe(false)
    expect(canAdministerWorkspace(user('viewer'))).toBe(false)
  })

  it('builds a secret presentation without any value field', () => {
    const secret: SecretRef = { id: 's1', name: 'Gemini', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', is_set: true, used_by: [] }
    expect(secretPresentation(secret)).toEqual({ name: 'Gemini', provider: 'gemini', status: '已设置', usage: '未引用' })
    expect(JSON.stringify(secretPresentation(secret))).not.toContain('value')
  })

})
