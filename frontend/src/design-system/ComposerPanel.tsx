import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { useInteractOutside } from 'react-aria/useInteractOutside'
import { Popover } from 'react-aria-components'
import { Button } from './Button'
import { X } from './icons'

/** Temporary command controls share the suggestion surface without entering chat. */
export function ComposerPanel({ anchor, children, onClose }: {
  anchor: RefObject<HTMLTextAreaElement | null>
  children: ReactNode
  onClose: () => void
}) {
  const [target, setTarget] = useState<HTMLElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let mounted = true
    const input = anchor.current
    void Promise.resolve().then(() => { if (mounted) setTarget(input?.closest<HTMLElement>('[data-prompt-input]') ?? input) })
    return () => { mounted = false }
  }, [anchor])
  const triggerRef = useMemo(() => ({ current: target }), [target])
  function close() { onClose(); anchor.current?.focus() }
  useInteractOutside({ ref: panelRef, onInteractOutside: onClose })
  if (!target) return null
  return <Popover ref={panelRef} isOpen isNonModal triggerRef={triggerRef} placement="top start" offset={8} containerPadding={12}
    onOpenChange={(open) => { if (!open) close() }}
    className="composer-command-panel z-50 w-[var(--trigger-width)] max-w-[calc(100vw-24px)] overflow-hidden rounded-[var(--inteliscope-radius-panel)] border border-separator bg-overlay p-2 outline-none">
    <div className="flex items-center justify-between gap-2 border-b border-separator pb-1">
      <span className="type-control px-2">快捷操作</span>
      <Button isIconOnly size="sm" variant="ghost" aria-label="关闭快捷操作" onPress={close}><X size={16} aria-hidden="true" /></Button>
    </div>
    <div className="quiet-scroll-region max-h-[min(480px,60dvh)] overflow-y-auto overscroll-contain px-2">{children}</div>
  </Popover>
}
