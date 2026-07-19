import { createContext, useContext } from 'react'

import type { AgentContextDraftV2, AgentContextItem, AgentModelPreference } from './agentContext'

export type WorkbenchAgentContextValue = {
  draft: AgentContextDraftV2
  toggleItem: (item: AgentContextItem) => void
  removeItem: (id: string) => void
  openComposer: () => void
  setQuestion: (question: string) => void
  setModelPreference: (preference: AgentModelPreference) => void
}

export const WorkbenchAgentContext = createContext<WorkbenchAgentContextValue | null>(null)

export function useWorkbenchAgentContext(): WorkbenchAgentContextValue {
  const value = useContext(WorkbenchAgentContext)
  if (!value) throw new Error('useWorkbenchAgentContext must be used inside HeroWorkbenchShell')
  return value
}
