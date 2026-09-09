import { lazy, Suspense, useEffect, useState } from 'react'
import { useLocation, useNavigate, useOutletContext } from 'react-router-dom'

import type { User } from '../../api/types'
import { AgentWorkspaceLayout } from '../../design-system'
import { useOpenClawWorkspaceRuntime } from '../openclaw/workspace/openClawWorkspaceRuntimeContext'
import { useWorkbenchAgentContext } from '../workbench-live/workbenchAgentContext'
import { AgentExamplesView } from './AgentExamplesView'
import { AgentArtifactsView } from './AgentArtifactsView'
import { AgentAutomationsView } from './AgentAutomationsView'
import { AgentContextPanel } from './AgentContextPanel'
import { AgentConversationView } from './AgentConversationView'
import { AgentSkillsView } from './AgentSkillsView'
import { AgentTasksView } from './AgentTasksView'
import { AgentWorkspaceHeader } from './AgentWorkspaceHeader'
import { AgentWorkspaceSidebar } from './AgentWorkspaceSidebar'
import { GatewayWriteTrustDialog } from './GatewayWriteTrustDialog'
import {
  inspectorForLocation,
  isOpenClawResourcePage,
  type OpenClawInspector,
} from './agentWorkspaceModel'
import { useAgentWorkspaceSessions } from './useAgentWorkspaceSessions'

const InformationAutomationsView = lazy(() => import('../information-automations/InformationAutomationsView'))

const fallbackUser: User = {
  id: 'agent-workspace',
  username: 'user',
  role: 'member',
  enabled: true,
}

export function AgentWorkspacePage() {
  const location = useLocation()
  const navigate = useNavigate()
  const outlet = useOutletContext<{ api?: import('../../api/service').ServiceApi; user?: User; onLogout?: () => void } | null>()
  const user = outlet?.user ?? fallbackUser
  const chat = useOpenClawWorkspaceRuntime()
  const context = useWorkbenchAgentContext()
  const sessions = useAgentWorkspaceSessions(chat, user.id)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [writeTrustedGateway, setWriteTrustedGateway] = useState<string | null>(null)
  const [trustOpen, setTrustOpen] = useState(false)
  const inspector = inspectorForLocation(location.pathname, location.search)
  const resourcePage = isOpenClawResourcePage(location.pathname)
  const writeTrusted = chat.status === 'connected' && writeTrustedGateway === chat.gatewayUrl

  const inspectorView = inspector === 'tasks'
    ? <AgentTasksView chat={chat} scopeKeys={sessions.scopeKeys} writeTrusted={writeTrusted} onRequireWriteTrust={() => setTrustOpen(true)} variant="inspector" />
    : inspector === 'artifacts'
      ? <AgentArtifactsView chat={chat} trustedSessions={sessions.trustedSessions} variant="inspector" />
      : inspector === 'context'
        ? <AgentContextPanel chat={chat} context={context} />
        : undefined
  const inspectorTitle = inspector === 'tasks' ? 'Tasks' : inspector === 'artifacts' ? 'Artifacts' : '上下文'
  const content = location.pathname === '/agent/examples'
    ? <AgentExamplesView />
    : location.pathname === '/agent/skills'
    ? outlet?.api ? <AgentSkillsView chat={chat} api={outlet.api} user={user} /> : null
    : location.pathname === '/agent/automations'
      ? new URLSearchParams(location.search).get('advanced') === 'cron' ? <AgentAutomationsView chat={chat} /> : <Suspense fallback={<p role="status">正在加载提醒…</p>}><InformationAutomationsView key={user.id} canMutate={user.role !== 'viewer'} /></Suspense>
      : <AgentConversationView chat={chat} context={context} />

  function navigateInspector(route: string) {
    navigate(route)
  }

  function closeInspector(open: boolean) {
    if (!open) navigate('/agent')
  }

  useEffect(() => {
    if (chat.status !== 'connected') void Promise.resolve().then(() => setWriteTrustedGateway(null))
  }, [chat.gatewayUrl, chat.status])

  return <div className="h-full min-h-0 min-w-0 overflow-hidden">
    <AgentWorkspaceLayout
      sidebar={<AgentWorkspaceSidebar chat={chat} sessions={sessions} user={user} onLogout={() => outlet?.onLogout?.()} onNavigate={() => setSidebarOpen(false)} writeTrusted={writeTrusted} onRequireWriteTrust={() => setTrustOpen(true)} />}
      inspector={inspectorView}
      inspectorTitle={inspectorTitle}
      sidebarOpen={sidebarOpen}
      onSidebarOpenChange={setSidebarOpen}
      inspectorOpen={Boolean(inspector)}
      onInspectorOpenChange={closeInspector}
    >
      <AgentWorkspaceHeader
        chat={chat}
        current={sessions.current}
        inspector={inspector as OpenClawInspector}
        userId={user.id}
        pageTitle={location.pathname === '/agent/examples' ? '使用示例' : location.pathname === '/agent/skills' ? 'Skills' : location.pathname === '/agent/automations' ? 'Automations' : undefined}
        onOpenSessions={() => setSidebarOpen(true)}
        onNavigate={navigateInspector}
      />
      <div className={`min-h-0 min-w-0 flex-1 ${resourcePage ? 'overflow-hidden' : 'flex flex-col overflow-hidden'}`}>
        {content}
      </div>
    </AgentWorkspaceLayout>
    <GatewayWriteTrustDialog open={trustOpen} gatewayUrl={chat.gatewayUrl} onOpenChange={setTrustOpen} onConfirm={() => setWriteTrustedGateway(chat.gatewayUrl)} />
  </div>
}
