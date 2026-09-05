import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

/** Keeps exiting content available visually without keeping it focusable. */
export function DisclosurePanel({ open, label, width, children }: { open: boolean; label: string; width: string; children: ReactNode }) {
  const [retained, setRetained] = useState(open)
  const [visible, setVisible] = useState(false)
  const panel = useRef<HTMLElement>(null)
  const [latestContent, setLatestContent] = useState(children)
  const trigger = useRef<HTMLElement | null>(null)

  if (open && latestContent !== children) setLatestContent(children)

  useEffect(() => {
    let frame = 0
    let timeout = 0
    if (open) {
      if (!panel.current?.contains(document.activeElement) && document.activeElement instanceof HTMLElement) trigger.current = document.activeElement
      frame = window.requestAnimationFrame(() => { setRetained(true); setVisible(true) })
    } else {
      if (panel.current?.contains(document.activeElement)) trigger.current?.focus()
      frame = window.requestAnimationFrame(() => setVisible(false))
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const duration = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--inteliscope-motion-standard')) || 0
      timeout = window.setTimeout(() => setRetained(false), reduced ? 0 : duration)
    }
    return () => { window.cancelAnimationFrame(frame); window.clearTimeout(timeout) }
  }, [open])

  return <aside ref={panel} style={{ '--inteliscope-disclosure-width': width } as CSSProperties} aria-label={label} aria-hidden={!open} inert={!open} data-open={open && visible} className="disclosure-panel flex min-h-0 flex-col bg-surface">
    {(open || retained) && <div className="disclosure-panel-content flex h-full min-h-0 flex-col border-l border-separator">{open ? children : latestContent}</div>}
  </aside>
}
