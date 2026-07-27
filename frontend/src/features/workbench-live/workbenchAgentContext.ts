import { createContext, useContext } from 'react'

import type { AgentContextDraftV4, AgentContextItem } from './agentContext'

export type WorkbenchAgentContextValue = {
  draft: AgentContextDraftV4
  toggleItem: (item: AgentContextItem) => void
  removeItem: (id: string) => void
  openComposer: () => void
  setQuestion: (question: string) => void
  clearComposer: () => void
  restoreComposer: (question: string, items: AgentContextItem[]) => void
}

export const WorkbenchAgentContext = createContext<WorkbenchAgentContextValue | null>(null)

export function useWorkbenchAgentContext(): WorkbenchAgentContextValue {
  const value = useContext(WorkbenchAgentContext)
  if (!value) throw new Error('useWorkbenchAgentContext must be used inside HeroWorkbenchShell')
  return value
}
