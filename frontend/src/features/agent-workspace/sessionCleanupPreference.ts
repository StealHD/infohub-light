export const SESSION_CLEANUP_POLICY = '空白会话闲置 7 天、其他会话闲置 90 天后永久删除。主会话、当前会话、运行中、自动任务、工作树及被引用的父会话会保留。'

export function cleanupPreferenceScope(userId: string, gatewayUrl: string): string {
  return `inteliscope.session-cleanup.v1:${encodeURIComponent(userId)}:${encodeURIComponent(gatewayUrl)}`
}
export function cleanupEnabled(scope: string): boolean {
  try { const value = localStorage.getItem(scope); return value === null || value === 'on' } catch { return false }
}
export function writeCleanupEnabled(scope: string, enabled: boolean): boolean {
  try { localStorage.setItem(scope, enabled ? 'on' : 'off'); return true } catch { return false }
}
export function markSessionUsed(scope: string, key: string): void {
  try { localStorage.setItem(`${scope}:used:${encodeURIComponent(key)}`, String(Date.now())) } catch { /* Current session is also protected by runtime. */ }
}
export function sessionLastUsed(scope: string, key: string): number {
  try {
    const value = Number(localStorage.getItem(`${scope}:used:${encodeURIComponent(key)}`) ?? 0)
    return Number.isFinite(value) && value >= 0 ? value : Date.now()
  } catch { return Date.now() }
}
