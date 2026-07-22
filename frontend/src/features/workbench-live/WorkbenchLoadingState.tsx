import { CalmSkeleton } from '../../design-system'
import { WORKBENCH_COLLAPSED_ROW_PX, WORKBENCH_SKELETON_CARD_PX } from './workbenchLayout'

export function WorkbenchFeedSkeleton() {
  return <div data-workbench-feed-skeleton className="h-full min-h-0 overflow-hidden px-3 py-4 sm:px-5">
    <div className="mx-auto w-full max-w-[var(--inteliscope-width-reading)]">
      {Array.from({ length: 5 }, (_, index) => <div
        key={index}
        data-workbench-feed-skeleton-row
        className="pb-3"
        style={{ height: WORKBENCH_COLLAPSED_ROW_PX }}
      >
        <CalmSkeleton className="h-full w-full rounded-[var(--inteliscope-radius-feed-card)] border border-separator" />
        <span className="sr-only">{WORKBENCH_SKELETON_CARD_PX}px 内容卡片占位</span>
      </div>)}
    </div>
  </div>
}

export function AgentPanelSkeleton() {
  return <div data-agent-panel-skeleton className="grid h-full min-h-0 grid-rows-[48px_minmax(96px,1fr)_128px] gap-3 p-4">
    <CalmSkeleton className="h-12 rounded-[var(--inteliscope-radius-card)]" />
    <CalmSkeleton className="min-h-24 rounded-[var(--inteliscope-radius-card)]" />
    <CalmSkeleton className="h-32 rounded-[var(--inteliscope-radius-card)]" />
    <span data-agent-skeleton-block className="sr-only">上下文占位</span>
    <span data-agent-skeleton-block className="sr-only">对话占位</span>
    <span data-agent-skeleton-block className="sr-only">输入区占位</span>
  </div>
}
