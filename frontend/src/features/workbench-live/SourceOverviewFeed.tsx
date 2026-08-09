import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import type { SourceSummary } from '../../api/types'
import { Button, Card, Icons, ImageGalleryModal, Timeline } from '../../design-system'
import { SourceAvatar } from '../source-avatar/SourceAvatar'
import type { WorkbenchCardModel } from './workbenchModel'
import { cardLabelForViewer, WorkbenchCard } from './VirtualFeed'
import type { MediaViewerState } from './VirtualFeed'
import type { SourceOverviewSectionModel } from './sourceOverviewModel'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'

type SourceOverviewFeedProps = {
  topInset?: number
  resetToTopKey?: string
  sections: SourceOverviewSectionModel[]
  sourceItemIds?: string[]
  trackNewItems?: boolean
  feedWindowDays?: number
  footer?: ReactNode
  terminal?: ReactNode
  terminalKey?: string
  expandedSourceId?: string | null
  expandedId?: string
  navigationTargetId?: string
  contextIds: string[]
  detailLoading?: boolean
  detailError?: boolean
  readonly?: boolean
  resumeAnchor?: SourceOverviewViewportAnchor | null
  onResumeAnchorRestored?: () => void
  onToggleSource: (id: string) => void
  onToggleExpanded: (id: string) => void
  onToggleSaved: (id: string, saved: boolean) => void
  onToggleContext: (card: WorkbenchCardModel) => void
  onItemAction: (id: string, dismissed: boolean) => void
  onTerminalReach?: () => void
  summaryStates?: Record<string, SourceSummaryViewState | undefined>
  canSummarize?: boolean
  onRequestSummary?: (section: SourceOverviewSectionModel, regenerate?: boolean) => void
  onAskAgent?: (section: SourceOverviewSectionModel) => void
}

export type SourceSummaryViewState = {
  fingerprint: string
  status: 'loading' | 'success' | 'error'
  data?: SourceSummary
  message?: string
}

export type SourceOverviewViewportAnchor = {
  kind: 'item' | 'source'
  id: string
  offset: number
  scrollTop?: number
}

export function readSourceOverviewViewportAnchor(scroll: HTMLDivElement, topInset: number): SourceOverviewViewportAnchor | null {
  const bounds = scroll.getBoundingClientRect()
  const effectiveTop = bounds.top + topInset
  const row = Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]'))
    .filter((candidate) => candidate.getBoundingClientRect().bottom > effectiveTop)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const card = row?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
  if (row?.dataset.itemId && card) {
    return { kind: 'item', id: row.dataset.itemId, offset: card.getBoundingClientRect().top - effectiveTop, scrollTop: scroll.scrollTop }
  }
  const header = Array.from(scroll.querySelectorAll<HTMLElement>('[data-source-header]'))
    .filter((candidate) => candidate.getBoundingClientRect().bottom > effectiveTop)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const section = header?.closest<HTMLElement>('[data-source-section]')
  if (!section?.dataset.sourceSectionId || !header) return null
  return { kind: 'source', id: section.dataset.sourceSectionId, offset: header.getBoundingClientRect().top - effectiveTop, scrollTop: scroll.scrollTop }
}

function sectionForItem(sections: SourceOverviewSectionModel[], itemId: string): number {
  return sections.findIndex((section) => section.cards.some((card) => card.id === itemId))
}

export function SourceInsight({ state, onRetry }: { state?: SourceSummaryViewState; onRetry?: () => void }) {
  if (!state) return null
  return <div data-source-insight className="border-t border-separator px-4 py-3 sm:px-5">
    {state.status === 'loading' && <div role="status" className="type-meta flex items-center gap-2 text-muted">
      <Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />正在总结当前专题…
    </div>}
    {state.status === 'error' && <div className="flex min-w-0 flex-wrap items-center gap-2" role="alert">
      <span className="type-meta min-w-0 flex-1 text-danger">{state.message || '专题总结生成失败，请稍后重试。'}</span>
      {onRetry && <Button size="sm" variant="ghost" onPress={onRetry}><Icons.RefreshCw size={13} aria-hidden="true" />重试</Button>}
    </div>}
    {state.status === 'success' && state.data && <div className="grid gap-2">
      <p className="type-body text-foreground">{state.data.overview}</p>
      <ul className="grid gap-1 pl-4 text-muted" aria-label="专题总结关键要点">
        {state.data.highlights.map((highlight, index) => <li key={`${index}:${highlight}`} className="type-meta list-disc">{highlight}</li>)}
      </ul>
      {onRetry && <div><Button size="sm" variant="ghost" onPress={onRetry}><Icons.RefreshCw size={13} aria-hidden="true" />重新总结</Button></div>}
    </div>}
  </div>
}

