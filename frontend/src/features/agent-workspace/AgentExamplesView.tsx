import { AgentUseCaseContent } from './AgentUseCaseContent'

export function AgentExamplesView() {
  return <div data-agent-examples className="quiet-scroll-region h-full min-h-0 overflow-y-auto px-4 pb-6 pt-[var(--inteliscope-size-page-header)] min-[768px]:px-6">
    <div className="mx-auto max-w-[var(--inteliscope-width-agent-conversation)] py-4"><AgentUseCaseContent /></div>
  </div>
}
