import { Suspense, lazy } from 'react'
import { AgentPanelSkeleton } from '../workbench-live/WorkbenchLoadingState'
import type { OpenClawChatController } from '../openclaw'
import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
const OpenClawWorkbenchPanel = lazy(() => import('../openclaw/adapters/OpenClawConversation').then((module) => ({ default: module.OpenClawWorkbenchPanel })))
export function AgentConversationView({ chat, context }: { chat: OpenClawChatController; context: WorkbenchAgentContextValue }) { return <div className="flex min-h-0 flex-1 flex-col overflow-hidden" data-agent-conversation-view><Suspense fallback={<AgentPanelSkeleton />}><OpenClawWorkbenchPanel chat={chat} value={context} variant="workspace" /></Suspense></div> }
