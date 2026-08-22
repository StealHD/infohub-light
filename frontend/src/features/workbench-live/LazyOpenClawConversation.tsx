import { lazy, Suspense } from 'react'

import type { OpenClawChatController } from '../openclaw'
import { AgentPanelSkeleton } from './WorkbenchLoadingState'
import type { WorkbenchAgentContextValue } from './workbenchAgentContext'

const OpenClawConversation = lazy(() => import('../openclaw/OpenClawConversation').then((module) => ({
  default: module.OpenClawConversation,
})))

export function LazyOpenClawConversation({
  chat,
  value,
}: {
  chat: OpenClawChatController
  value: WorkbenchAgentContextValue
}) {
  return <Suspense fallback={<AgentPanelSkeleton />}>
    <OpenClawConversation chat={chat} value={value} />
  </Suspense>
}
