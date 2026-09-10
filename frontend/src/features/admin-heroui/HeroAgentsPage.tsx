import { PageFrame } from '../../design-system'
import { AgentAccessPanel } from '../agent-connection/AgentAccessPanel'

export { OpenClawBrowserSettings } from './HeroAgentsPageBrowserSettings'

export function HeroAgentsPage() {
  return <div data-page-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
      <AgentAccessPanel />
    </PageFrame>
  </div>
}
