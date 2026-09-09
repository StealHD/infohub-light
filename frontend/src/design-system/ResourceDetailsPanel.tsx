import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { AgentInspectorFrame, WorkspaceDrawer } from './AgentWorkspaceLayout'
import { useViewportWidth } from './useViewportWidth'
import { DisclosurePanel } from './DisclosurePanel'
import {
  RESOURCE_DETAILS_DEFAULT_WIDTH, RESOURCE_DETAILS_MIN_WIDTH, canDockResourceDetails,
  clampResourceDetailsWidth, maximumResourceDetailsWidth, readResourceDetailsWidth, writeResourceDetailsWidth,
} from './resourceDetailsPreference'

/** Resource pages reuse the workspace inspector geometry and responsive surfaces. */
export function ResourceDetailsPanel({ open, onClose, userId, title, children }: { open: boolean; onClose: () => void; userId: string; title: string; children: ReactNode }) {
  const viewportWidth = useViewportWidth()
  const [stored, setStored] = useState(() => ({ userId, width: readResourceDetailsWidth(userId) }))
  const [resizing, setResizing] = useState(false)
  const width = clampResourceDetailsWidth(stored.userId === userId ? stored.width : readResourceDetailsWidth(userId), viewportWidth)
  const widthRef = useRef(width)
  useEffect(() => { widthRef.current = width }, [width])
  const update = (clientX: number) => {
    const next = clampResourceDetailsWidth(viewportWidth - clientX, viewportWidth)
    widthRef.current = next; setStored({ userId, width: next })
  }
  const finish = () => { setResizing(false); setStored({ userId, width: writeResourceDetailsWidth(userId, widthRef.current) }) }
  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault(); event.currentTarget.setPointerCapture?.(event.pointerId); setResizing(true); update(event.clientX)
  }
  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizing || (event.currentTarget.hasPointerCapture && !event.currentTarget.hasPointerCapture(event.pointerId))) return
    update(event.clientX)
  }
  const keyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 64 : 24
    let next = widthRef.current
    if (event.key === 'ArrowLeft') next += step
    else if (event.key === 'ArrowRight') next -= step
    else if (event.key === 'Home') next = RESOURCE_DETAILS_MIN_WIDTH
    else if (event.key === 'End') next = maximumResourceDetailsWidth(viewportWidth)
    else return
    event.preventDefault(); next = clampResourceDetailsWidth(next, viewportWidth); widthRef.current = next
    setStored({ userId, width: writeResourceDetailsWidth(userId, next) })
  }
  const content = <div className="quiet-scroll-region h-full min-h-0 overflow-y-auto p-4">{children}</div>
  return canDockResourceDetails(viewportWidth)
    ? <DisclosurePanel open={open} label="自动化任务详情" width={`${width}px`}>
      <div className={`relative h-full min-h-0 pt-[var(--inteliscope-size-page-header)] ${resizing ? 'select-none' : ''}`} onKeyDown={(event) => {
        if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); onClose() }
      }}>
        <div role="separator" tabIndex={0} aria-label="调整任务列表和详情宽度" aria-orientation="vertical"
          aria-valuemin={RESOURCE_DETAILS_MIN_WIDTH} aria-valuemax={maximumResourceDetailsWidth(viewportWidth)} aria-valuenow={width}
          data-testid="resource-details-resizer" title="拖动调整宽度；双击恢复默认"
          className="group absolute inset-y-0 -left-[5px] z-20 w-[10px] cursor-col-resize touch-none focus-visible:outline-none"
          onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture?.(event.pointerId); finish()
          }} onPointerCancel={finish} onKeyDown={keyDown} onDoubleClick={() => {
            const next = clampResourceDetailsWidth(RESOURCE_DETAILS_DEFAULT_WIDTH, viewportWidth); widthRef.current = next
            setStored({ userId, width: writeResourceDetailsWidth(userId, next) })
          }}><span className={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors motion-reduce:transition-none ${resizing ? 'bg-accent' : 'bg-separator group-hover:bg-muted group-focus-visible:bg-accent'}`} /></div>
        <AgentInspectorFrame title={title} onClose={onClose}>{content}</AgentInspectorFrame>
      </div>
    </DisclosurePanel>
    : <WorkspaceDrawer open={open} title={title} placement={viewportWidth < 768 ? 'bottom' : 'right'} frameContent
      onOpenChange={(value) => { if (!value) onClose() }}>{content}</WorkspaceDrawer>
}
