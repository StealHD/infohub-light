import { updateAgentContextDraft, type AgentContextDraftV6 } from './agentContext'
import type { WorkbenchAgentContextValue } from './workbenchAgentContext'

export function createWorkbenchAgentValue(draft: AgentContextDraftV6, persist: (draft: AgentContextDraftV6) => void): Omit<WorkbenchAgentContextValue, 'openComposer'> {
  return {
    draft,
    toggleItem: (item) => persist(updateAgentContextDraft(draft, item)),
    removeItem: (id) => persist({ ...draft, items: draft.items.filter((item) => item.articleId !== id) }),
    clearItems: () => persist({ ...draft, items: [], sourceSnapshot: undefined }),
    openWithSourceSnapshot: (sourceSnapshot) => persist({ ...draft, items: [], sourceSnapshot }),
    setQuestion: (question) => persist({ ...draft, question }),
    setSkill: (selectedSkill) => persist({ ...draft, selectedSkill }),
    clearComposer: () => persist({ ...draft, question: '', items: [], sourceSnapshot: undefined, selectedSkill: undefined }),
    restoreComposer: (question, items, sourceSnapshot, selectedSkill) => persist({ ...draft, question, items, sourceSnapshot, selectedSkill }),
  }
}
