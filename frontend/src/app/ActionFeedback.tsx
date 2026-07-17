import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

import { Alert, Snackbar, uiLayout, useMediaQuery } from '../ui'

export type ActionPhase = 'pending' | 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'blocked'

type ActionRecord = {
  phase: ActionPhase
  message?: string
}

type ActionNotice = ActionRecord & { key: string }

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

function severity(phase: ActionPhase): 'success' | 'warning' | 'error' | 'info' {
  if (phase === 'failed') return 'error'
  if (phase === 'partial' || phase === 'blocked') return 'warning'
  if (phase === 'succeeded') return 'success'
  return 'info'
}

export function ActionFeedbackProvider({ userId, children, noticeSurface = 'legacy' }: { userId: string; children: ReactNode; noticeSurface?: 'legacy' | 'none' }) {
  return <ActionFeedbackState key={userId} userId={userId} noticeSurface={noticeSurface}>{children}</ActionFeedbackState>
}

function ActionFeedbackState({ userId, children, noticeSurface }: { userId: string; children: ReactNode; noticeSurface: 'legacy' | 'none' }) {
  const mobile = useMediaQuery('(max-width:767px)')
  const [records, setRecords] = useState<Record<string, ActionRecord>>({})
  const [notice, setNotice] = useState<ActionNotice>()
  const [sequence, setSequence] = useState(0)

  const advance = useCallback((action: string, entity: string, phase: ActionPhase, message?: string) => {
    const key = actionKey(action, entity)
    setRecords((current) => ({ ...current, [key]: { phase, message } }))
    if (message && !activePhases.has(phase)) {
      setSequence((current) => current + 1)
      setNotice({ key, phase, message })
    }
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

  const open = Boolean(notice?.message)
  const role = notice?.phase === 'failed' || notice?.phase === 'blocked' ? 'alert' : 'status'

  return <ActionFeedbackContext.Provider value={value}>
    {children}
    {noticeSurface === 'legacy' && <Snackbar
      key={`${userId}:${notice?.key ?? ''}:${sequence}`}
      open={open}
      autoHideDuration={notice?.phase === 'failed' || notice?.phase === 'partial' || notice?.phase === 'blocked' ? 8000 : 4000}
      onClose={(_event, reason) => { if (reason !== 'clickaway') setNotice(undefined) }}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      sx={mobile ? { bottom: `${uiLayout.mobileNavHeight + 8}px` } : undefined}
    >
      <Alert role={role} severity={notice ? severity(notice.phase) : 'info'} variant="filled" onClose={() => setNotice(undefined)}>
        {notice?.message}
      </Alert>
    </Snackbar>}
  </ActionFeedbackContext.Provider>
}

export function useActionFeedback(): ActionFeedback {
  const context = useContext(ActionFeedbackContext)
  if (!context) throw new Error('useActionFeedback must be used inside ActionFeedbackProvider')
  return context
}