type SourceHeaderProps = {
  section: SourceOverviewSectionModel
  feedWindowDays: number
  expanded: boolean
  controlsId: string
  onToggle: () => void
  summaryState?: SourceSummaryViewState
  canSummarize?: boolean
  onRequestSummary?: () => void
  onAskAgent?: () => void
}

export function SourceHeader({ section, feedWindowDays, expanded, controlsId, onToggle, summaryState, canSummarize = true, onRequestSummary, onAskAgent }: SourceHeaderProps) {
  const summaryReady = summaryState?.status === 'success'
  const summaryAction = summaryReady ? (expanded ? '重新总结' : '查看总结') : 'AI 总结'
  const summaryActionLabel = summaryReady
    ? `${expanded ? '重新' : '查看'}总结专题 ${section.sourceName}`
    : `总结专题 ${section.sourceName}`
  return <header data-source-header data-expanded={expanded ? 'true' : 'false'} className="relative flex min-w-0 flex-col sm:flex-row sm:items-stretch">
    <span
      aria-hidden="true"
      className={`absolute inset-y-3 left-0 w-0.5 rounded-r-full bg-accent transition-opacity duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'opacity-100' : 'opacity-0'}`}
    />
    <button
      type="button"
      id={`source-section-${section.id}`}
      data-source-section-toggle
      aria-label={`${expanded ? '收起' : '展开'}专题 ${section.sourceName}`}
      aria-expanded={expanded}
      aria-controls={controlsId}
      className={`group flex min-h-[76px] min-w-0 flex-1 flex-col justify-center px-4 py-3.5 text-left outline-none transition-colors duration-[var(--inteliscope-motion-standard)] hover:bg-default/25 focus-visible:bg-default/25 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus motion-reduce:transition-none sm:px-5 ${expanded ? 'bg-default/20' : 'bg-transparent'}`}
      onClick={onToggle}
    >
      <span className="flex min-w-0 items-center gap-3">
        <SourceAvatar
          name={section.sourceName}
          avatarUrl={section.sourceAvatar}
          platform={section.platformLabel}
          className="size-8 shrink-0"
        />
        <span className="min-w-0 flex-1">
          <span role="heading" aria-level={2} className="type-page-title block truncate text-foreground">{section.sourceName}</span>
          <span className="type-meta mt-0.5 block text-muted">近{feedWindowDays}天 · {section.itemCount} 篇内容 · {section.topicCount} 个主题</span>
        </span>
        <span className={`flex size-8 shrink-0 items-center justify-center rounded-full transition-colors duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'bg-accent/10 text-accent' : 'text-muted group-hover:bg-default/80 group-hover:text-foreground'}`}>
          <Icons.ChevronDown
            size={16}
            aria-hidden="true"
            className={`transition-transform duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`}
          />
        </span>
      </span>
    </button>
    {(onRequestSummary || onAskAgent) && <div data-source-actions className="grid grid-cols-2 gap-2 px-4 pb-3 sm:flex sm:shrink-0 sm:items-center sm:px-4 sm:pb-0 sm:pl-0">
      {onRequestSummary && <Button
        size="sm"
        variant="ghost"
        className="min-w-0 justify-center whitespace-nowrap"
        isDisabled={!canSummarize || summaryState?.status === 'loading'}
        aria-label={summaryActionLabel}
        onPress={onRequestSummary}
      >{summaryState?.status === 'loading' ? <Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Icons.Sparkles size={14} aria-hidden="true" />}{summaryAction}</Button>}
      {onAskAgent && <Button size="sm" variant="ghost" className="min-w-0 justify-center whitespace-nowrap" aria-label={`针对专题 ${section.sourceName} 问 Agent`} onPress={onAskAgent}>
        <Icons.MessageCircle size={14} aria-hidden="true" />问 Agent
      </Button>}
    </div>}
  </header>
}

