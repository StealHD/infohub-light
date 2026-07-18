import { createContext, useContext } from 'react'

import type { AgentContextDraftV1, AgentModelPreference } from './agentContext'

export type WorkbenchAgentContextValue = {
  draft: AgentContextDraftV1
  toggleItem: (id: string) => void
  removeItem: (id: string) => void
  setQuestion: (question: string) => void
  setModelPreference: (preference: AgentModelPreference) => void
}

export const WorkbenchAgentContext = createContext<WorkbenchAgentContextValue | null>(null)

export function useWorkbenchAgentContext(): WorkbenchAgentContextValue {
  const value = useContext(WorkbenchAgentContext)
  if (!value) throw new Error('useWorkbenchAgentContext must be used inside HeroWorkbenchShell')
  return value
}
