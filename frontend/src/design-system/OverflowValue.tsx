import { Popover } from '@heroui/react'
import { useCallback, useEffect, useRef, useState } from 'react'

type OverflowValueProps = {
  ariaLabel: string
  className?: string
  lines?: 1 | 2
  value: string
}

export function OverflowValue({ ariaLabel, className = '', lines = 1, value }: OverflowValueProps) {
  const valueRef = useRef<HTMLSpanElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [overflowing, setOverflowing] = useState(false)
  const [open, setOpen] = useState(false)

  const measure = useCallback(() => {
    const element = valueRef.current
    if (!element) return
    setOverflowing(element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight)
  }, [])

  useEffect(() => {
    measure()
    const element = valueRef.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [measure, value])

  const clamp = lines === 2 ? 'line-clamp-2' : 'truncate'
  const content = <span ref={valueRef} className={`block min-w-0 ${clamp} ${className}`}>{value}</span>
  if (!overflowing) return content

  return <Popover isOpen={open} onOpenChange={(next) => {
    setOpen(next)
    if (!next) window.requestAnimationFrame(() => triggerRef.current?.focus())
  }}>
    <Popover.Trigger<'button'>
      ref={triggerRef}
      aria-label={ariaLabel}
      type="button"
      className="pointer-events-auto block min-w-0 max-w-full cursor-pointer rounded-[var(--inteliscope-radius-compact)] text-left outline-none focus-visible:outline-2 focus-visible:outline-focus"
    >{content}</Popover.Trigger>
    <Popover.Content placement="bottom start" offset={6} containerPadding={8} className="z-50 max-w-[min(28rem,calc(100vw-16px))] p-0">
      <Popover.Dialog aria-label={ariaLabel} className="p-3">
        <p className="type-control [overflow-wrap:anywhere] text-foreground">{value}</p>
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}
