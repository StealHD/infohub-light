import { useCallback, useEffect, useMemo, useState } from 'react'
import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'
import type { OpenClawSessionPage } from '../openclaw/workspace/openclawWorkspaceContracts'

export function recentSessionRows(rows: OpenClawWorkspaceSession[], current?: OpenClawWorkspaceSession): OpenClawWorkspaceSession[] {
  const candidates = current && !rows.some((row) => row.key === current.key) ? [...rows, current] : rows
  const sorted = [...candidates].sort((a, b) => (b.updatedAt ?? b.createdAt ?? 0) - (a.updatedAt ?? a.createdAt ?? 0) || a.key.localeCompare(b.key))
  const latest = sorted.slice(0, 3)
  if (!current || latest.some((row) => row.key === current.key)) return latest
  return [...latest.slice(0, 2), sorted.find((row) => row.key === current.key)!]
}

type DirectoryState = { scope: string; page?: OpenClawSessionPage; error: string; loading: boolean }

export function useAgentSessionDirectory(chat: OpenClawChatController, userId: string, enabled = true, search = '', archived = false, offset = 0) {
  const generation = chat.workspace.skillScope?.()?.generation ?? 0
  const scope = JSON.stringify([userId, chat.gatewayUrl, generation, search, archived, offset, enabled, chat.status])
  const [state, setState] = useState<DirectoryState>({ scope: '', error: '', loading: false })
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision((value) => value + 1), [])
  const available = chat.status === 'connected' && chat.workspace.capabilities()['sessions.list']

  useEffect(() => chat.workspace.subscribe((event) => {
    if (event === 'sessions.changed' || event === 'task') refresh()
  }), [chat.workspace, refresh])

  useEffect(() => {
    if (!enabled || !available) return
    let active = true
    void Promise.resolve().then(async () => {
      if (!active) return
      setState((previous) => ({ scope, page: previous.scope === scope ? previous.page : undefined, error: '', loading: true }))
      try {
        const page = await chat.workspace.listSessionPage({ limit: 50, offset, search, archived })
        if (active) setState({ scope, page, error: '', loading: false })
      } catch {
        if (active) setState((previous) => ({ ...previous, scope, error: '暂时无法读取会话，请重试。', loading: false }))
      }
    })
    return () => { active = false }
  }, [chat.workspace, chat.sessionKey, available, enabled, scope, revision, search, archived, offset])

  return useMemo(() => ({
    page: state.scope === scope && enabled && available ? state.page : undefined,
    error: state.scope === scope ? state.error : '',
    loading: enabled && available && (state.scope !== scope || state.loading),
    available, refresh,
  }), [state, scope, enabled, available, refresh])
}
