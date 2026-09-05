import { useCallback, useEffect, useMemo, useState } from 'react'

import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'

export type TrustedSessionRow = { session: OpenClawWorkspaceSession; depth: number }
export type AgentWorkspaceSessionState = {
  root?: OpenClawWorkspaceSession
  current?: OpenClawWorkspaceSession
  tree: TrustedSessionRow[]
  trustedSessions: OpenClawWorkspaceSession[]
  scopeKeys: string[]
  loading: boolean
  error: string
  refresh: () => void
}

function ancestryDepth(
  session: OpenClawWorkspaceSession,
  rootKey: string,
  byKey: Map<string, OpenClawWorkspaceSession>,
): number | null {
  if (session.key === rootKey) return 0
  const seen = new Set([session.key])
  let parentKey = session.parentSessionKey
  let depth = 1
  while (parentKey && depth <= byKey.size) {
    if (seen.has(parentKey)) return null
    if (parentKey === rootKey) return depth
    seen.add(parentKey)
    parentKey = byKey.get(parentKey)?.parentSessionKey
    depth += 1
  }
  return null
}

function fallbackSession(key: string, active: boolean): OpenClawWorkspaceSession {
  return { key, label: '当前会话', hasActiveRun: active }
}

export function projectTrustedSessionTree(
  sessions: OpenClawWorkspaceSession[],
  currentKey: string,
  requestedRootKey: string | null,
  currentActive = false,
) {
  const byKey = new Map(sessions.map((session) => [session.key, session]))
  if (!byKey.has(currentKey)) byKey.set(currentKey, fallbackSession(currentKey, currentActive))
  const effectiveRoot = requestedRootKey && ancestryDepth(byKey.get(currentKey)!, requestedRootKey, byKey) !== null
    ? requestedRootKey
    : currentKey
  if (!byKey.has(effectiveRoot)) byKey.set(effectiveRoot, fallbackSession(effectiveRoot, currentActive))
  const trustedRows = [...byKey.values()]
    .flatMap((session) => {
      const depth = ancestryDepth(session, effectiveRoot, byKey)
      return depth === null ? [] : [{ session, depth }]
    })
  const compareSessions = (left: OpenClawWorkspaceSession, right: OpenClawWorkspaceSession) => (
    Number(left.createdAt ?? 0) - Number(right.createdAt ?? 0)
    || left.key.localeCompare(right.key)
  )
  const childrenByParent = new Map<string, OpenClawWorkspaceSession[]>()
  for (const { session, depth } of trustedRows) {
    if (depth === 0 || !session.parentSessionKey) continue
    const children = childrenByParent.get(session.parentSessionKey) ?? []
    children.push(session)
    childrenByParent.set(session.parentSessionKey, children)
  }
  for (const children of childrenByParent.values()) children.sort(compareSessions)
  const tree: TrustedSessionRow[] = []
  const visit = (session: OpenClawWorkspaceSession, depth: number) => {
    tree.push({ session, depth })
    for (const child of childrenByParent.get(session.key) ?? []) visit(child, depth + 1)
  }
  visit(byKey.get(effectiveRoot)!, 0)
  return {
    root: byKey.get(effectiveRoot),
    current: byKey.get(currentKey),
    tree,
    trustedSessions: tree.map((row) => row.session),
    scopeKeys: tree.map((row) => row.session.key),
  }
}

export function useAgentWorkspaceSessions(chat: OpenClawChatController): AgentWorkspaceSessionState {
  const [sessions, setSessions] = useState<OpenClawWorkspaceSession[]>([])
  const [rootKey, setRootKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => chat.workspace.subscribe((event) => {
    if (event === 'sessions.changed' || event === 'task') refresh()
  }), [chat.workspace, refresh])

  useEffect(() => {
    let active = true
    if (chat.status !== 'connected' || !chat.sessionKey) {
      void Promise.resolve().then(() => { if (active) { setSessions([]); setRootKey(null) } })
      return () => { active = false }
    }
    if (!rootKey) void Promise.resolve().then(() => { if (active) setRootKey(chat.sessionKey) })
    return () => { active = false }
  }, [chat.sessionKey, chat.status, rootKey])

  useEffect(() => {
    if (chat.status !== 'connected' || !chat.sessionKey || !chat.workspace.capabilities()['sessions.list']) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) { setLoading(true); setError('') }
      return chat.workspace.listSessions()
    })
      .then((value) => {
        if (!active) return
        setSessions(value)
        setRootKey((currentRoot) => {
          if (!currentRoot) return chat.sessionKey
          const byKey = new Map(value.map((session) => [session.key, session]))
          const current = byKey.get(chat.sessionKey!) ?? fallbackSession(chat.sessionKey!, chat.isRunning)
          return ancestryDepth(current, currentRoot, byKey) === null ? chat.sessionKey : currentRoot
        })
      })
      .catch(() => { if (active) setError('暂时无法读取可信会话树，请稍后重试。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [chat.isRunning, chat.sessionKey, chat.status, chat.workspace, revision])

  const projection = useMemo(() => {
    if (!chat.sessionKey) return { root: undefined, current: undefined, tree: [], trustedSessions: [], scopeKeys: [] }
    return projectTrustedSessionTree(sessions, chat.sessionKey, rootKey, chat.isRunning)
  }, [chat.isRunning, chat.sessionKey, rootKey, sessions])

  return { ...projection, loading, error, refresh }
}