type SourceFeedProps = Pick<SourceOverviewFeedProps,
  'contextIds' | 'detailLoading' | 'detailError' | 'expandedId' | 'onItemAction' | 'onToggleContext' | 'onToggleExpanded' | 'onToggleSaved' | 'readonly'
> & {
  cards: WorkbenchCardModel[]
  actionMenuCardId: string | null
  onActionMenuOpenChange: (id: string, open: boolean) => void
  onOpenMedia: (card: WorkbenchCardModel, index: number, trigger: HTMLButtonElement) => void
  onBeforeLayoutChange: () => void
}

export function SourceFeed({
  cards,
  contextIds,
  expandedId,
  detailLoading,
  detailError,
  readonly,
  actionMenuCardId,
  onActionMenuOpenChange,
  onBeforeLayoutChange,
  onItemAction,
  onToggleContext,
  onToggleExpanded,
  onToggleSaved,
  onOpenMedia,
}: SourceFeedProps) {
  return <div data-source-feed className="border-t border-separator px-4 py-3 sm:px-5">
    <Timeline density="compact" className="[&>[data-timeline-item]:last-child_[data-timeline-content]]:border-b-0">
    {cards.map((card) => <Timeline.Item
      key={card.id}
      data-item-id={card.id}
      data-source-feed-row
      status={card.id === expandedId ? 'current' : 'default'}
    >
      <Timeline.Rail><Timeline.Marker className="mt-3" /><Timeline.Connector className="top-7" /></Timeline.Rail>
      <Timeline.Content className="border-b border-separator/80 pb-1">
        <WorkbenchCard
        card={card}
        variant="source-overview"
        expanded={card.id === expandedId}
        inContext={contextIds.includes(card.id)}
        contextFull={contextIds.length >= 8}
        contextCount={contextIds.length}
        actionMenuOpen={actionMenuCardId === card.id}
        detailLoading={card.id === expandedId && detailLoading}
        detailError={card.id === expandedId && detailError}
        readonly={readonly}
        onToggleExpanded={() => {
          onBeforeLayoutChange()
          onToggleExpanded(card.id)
        }}
        onToggleSaved={() => onToggleSaved(card.id, !card.userState.is_saved)}
        onToggleContext={() => onToggleContext(card)}
        onActionMenuOpenChange={(open) => onActionMenuOpenChange(card.id, open)}
        onItemAction={(dismissed) => {
          onBeforeLayoutChange()
          onItemAction(card.id, dismissed)
        }}
        onOpenMedia={(index, trigger) => onOpenMedia(card, index, trigger)}
        />
      </Timeline.Content>
    </Timeline.Item>)}
    </Timeline>
  </div>
}

type SourceSectionProps = Pick<SourceOverviewFeedProps,
  'contextIds' | 'detailLoading' | 'detailError' | 'expandedId' | 'onItemAction' | 'onToggleContext' | 'onToggleExpanded' | 'onToggleSaved' | 'readonly'
> & {
  section: SourceOverviewSectionModel
  feedWindowDays: number
  expanded: boolean
  onToggleSource: (id: string) => void
  actionMenuCardId: string | null
  onActionMenuOpenChange: (id: string, open: boolean) => void
  onOpenMedia: (card: WorkbenchCardModel, index: number, trigger: HTMLButtonElement) => void
  onBeforeLayoutChange: () => void
  summaryState?: SourceSummaryViewState
  canSummarize?: boolean
  onRequestSummary?: (section: SourceOverviewSectionModel, regenerate?: boolean) => void
  onAskAgent?: (section: SourceOverviewSectionModel) => void
}

