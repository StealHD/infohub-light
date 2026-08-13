import { useLayoutEffect, useState } from 'react'

export function useMeasuredClampOverflow(cardId: string, expanded: boolean, contentKey: string) {
  const [primary, setPrimary] = useState<HTMLElement | null>(null)
  const [secondary, setSecondary] = useState<HTMLElement | null>(null)
  const [overflow, setOverflow] = useState(false)

  useLayoutEffect(() => {
    if (expanded) return
    const elements = [primary, secondary].filter((value): value is HTMLElement => Boolean(value))
    if (elements.length === 0) return
    const measure = () => setOverflow(elements.some((element) => element.scrollHeight > element.clientHeight + 1))
    let active = true
    let frame = window.requestAnimationFrame(() => {
      measure()
      frame = window.requestAnimationFrame(measure)
    })
    void document.fonts?.ready.then(() => {
      if (active) measure()
    })
    window.addEventListener('resize', measure)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    const mutationObserver = typeof MutationObserver === 'undefined' ? null : new MutationObserver(measure)
    elements.forEach((element) => observer?.observe(element))
    elements.forEach((element) => mutationObserver?.observe(element, { childList: true, characterData: true, subtree: true }))
    return () => {
      active = false
      window.cancelAnimationFrame(frame)
      window.removeEventListener('resize', measure)
      observer?.disconnect()
      mutationObserver?.disconnect()
    }
  }, [cardId, contentKey, expanded, primary, secondary])

  return { overflow, primaryRef: setPrimary, secondaryRef: setSecondary }
}
