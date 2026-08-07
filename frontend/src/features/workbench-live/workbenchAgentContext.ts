import { createContext, useContext } from 'react'

import type { AgentContextDraftV5, AgentContextItem } from './agentContext'

export type WorkbenchAgentContextValue = {
  draft: AgentContextDraftV5
  toggleItem: (item: AgentContextItem) => void
  removeItem: (id: string) => void
  clearItems: () => void
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
