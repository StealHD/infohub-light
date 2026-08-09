import { createContext, useContext } from 'react'

import type { AgentContextDraftV6, AgentContextItem, AgentSourceSnapshot } from './agentContext'

export type WorkbenchAgentContextValue = {
  draft: AgentContextDraftV6
  toggleItem: (item: AgentContextItem) => void
  removeItem: (id: string) => void
  clearItems: () => void
  openComposer: () => void
  openWithSourceSnapshot: (snapshot: AgentSourceSnapshot) => void
  setQuestion: (question: string) => void
  clearComposer: () => void
  restoreComposer: (question: string, items: AgentContextItem[], sourceSnapshot?: AgentSourceSnapshot) => void
}

export const WorkbenchAgentContext = createContext<WorkbenchAgentContextValue | null>(null)

export function useWorkbenchAgentContext(): WorkbenchAgentContextValue {
  const value = useContext(WorkbenchAgentContext)
  if (!value) throw new Error('useWorkbenchAgentContext must be used inside HeroWorkbenchShell')
  return value
}
