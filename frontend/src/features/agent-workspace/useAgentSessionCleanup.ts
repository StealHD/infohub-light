import { useCallback, useEffect, useRef, useState } from 'react'
import type { OpenClawChatController } from '../openclaw'
import { isManagedGateway } from '../openclaw/gateway/openclawManaged'
import { cleanupEnabled, cleanupPreferenceScope, markSessionUsed, sessionLastUsed, writeCleanupEnabled } from './sessionCleanupPreference'

export function useAgentSessionCleanup(chat: OpenClawChatController, userId: string) {
  const scope = cleanupPreferenceScope(userId, chat.gatewayUrl)
  const [preference, setPreference] = useState({ scope, enabled: cleanupEnabled(scope) })
  const [status, setStatus] = useState({ scope, text: '' })
  const latest = useRef(chat)
  const enabled = preference.scope === scope ? preference.enabled : cleanupEnabled(scope)
  useEffect(() => { latest.current = chat }, [chat])
  useEffect(() => { if (chat.sessionKey) markSessionUsed(scope, chat.sessionKey) }, [scope, chat.sessionKey])
  useEffect(() => {
    const changed = (event: StorageEvent) => { if (event.key === scope) setPreference({ scope, enabled: cleanupEnabled(scope) }) }
    window.addEventListener('storage', changed)
    return () => window.removeEventListener('storage', changed)
  }, [scope])
  useEffect(() => {
    let active = true, running = false
    const tick = async () => {
      const current = latest.current
      if (current.sessionKey) markSessionUsed(scope, current.sessionKey)
      if (!enabled || !cleanupEnabled(scope) || running || current.status !== 'connected' || current.isRunning
        || current.runtimeUpdating || current.runtimeLoading || !isManagedGateway(current.gatewayUrl) || !navigator.locks) return
      running = true
      try {
        await navigator.locks.request(scope, { ifAvailable: true }, async (lock) => {
          if (!lock || !active) return
          const deleted = await current.workspace.cleanupSessions?.({
            lastUsedAt: (key) => sessionLastUsed(scope, key),
            isEnabled: () => active && cleanupEnabled(scope) && latest.current.status === 'connected' && !latest.current.isRunning,
          }) ?? 0
          if (active && deleted) setStatus({ scope, text: `已自动清理 ${deleted} 个闲置会话。` })
        })
      } catch { if (active) setStatus({ scope, text: '自动清理暂未完成，稍后会重试。' }) }
      finally { running = false }
    }
    const start = window.setTimeout(() => { void tick() }, 3000)
    const timer = window.setInterval(() => { void tick() }, 60_000)
    return () => { active = false; window.clearTimeout(start); window.clearInterval(timer) }
  }, [scope, enabled])
  const setEnabled = useCallback((value: boolean) => {
    if (writeCleanupEnabled(scope, value)) setPreference({ scope, enabled: value })
    else setStatus({ scope, text: '无法保存清理设置，请检查浏览器存储权限。' })
  }, [scope, setPreference, setStatus])
  return { enabled, setEnabled, available: isManagedGateway(chat.gatewayUrl), status: status.scope === scope ? status.text : '' }
}
