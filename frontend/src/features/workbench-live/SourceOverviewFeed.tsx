import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import { Button, ImageGalleryModal } from '../../design-system'
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
  expandedId?: string
  navigationTargetId?: string
  contextIds: string[]
  detailLoading?: boolean
  detailError?: boolean
  readonly?: boolean
  resumeAnchor?: SourceOverviewViewportAnchor | null
  onResumeAnchorRestored?: () => void
  onToggleExpanded: (id: string) => void
  onToggleSaved: (id: string, saved: boolean) => void
  onToggleContext: (card: WorkbenchCardModel) => void
  onItemAction: (id: string, dismissed: boolean) => void
  onTerminalReach?: () => void
}

export type SourceOverviewViewportAnchor = { id: string; offset: number; scrollTop?: number }

export function readSourceOverviewViewportAnchor(scroll: HTMLDivElement, topInset: number): SourceOverviewViewportAnchor | null {
  const bounds = scroll.getBoundingClientRect()
  const effectiveTop = bounds.top + topInset
  const row = Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]'))
    .filter((candidate) => candidate.getBoundingClientRect().bottom > effectiveTop)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const card = row?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
  if (!row?.dataset.itemId || !card) return null
  return { id: row.dataset.itemId, offset: card.getBoundingClientRect().top - effectiveTop, scrollTop: scroll.scrollTop }
}

function sectionForItem(sections: SourceOverviewSectionModel[], itemId: string): number {
  return sections.findIndex((section) => section.cards.some((card) => card.id === itemId))
}

export function SourceInsight({ children }: { children?: ReactNode }) {
  if (!children) return null
  return <div data-source-insight className="border-b border-separator py-3">{children}</div>
}

export function SourceHeader({ section, feedWindowDays }: { section: SourceOverviewSectionModel; feedWindowDays: number }) {
  return <header data-source-header className="border-b border-separator pb-4 pt-6">
    <div className="flex min-w-0 items-center gap-2.5">
      <SourceAvatar
        name={section.sourceName}
        avatarUrl={section.sourceAvatar}
        platform={section.platformLabel}
        className="size-7 shrink-0"
      />
      <div className="min-w-0">
        <h2 className="type-page-title truncate text-foreground">{section.sourceName}</h2>
        <p className="type-meta mt-0.5 text-muted">近{feedWindowDays}天 · {section.itemCount} 篇内容 · {section.topicCount} 个主题</p>
      </div>
    </div>
    {section.topics.length > 0 && <div aria-label={`${section.sourceName} 的主题`} className="type-meta mt-3 flex flex-wrap gap-x-3 gap-y-1 text-muted">
      {section.topics.map((topic) => <span key={topic}>#{topic}</span>)}
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
  return <div data-source-feed>
    {cards.map((card) => <div key={card.id} data-item-id={card.id}>
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
    </div>)}
  </div>
}

type SourceSectionProps = Pick<SourceOverviewFeedProps,
  'contextIds' | 'detailLoading' | 'detailError' | 'expandedId' | 'onItemAction' | 'onToggleContext' | 'onToggleExpanded' | 'onToggleSaved' | 'readonly'
> & {
  section: SourceOverviewSectionModel
  feedWindowDays: number
  actionMenuCardId: string | null
  onActionMenuOpenChange: (id: string, open: boolean) => void
  onOpenMedia: (card: WorkbenchCardModel, index: number, trigger: HTMLButtonElement) => void
  onBeforeLayoutChange: () => void
}

export function SourceSection({ section, feedWindowDays, ...feedProps }: SourceSectionProps) {
  return <section data-source-section data-source-section-id={section.id} aria-labelledby={`source-section-${section.id}`}>
    <div id={`source-section-${section.id}`} className="sr-only">专题：{section.sourceName}</div>
    <SourceHeader section={section} feedWindowDays={feedWindowDays} />
    <SourceInsight />
    <SourceFeed cards={section.cards} {...feedProps} />
  </section>
}

export function SourceOverviewFeed(props: SourceOverviewFeedProps) {
  const topInset = props.topInset ?? 64
  const feedWindowDays = props.feedWindowDays ?? 7
  const terminalContent = props.terminal
  const terminalKey = props.terminalKey
  const onTerminalReach = props.onTerminalReach
  const resumeAnchor = props.resumeAnchor
  const onResumeAnchorRestored = props.onResumeAnchorRestored
  const scrollRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<HTMLDivElement>(null)
  const terminalVisible = useRef(false)
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

  const captureAnchor = useCallback(() => {
    const scroll = scrollRef.current
    pendingAnchor.current = scroll ? readSourceOverviewViewportAnchor(scroll, topInset) : null
  }, [topInset])

  const cancelAnchorRestore = useCallback(() => {
    pendingAnchor.current = null
    window.cancelAnimationFrame(restoreFrame.current ?? 0)
    restoreFrame.current = undefined
  }, [])

  const restoreAnchor = useCallback((anchor: SourceOverviewViewportAnchor, align: 'start' | 'center' = 'start') => {
    const index = sectionForItem(props.sections, anchor.id)
    if (index < 0) return
    virtualizer.scrollToIndex(index, { align })
    let remainingFrames = 120
    let stableFrames = 0
    const adjust = () => {
      if (remainingFrames <= 0) {
        restoreFrame.current = undefined
        return
      }
      remainingFrames -= 1
      const scroll = scrollRef.current
      const row = scroll
        ? Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]')).find((candidate) => candidate.dataset.itemId === anchor.id)
        : undefined
      const card = row?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
      if (scroll && card) {
        const offset = card.getBoundingClientRect().top - scroll.getBoundingClientRect().top - topInset
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
    const capture = () => captureAnchor()
    window.addEventListener(workbenchRefreshRequestEvent, capture)
    return () => window.removeEventListener(workbenchRefreshRequestEvent, capture)
  }, [captureAnchor])

  useLayoutEffect(() => {
    const anchor = pendingAnchor.current
    pendingAnchor.current = null
    if (!anchor) return
    restoreAnchor(anchor)
  }, [restoreAnchor, sectionsSignature])

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
    restoreAnchor({ id: target, offset: 96 }, 'center')
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
    if (!terminalContent || !terminal || !scroll) return
    const handle = (visible: boolean) => {
      if (visible && !terminalVisible.current) onTerminalReach?.()
      terminalVisible.current = visible
    }
    if (typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver((entries) => handle(Boolean(entries[0]?.isIntersecting)), { root: scroll, threshold: 0.01 })
    observer.observe(terminal)
    return () => observer.disconnect()
  }, [onTerminalReach, terminalContent, terminalKey])

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
  const terminalEnabled = Boolean(terminalContent)

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
      onScroll={() => {
        if (scrollRef.current && scrollRef.current.scrollTop <= 96) setNewItemCount(0)
      }}
      onWheel={cancelAnchorRestore}
      onTouchStart={cancelAnchorRestore}
      onPointerDown={cancelAnchorRestore}
      onKeyDown={cancelAnchorRestore}
    >
      <div data-source-overview-frame className="relative mx-auto w-full max-w-[var(--inteliscope-width-reading)]" style={{ height: virtualizer.getTotalSize() }}>
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
              expandedId={props.expandedId}
              contextIds={props.contextIds}
              detailLoading={props.detailLoading}
              detailError={props.detailError}
              readonly={props.readonly}
              actionMenuCardId={openActionCardId}
              onActionMenuOpenChange={(id, open) => setOpenActionCardId(open ? id : null)}
              onBeforeLayoutChange={captureAnchor}
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
      className="absolute left-1/2 top-4 z-10 -translate-x-1/2"
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
