import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

export type ActionPhase = 'pending' | 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'blocked'

type ActionRecord = {
  phase: ActionPhase
  message?: string
}

type ActionFeedback = {
  begin: (action: string, entity: string) => void
  advance: (action: string, entity: string, phase: ActionPhase, message?: string) => void
  succeed: (action: string, entity: string, message?: string) => void
  fail: (action: string, entity: string, message: string) => void
  clear: (action: string, entity: string) => void
  phase: (action: string, entity: string) => ActionPhase | undefined
  message: (action: string, entity: string) => string | undefined
  isPending: (action: string, entity: string) => boolean
}

const ActionFeedbackContext = createContext<ActionFeedback | null>(null)

const actionKey = (action: string, entity: string) => `${action}:${entity}`
const activePhases = new Set<ActionPhase>(['pending', 'queued', 'running'])

export function ActionFeedbackProvider({ userId, children }: { userId: string; children: ReactNode }) {
  return <ActionFeedbackState key={userId}>{children}</ActionFeedbackState>
}

function ActionFeedbackState({ children }: { children: ReactNode }) {
  const [records, setRecords] = useState<Record<string, ActionRecord>>({})

  const advance = useCallback((action: string, entity: string, phase: ActionPhase, message?: string) => {
    const key = actionKey(action, entity)
    setRecords((current) => ({ ...current, [key]: { phase, message } }))
  }, [])

  const value = useMemo<ActionFeedback>(() => ({
    begin: (action, entity) => advance(action, entity, 'pending'),
    advance,
    succeed: (action, entity, message) => advance(action, entity, 'succeeded', message),
    fail: (action, entity, message) => advance(action, entity, 'failed', message),
    clear: (action, entity) => setRecords((current) => {
      const next = { ...current }
      delete next[actionKey(action, entity)]
      return next
    }),
    phase: (action, entity) => records[actionKey(action, entity)]?.phase,
    message: (action, entity) => records[actionKey(action, entity)]?.message,
    isPending: (action, entity) => activePhases.has(records[actionKey(action, entity)]?.phase as ActionPhase),
  }), [advance, records])

  return <ActionFeedbackContext.Provider value={value}>
    {children}
  </ActionFeedbackContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- provider consumers share this hook boundary
export function useActionFeedback(): ActionFeedback {
  const context = useContext(ActionFeedbackContext)
  if (!context) throw new Error('useActionFeedback must be used inside ActionFeedbackProvider')
  return context
}
