import type { SourceSummary } from '../../api/types'
import { Button, Icons, OverflowValue, StableAsyncButton } from '../../design-system'
import { SourceAvatar } from '../source-avatar/SourceAvatar'
import type { SourceOverviewSectionModel } from './sourceOverviewModel'

export type SourceSummaryViewState = {
  fingerprint: string
  status: 'loading' | 'success' | 'error'
  data?: SourceSummary
  message?: string
}

type SourceHeaderProps = {
  section: SourceOverviewSectionModel
  feedWindowDays: number
  expanded: boolean
  controlsId: string
  onToggle: () => void
  summaryState?: SourceSummaryViewState
  canSummarize?: boolean
  onRequestSummary?: () => void | Promise<unknown>
  onAskAgent?: () => void
}

export function SourceHeader({ section, feedWindowDays, expanded, controlsId, onToggle, summaryState, canSummarize = true, onRequestSummary, onAskAgent }: SourceHeaderProps) {
  const summaryReady = Boolean(summaryState?.data)
  const summaryAction = summaryReady ? (expanded ? '重新总结' : '查看总结') : 'AI 总结'
  const summaryActionLabel = summaryReady ? `${expanded ? '重新' : '查看'}总结专题 ${section.sourceName}` : `总结专题 ${section.sourceName}`
  const summaryPending = summaryState?.status === 'loading'
  return <header data-source-header data-expanded={expanded ? 'true' : 'false'} className="relative flex min-w-0 flex-col sm:flex-row sm:items-stretch">
    <span aria-hidden="true" className={`absolute inset-y-3 left-0 w-0.5 rounded-r-full bg-accent transition-opacity duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'opacity-100' : 'opacity-0'}`} />
    <div className={`group relative flex min-h-[76px] min-w-0 flex-1 flex-col justify-center px-4 py-3.5 transition-colors duration-[var(--inteliscope-motion-standard)] hover:bg-default/25 motion-reduce:transition-none sm:px-5 ${expanded ? 'bg-default/20' : 'bg-transparent'}`}>
      <button type="button" data-source-section-toggle aria-label={`${expanded ? '收起' : '展开'}专题 ${section.sourceName}`} aria-expanded={expanded} aria-controls={controlsId} className="absolute inset-0 z-0 text-left outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus" onClick={onToggle} />
      <span className="pointer-events-none relative z-10 flex min-w-0 items-center gap-3">
        <SourceAvatar name={section.sourceName} avatarUrl={section.sourceAvatar} platform={section.platformLabel} className="size-8 shrink-0" />
        <span className="min-w-0 flex-1">
          <h3 id={`source-section-${section.id}`} className="min-w-0"><OverflowValue value={section.sourceName} ariaLabel={`查看 ${section.sourceName} 的完整来源名称`} className="type-page-title text-foreground" /></h3>
          <span className="type-meta mt-0.5 block text-muted">近{feedWindowDays}天 · {section.itemCount} 篇内容 · {section.topicCount} 个主题</span>
        </span>
        <span className={`flex size-8 shrink-0 items-center justify-center rounded-full transition-colors duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'bg-accent/10 text-accent' : 'text-muted group-hover:bg-default/80 group-hover:text-foreground'}`}><Icons.ChevronDown size={16} aria-hidden="true" className={`transition-transform duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} /></span>
      </span>
    </div>
    {(onRequestSummary || onAskAgent) && <div data-source-actions className="grid grid-cols-2 gap-2 px-4 pb-3 sm:flex sm:shrink-0 sm:items-center sm:px-4 sm:pb-0 sm:pl-0">
      {onRequestSummary && (summaryReady && !expanded
        ? <Button size="sm" variant="ghost" className="min-w-0 justify-center whitespace-nowrap" aria-label={summaryActionLabel} onPress={onRequestSummary}><Icons.Sparkles size={14} aria-hidden="true" />{summaryAction}</Button>
        : <StableAsyncButton size="sm" variant="ghost" className="min-w-0 justify-center whitespace-nowrap" isDisabled={!canSummarize} pending={summaryPending} pendingContent={<><Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />总结中…</>} aria-label={summaryActionLabel} onPress={onRequestSummary}><Icons.Sparkles size={14} aria-hidden="true" />{summaryAction}</StableAsyncButton>)}
      {onAskAgent && <Button size="sm" variant="ghost" className="min-w-0 justify-center whitespace-nowrap" aria-label={`针对专题 ${section.sourceName} 问 Agent`} onPress={onAskAgent}><Icons.MessageCircle size={14} aria-hidden="true" />问 Agent</Button>}
    </div>}
  </header>
}