export function SourceSection({ section, feedWindowDays, expanded, onToggleSource, onBeforeLayoutChange, summaryState, canSummarize, onRequestSummary, onAskAgent, ...feedProps }: SourceSectionProps) {
  const contentId = `source-section-content-${section.id}`
  return <section data-source-section data-source-section-id={section.id} aria-labelledby={`source-section-${section.id}`} className="pb-3">
    <Card
      data-source-group-card
      data-state={expanded ? 'expanded' : 'collapsed'}
      variant="secondary"
      className={`w-full gap-0 overflow-hidden rounded-[var(--inteliscope-radius-card)] border bg-surface-secondary/55 p-0 shadow-none transition-[background-color,border-color] duration-[var(--inteliscope-motion-standard)] motion-reduce:transition-none ${expanded ? 'border-border bg-surface-secondary/70' : 'border-separator hover:border-border'}`}
    >
      <SourceHeader
        section={section}
        feedWindowDays={feedWindowDays}
        expanded={expanded}
        controlsId={contentId}
        onToggle={() => {
          onBeforeLayoutChange()
          onToggleSource(section.id)
        }}
        summaryState={summaryState}
        canSummarize={canSummarize}
        onRequestSummary={onRequestSummary ? () => {
          onBeforeLayoutChange()
          if (summaryState?.status === 'success' && !expanded) {
            onToggleSource(section.id)
            return
          }
          onRequestSummary(section, summaryState?.status === 'success')
        } : undefined}
        onAskAgent={onAskAgent ? () => onAskAgent(section) : undefined}
      />
      <div
        id={contentId}
        data-source-section-content
        aria-hidden={!expanded}
        inert={!expanded}
        className={`grid transition-[grid-template-rows,opacity] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
      >
        <div className="min-h-0 overflow-hidden">
          <SourceInsight state={summaryState} onRetry={onRequestSummary ? () => {
            onBeforeLayoutChange()
            onRequestSummary(section, true)
          } : undefined} />
          <SourceFeed cards={section.cards} onBeforeLayoutChange={onBeforeLayoutChange} {...feedProps} />
        </div>
      </div>
    </Card>
  </section>
}

export function SourceOverviewFeed(props: SourceOverviewFeedProps) {
  const topInset = props.topInset ?? 64
  const feedWindowDays = props.feedWindowDays ?? 7
  const terminalContent = props.terminal
  const terminalKey = props.terminalKey
  const onTerminalReach = props.onTerminalReach
  const onToggleSource = props.onToggleSource
  const resumeAnchor = props.resumeAnchor
  const onResumeAnchorRestored = props.onResumeAnchorRestored
  const terminalEnabled = Boolean(terminalContent)
  const scrollRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<HTMLDivElement>(null)
  const terminalVisible = useRef(false)
  const onTerminalReachRef = useRef(onTerminalReach)
  const previousSourceIds = useRef(new Set<string>())
  const initializedSourceIds = useRef(false)
  const previousResetToTopKey = useRef(props.resetToTopKey)
  const pendingAnchor = useRef<SourceOverviewViewportAnchor | null>(null)
  const restoreFrame = useRef<number | undefined>(undefined)
  const didInitialNavigation = useRef(false)
  const didResumeAnchor = useRef(false)
  const mediaTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [newItemCount, setNewItemCount] = useState(0)
  const [openActionCardId, setOpenActionCardId] = useState<string | null>(null)
  const [mediaViewer, setMediaViewer] = useState<MediaViewerState | null>(null)
  const sectionsSignature = props.sections.map((section) => `${section.id}:${section.cards.map((card) => card.id).join(',')}`).join('|')
  const sourceItemIds = props.sourceItemIds ?? props.sections.flatMap((section) => section.cards.map((card) => card.id))
  const sourceSignature = sourceItemIds.join('\u0000')
  const summarySignature = props.sections.map((section) => {
    const state = props.summaryStates?.[section.id]
    return `${section.id}:${state?.status ?? ''}:${state?.data?.overview ?? ''}:${state?.data?.highlights.join('|') ?? ''}`
  }).join('\u0001')
  const layoutSignature = `${sectionsSignature}\u0000${props.expandedSourceId ?? ''}\u0000${props.expandedId ?? ''}\u0000${summarySignature}`
  // TanStack Virtual returns mutable imperative methods; React Compiler skips this component safely.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: props.sections.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 720,
    overscan: 2,
    // Resume restoration can synchronously emit a native scroll event. Let React
    // schedule that virtual range update normally instead of flushing during an effect.
    useFlushSync: false,
    getItemKey: (index) => props.sections[index]?.id ?? index,
    initialRect: { width: 760, height: 720 },
    observeElementRect: (instance, callback) => {
      const element = instance.scrollElement
      if (!(element instanceof HTMLElement)) return undefined
      const update = () => {
        const rect = element.getBoundingClientRect()
        callback({ width: rect.width || 760, height: rect.height || 720 })
      }
      update()
      if (typeof ResizeObserver === 'undefined') return undefined
      const observer = new ResizeObserver(update)
      observer.observe(element)
      return () => observer.disconnect()
    },
  })
  onTerminalReachRef.current = onTerminalReach

  const captureAnchor = useCallback(() => {
    const scroll = scrollRef.current
    pendingAnchor.current = scroll ? readSourceOverviewViewportAnchor(scroll, topInset) : null
  }, [topInset])

  const cancelAnchorRestore = useCallback(() => {
    pendingAnchor.current = null
    window.cancelAnimationFrame(restoreFrame.current ?? 0)
    restoreFrame.current = undefined
  }, [])

  const toggleSource = useCallback((sourceId: string) => {
    const scroll = scrollRef.current
    const header = Array.from(scroll?.querySelectorAll<HTMLElement>('[data-source-section]') ?? [])
      .find((section) => section.dataset.sourceSectionId === sourceId)
      ?.querySelector<HTMLElement>('[data-source-header]')
    if (scroll && header) {
      pendingAnchor.current = {
        kind: 'source',
        id: sourceId,
        offset: header.getBoundingClientRect().top - scroll.getBoundingClientRect().top - topInset,
        scrollTop: scroll.scrollTop,
      }
    }
    onToggleSource(sourceId)
  }, [onToggleSource, topInset])

  const restoreAnchor = useCallback((anchor: SourceOverviewViewportAnchor, align: 'start' | 'center' = 'start') => {
    const index = anchor.kind === 'item'
      ? sectionForItem(props.sections, anchor.id)
      : props.sections.findIndex((section) => section.id === anchor.id)
    if (index < 0) return
    window.cancelAnimationFrame(restoreFrame.current ?? 0)
    const findTarget = (scroll: HTMLDivElement) => anchor.kind === 'item'
      ? Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]')).find((candidate) => candidate.dataset.itemId === anchor.id)
        ?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
      : Array.from(scroll.querySelectorAll<HTMLElement>('[data-source-section]'))
        .find((section) => section.dataset.sourceSectionId === anchor.id)
        ?.querySelector<HTMLElement>('[data-source-header]')
    const initialScroll = scrollRef.current
    if (!initialScroll || !findTarget(initialScroll)) virtualizer.scrollToIndex(index, { align })
    let remainingFrames = 120
    let stableFrames = 0
    const adjust = () => {
      if (remainingFrames <= 0) {
        restoreFrame.current = undefined
        return
      }
      remainingFrames -= 1
      const scroll = scrollRef.current
      const target = scroll ? findTarget(scroll) : undefined
      if (scroll && target) {
        const offset = target.getBoundingClientRect().top - scroll.getBoundingClientRect().top - topInset
        const correction = offset - anchor.offset
        if (Math.abs(correction) > 0.5) {
          stableFrames = 0
          virtualizer.scrollToOffset(scroll.scrollTop + correction)
        } else stableFrames += 1
        if (stableFrames >= 30) {
          restoreFrame.current = undefined
          return
        }
      } else if (scroll) {
        virtualizer.scrollToIndex(index, { align })
      }
      restoreFrame.current = window.requestAnimationFrame(adjust)
    }
    restoreFrame.current = window.requestAnimationFrame(adjust)
  }, [props.sections, topInset, virtualizer])

  useEffect(() => {
    const capture = () => {
      captureAnchor()
      const anchor = pendingAnchor.current
      if (anchor) restoreAnchor(anchor)
    }
    window.addEventListener(workbenchRefreshRequestEvent, capture)
    return () => window.removeEventListener(workbenchRefreshRequestEvent, capture)
  }, [captureAnchor, restoreAnchor])

  useLayoutEffect(() => {
    const anchor = pendingAnchor.current
    pendingAnchor.current = null
    if (!anchor) return
    restoreAnchor(anchor)
  }, [layoutSignature, restoreAnchor])

  useLayoutEffect(() => {
    if (previousResetToTopKey.current === props.resetToTopKey) return
    previousResetToTopKey.current = props.resetToTopKey
    cancelAnchorRestore()
    setNewItemCount(0)
    const scroll = scrollRef.current
    if (scroll) scroll.scrollTop = 0
    if (props.sections.length > 0) virtualizer.scrollToIndex(0, { align: 'start' })
  }, [cancelAnchorRestore, props.resetToTopKey, props.sections.length, virtualizer])

  useEffect(() => {
    if (didResumeAnchor.current || !resumeAnchor || props.sections.length === 0) return
    didResumeAnchor.current = true
    const scroll = scrollRef.current
    const frame = scroll?.firstElementChild
    if (!scroll || !frame) {
      onResumeAnchorRestored?.()
      return
    }
    let restored = false
    const restore = () => {
      const targetScrollTop = resumeAnchor.scrollTop ?? 0
      if (restored || scroll.scrollHeight < targetScrollTop + scroll.clientHeight) return
      scroll.scrollTop = targetScrollTop
      scroll.dispatchEvent(new Event('scroll'))
      restored = true
      onResumeAnchorRestored?.()
    }
    restore()
    if (restored || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(restore)
    observer.observe(frame)
    return () => observer.disconnect()
  }, [onResumeAnchorRestored, props.sections.length, resumeAnchor])

  useEffect(() => {
    if (didInitialNavigation.current || props.sections.length === 0) return
    const target = props.navigationTargetId
    didInitialNavigation.current = true
    if (!target) return
    restoreAnchor({ kind: 'item', id: target, offset: 96 }, 'center')
  }, [props.navigationTargetId, props.sections.length, restoreAnchor])

  useEffect(() => {
    const nextIds = new Set(sourceItemIds)
    if (!initializedSourceIds.current) {
      initializedSourceIds.current = true
      previousSourceIds.current = nextIds
      return
    }
    const addedCount = sourceItemIds.filter((id) => !previousSourceIds.current.has(id)).length
    previousSourceIds.current = nextIds
    if (props.trackNewItems === false || addedCount <= 0) return
    const scroll = scrollRef.current
    if (scroll?.scrollTop && scroll.scrollTop > 96) setNewItemCount((count) => count + addedCount)
    else {
      setNewItemCount(0)
      virtualizer.scrollToIndex(0, { align: 'start' })
    }
  }, [props.trackNewItems, sourceItemIds, sourceSignature, virtualizer])

  useEffect(() => {
    terminalVisible.current = false
    const terminal = terminalRef.current
    const scroll = scrollRef.current
    if (!terminalEnabled || !terminal || !scroll) return
    const setVisibility = (visible: boolean) => {
      if (visible && !terminalVisible.current) onTerminalReachRef.current?.()
      terminalVisible.current = visible
    }
    if (typeof IntersectionObserver !== 'undefined') {
      const observer = new IntersectionObserver((entries) => setVisibility(Boolean(entries[0]?.isIntersecting)), { root: scroll, threshold: 0.01 })
      observer.observe(terminal)
      return () => observer.disconnect()
    }
    const frame = window.requestAnimationFrame(() => {
      const rootBounds = scroll.getBoundingClientRect()
      const terminalBounds = terminal.getBoundingClientRect()
      setVisibility(terminalBounds.bottom >= rootBounds.top && terminalBounds.top <= rootBounds.bottom)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [terminalEnabled, terminalKey])

  useEffect(() => () => {
    window.cancelAnimationFrame(restoreFrame.current ?? 0)
  }, [])

  function openMediaViewer(card: WorkbenchCardModel, index: number, trigger: HTMLButtonElement) {
    const requestedImage = card.mediaImages[index]
    if (!requestedImage?.url.startsWith('/api/media/')) return
    const images = card.mediaImages.filter((image) => image.url.startsWith('/api/media/')).slice(0, 6)
    const safeIndex = images.findIndex((image) => image.url === requestedImage.url)
    if (safeIndex < 0) return
    mediaTriggerRef.current = trigger
    setMediaViewer({ cardLabel: cardLabelForViewer(card), images, index: safeIndex })
  }

  function closeMediaViewer() {
    const trigger = mediaTriggerRef.current
    mediaTriggerRef.current = null
    setMediaViewer(null)
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected) trigger.focus()
    })
  }

  const virtualItems = virtualizer.getVirtualItems()

  function updateScrollState() {
    const scroll = scrollRef.current
    if (!scroll) return
    if (scroll.scrollTop <= 96) setNewItemCount(0)
    if (typeof IntersectionObserver === 'undefined' && terminalRef.current) {
      const rootBounds = scroll.getBoundingClientRect()
      const terminalBounds = terminalRef.current.getBoundingClientRect()
      const visible = terminalBounds.bottom >= rootBounds.top && terminalBounds.top <= rootBounds.bottom
      if (visible && !terminalVisible.current) onTerminalReachRef.current?.()
      terminalVisible.current = visible
    }
  }

  return <div className="relative flex min-h-0 flex-1 overflow-hidden">
    <div
      ref={scrollRef}
      data-testid="workbench-feed-scroll"
      data-feed-visual="quiet-studio"
      data-feed-mode="source-overview"
      data-fresh-edge="start"
      data-top-inset={topInset}
      className="quiet-scroll-region min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-3 pb-4 [overflow-anchor:none] sm:px-5"
      style={{ paddingTop: topInset }}
      onScroll={updateScrollState}
      onWheel={cancelAnchorRestore}
      onTouchStart={cancelAnchorRestore}
      onPointerDown={cancelAnchorRestore}
      onKeyDown={cancelAnchorRestore}
    >
      <div data-source-overview-frame data-feed-reading-frame className="relative mx-auto w-full max-w-[var(--inteliscope-width-reading)]" style={{ height: virtualizer.getTotalSize() }}>
        {virtualItems.map((virtualItem) => {
          const section = props.sections[virtualItem.index]
          if (!section) return null
          return <div
            key={virtualItem.key}
            data-index={virtualItem.index}
            ref={virtualizer.measureElement}
            className="absolute left-0 top-0 w-full"
            style={{ transform: `translateY(${virtualItem.start}px)` }}
          >
            <SourceSection
              section={section}
              feedWindowDays={feedWindowDays}
              expanded={props.expandedSourceId === section.id}
              onToggleSource={toggleSource}
              expandedId={props.expandedId}
              contextIds={props.contextIds}
              detailLoading={props.detailLoading}
              detailError={props.detailError}
              readonly={props.readonly}
              actionMenuCardId={openActionCardId}
              onActionMenuOpenChange={(id, open) => setOpenActionCardId(open ? id : null)}
              onBeforeLayoutChange={captureAnchor}
              summaryState={props.summaryStates?.[section.id]?.fingerprint === section.contentFingerprint ? props.summaryStates[section.id] : undefined}
              canSummarize={props.canSummarize}
              onRequestSummary={props.onRequestSummary}
              onAskAgent={props.onAskAgent}
              onToggleExpanded={props.onToggleExpanded}
              onToggleSaved={props.onToggleSaved}
              onToggleContext={props.onToggleContext}
              onItemAction={props.onItemAction}
              onOpenMedia={openMediaViewer}
            />
          </div>
        })}
      </div>
      {props.footer && <div className="mx-auto w-full max-w-[var(--inteliscope-width-reading)] pb-4">{props.footer}</div>}
      {terminalEnabled && <div ref={terminalRef} data-testid="feed-end-sentinel" className="mx-auto w-full max-w-[var(--inteliscope-width-reading)] pb-5">{terminalContent}</div>}
    </div>
    {newItemCount > 0 && <Button
      size="sm"
      className="absolute left-1/2 z-10 -translate-x-1/2"
      style={{ top: topInset + 16 }}
      aria-label={`查看 ${newItemCount} 条新内容`}
      onPress={() => {
        cancelAnchorRestore()
        setNewItemCount(0)
        virtualizer.scrollToIndex(0, { align: 'start' })
      }}
    >{newItemCount} 条新内容</Button>}
    <ImageGalleryModal
      isOpen={Boolean(mediaViewer)}
      heading={mediaViewer ? `${mediaViewer.cardLabel} 图片预览` : '图片预览'}
      images={mediaViewer?.images ?? []}
      index={mediaViewer?.index ?? 0}
      onIndexChange={(index) => setMediaViewer((current) => current ? { ...current, index } : current)}
      onOpenChange={(open) => { if (!open) closeMediaViewer() }}
    />
  </div>
}
