import { useCallback, useEffect, useRef, type FocusEvent, type KeyboardEvent, type PointerEvent, type RefObject } from 'react'

export const interactivePopoverCloseDelayMs = 160

type InteractivePopoverElement = HTMLElement | null

function interactivePopoverDelay() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 0
  const value = Number.parseFloat(window.getComputedStyle(document.documentElement).getPropertyValue('--inteliscope-motion-standard'))
  return Number.isFinite(value) ? value : interactivePopoverCloseDelayMs
}

export function useHoverPopoverIntent({
  contentRef,
  open,
  setOpen,
  triggerRef,
}: {
  contentRef: RefObject<InteractivePopoverElement>
  open: boolean
  setOpen: (open: boolean) => void
  triggerRef: RefObject<InteractivePopoverElement>
}) {
  const closeTimer = useRef<number | null>(null)
  const focusTimer = useRef<number | null>(null)
  const restoringTriggerFocus = useRef(false)
  const suppressFocusOpen = useRef(false)

  const clearCloseTimer = useCallback(() => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
    closeTimer.current = null
  }, [])

  const restoreTriggerFocus = useCallback(() => {
    if (focusTimer.current !== null) window.clearTimeout(focusTimer.current)
    focusTimer.current = window.setTimeout(() => {
      focusTimer.current = null
      triggerRef.current?.focus()
      restoringTriggerFocus.current = false
      suppressFocusOpen.current = false
    })
  }, [triggerRef])

  const scheduleClose = useCallback(() => {
    clearCloseTimer()
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null
      setOpen(false)
    }, interactivePopoverDelay())
  }, [clearCloseTimer, setOpen])

  const openFromPointer = useCallback((event: PointerEvent<HTMLElement>) => {
    if (event.pointerType === 'touch') return
    restoringTriggerFocus.current = false
    suppressFocusOpen.current = false
    clearCloseTimer()
    setOpen(true)
  }, [clearCloseTimer, setOpen])

  const leaveFromPointer = useCallback((event: PointerEvent<HTMLElement>) => {
    if (event.pointerType !== 'touch') scheduleClose()
  }, [scheduleClose])

  const openFromFocus = useCallback(() => {
    if (restoringTriggerFocus.current || suppressFocusOpen.current) return
    clearCloseTimer()
    setOpen(true)
  }, [clearCloseTimer, setOpen])

  const closeFromBlur = useCallback((event: FocusEvent<HTMLElement>) => {
    const nextTarget = event.relatedTarget as Node | null
    if (triggerRef.current?.contains(nextTarget) || contentRef.current?.contains(nextTarget)) return
    scheduleClose()
  }, [contentRef, scheduleClose, triggerRef])

  const closeFromEscape = useCallback((event: Pick<KeyboardEvent<HTMLElement>, 'key' | 'preventDefault' | 'stopPropagation'>) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    event.stopPropagation()
    restoringTriggerFocus.current = true
    suppressFocusOpen.current = true
    setOpen(false)
    restoreTriggerFocus()
  }, [restoreTriggerFocus, setOpen])

  const onOpenChange = useCallback((next: boolean) => {
    clearCloseTimer()
    if (restoringTriggerFocus.current) {
      if (!next) setOpen(false)
      return
    }
    if (next) {
      setOpen(true)
      return
    }
    setOpen(false)
    suppressFocusOpen.current = false
  }, [clearCloseTimer, setOpen])

  useEffect(() => () => {
    clearCloseTimer()
    if (focusTimer.current !== null) window.clearTimeout(focusTimer.current)
  }, [clearCloseTimer])

  useEffect(() => {
    if (!open) return
    const onDocumentKeyDown = (event: globalThis.KeyboardEvent) => {
      const target = event.target as Node | null
      if (!triggerRef.current?.contains(target) && !contentRef.current?.contains(target)) return
      closeFromEscape(event)
    }
    document.addEventListener('keydown', onDocumentKeyDown, true)
    return () => document.removeEventListener('keydown', onDocumentKeyDown, true)
  }, [closeFromEscape, contentRef, open, triggerRef])

  return {
    onOpenChange,
    surfaceProps: { onBlur: closeFromBlur, onFocus: openFromFocus, onKeyDownCapture: closeFromEscape, onPointerEnter: openFromPointer, onPointerLeave: leaveFromPointer },
    triggerProps: { onBlur: closeFromBlur, onFocus: openFromFocus, onPointerEnter: openFromPointer, onPointerLeave: leaveFromPointer },
    visible: open,
  }
}
