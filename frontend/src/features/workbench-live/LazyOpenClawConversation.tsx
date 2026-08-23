import { lazy, Suspense } from 'react'

import type { OpenClawChatController } from '../openclaw'
import { AgentPanelSkeleton } from './WorkbenchLoadingState'
import type { WorkbenchAgentContextValue } from './workbenchAgentContext'

const OpenClawWorkbenchPanel = lazy(() => import('../openclaw/adapters/OpenClawConversation').then((module) => ({
  default: module.OpenClawWorkbenchPanel,
})))

export function LazyOpenClawConversation({
  chat,
  value,
}: {
  chat: OpenClawChatController
  value: WorkbenchAgentContextValue
}) {
  return <Suspense fallback={<AgentPanelSkeleton />}>
    <OpenClawWorkbenchPanel chat={chat} value={value} />
  </Suspense>
}
