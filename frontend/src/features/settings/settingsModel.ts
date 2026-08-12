import type { SecretRef, User } from '../../api/types'

export const DEFAULT_GEMINI_MODEL = 'gemini-3.5-flash'
export const DEFAULT_DEEPSEEK_MODEL = 'deepseek-v4-flash'

const providerDefaults: Record<string, { model: string; apiKeyEnv: string }> = {
  gemini: { model: DEFAULT_GEMINI_MODEL, apiKeyEnv: 'GOOGLE_API_KEY' },
  openai: { model: 'gpt-5-mini', apiKeyEnv: 'OPENAI_API_KEY' },
  anthropic: { model: 'claude-sonnet-4-5', apiKeyEnv: 'ANTHROPIC_API_KEY' },
  deepseek: { model: DEFAULT_DEEPSEEK_MODEL, apiKeyEnv: 'DEEPSEEK_API_KEY' },
}

export const aiDefaultsForProvider = (provider: string) => providerDefaults[provider] ?? providerDefaults.gemini

export const canAdministerWorkspace = (user: User) => user.role === 'owner' || user.role === 'admin'

export function secretPresentation(secret: SecretRef) {
  return {
    name: secret.name,
    provider: secret.provider,
    status: secret.is_set ? '已设置' : '未设置',
    usage: secret.used_by.length ? `${secret.used_by.length} 个引用` : '未引用',
  }
}
