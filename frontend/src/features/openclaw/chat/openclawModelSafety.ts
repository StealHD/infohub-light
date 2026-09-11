import type { OpenClawRuntimeSelection } from '../openclawContracts'

export const MODEL_RECOVERY_MESSAGE = '当前会话的模型继承异常，请重新选择模型；若仍失败，请管理员修复 Gateway。'

export function modelSelectionSafety(session: Record<string, unknown> | null, expectedKey?: string): OpenClawRuntimeSelection['modelSafety'] {
  if (!session || (expectedKey && session.key !== expectedKey)) return 'unknown'
  if (session.parentSessionKey != null && typeof session.parentSessionKey !== 'string') return 'unknown'
  // 2026.9.2 clears the default override, yet execution inherits the parent.
  if (session.parentSessionKey && session.modelOverrideSource !== 'user') return 'unsafe_fork'
  return 'verified'
}

export function safeModelIdentity(provider: unknown, model: unknown): string | undefined {
  if (typeof provider !== 'string' || typeof model !== 'string') return undefined
  const value = model.startsWith(provider + '/') ? model : `${provider}/${model}`
  return value.length <= 180 && /^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.:/-]+$/u.test(value) && !value.includes('://') ? value : undefined
}
