import { useEffect, useRef, useState, type ComponentType, type PointerEvent } from 'react'
import type { Button as SuggestionButton } from './Button'

type Suggestion = {
  title: string
  category: string
  description: string
  prompt: string
  icon: ComponentType<{ size?: number; 'aria-hidden'?: boolean | 'true' | 'false' }>
}

export function SpatialSuggestions({ items, onSelect, Button }: {
  Button: typeof SuggestionButton
  items: Suggestion[]
  onSelect: (prompt: string) => void
}) {
  const [active, setActive] = useState(0)
  const [paused, setPaused] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(false)
  const [cycle, setCycle] = useState(0)
  const touchStart = useRef<{ x: number; y: number } | null>(null)
  const swiped = useRef(false)
  const current = active % items.length
  const move = (direction: number) => {
    setActive(value => (value + direction + items.length) % items.length)
    setCycle(value => value + 1)
  }

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(preference.matches)
    update()
    preference.addEventListener('change', update)
    return () => preference.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (paused || reducedMotion || items.length < 2) return
    const timer = window.setInterval(() => {
      if (!document.hidden) setActive(value => (value + 1) % items.length)
    }, 4500)
    return () => window.clearInterval(timer)
  }, [paused, reducedMotion, cycle, items.length])

  function moveLight(event: PointerEvent<HTMLElement>) {
    if (event.pointerType === 'touch' || reducedMotion) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width))
    const y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))
    event.currentTarget.style.setProperty('--light-on', '1')
    event.currentTarget.style.setProperty('--light-x', `${x * 100}%`)
    event.currentTarget.style.setProperty('--light-y', `${y * 100}%`)
    event.currentTarget.style.setProperty('--tilt-x', `${(0.5 - y) * 10}deg`)
    event.currentTarget.style.setProperty('--tilt-y', `${(x - 0.5) * 14}deg`)
  }

  return <div className="spatial-suggestions" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
    onFocusCapture={() => setPaused(true)} onBlurCapture={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false)
    }} onKeyDown={event => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    move(event.key === 'ArrowRight' ? 1 : -1)
  }}>
    <div className="spatial-suggestions__atmosphere" aria-hidden="true">
      {items.map((item, index) => <span key={item.title} data-tone={index % 3} data-active={index === current} />)}
    </div>
    <div className="spatial-suggestions__stage prompt-suggestion__items" aria-label="进阶建议任务">
      <span className="spatial-suggestions__ghost" data-side="left" aria-hidden="true" />
      <span className="spatial-suggestions__ghost" data-side="right" aria-hidden="true" />
    <div className="spatial-suggestions__cards"
      onTouchStart={event => {
        const touch = event.touches[0]
        touchStart.current = { x: touch.clientX, y: touch.clientY }
        swiped.current = false
      }}
      onTouchEnd={event => {
        if (!touchStart.current) return
        const touch = event.changedTouches[0]
        const dx = touch.clientX - touchStart.current.x
        const dy = touch.clientY - touchStart.current.y
        if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
          swiped.current = true
          move(dx < 0 ? 1 : -1)
        }
        touchStart.current = null
      }}>
      {items.map(({ title, category, description, prompt, icon: Icon }, index) => {
        const offset = (index - current + items.length) % items.length
        const position = offset === 0 ? 'front' : offset === 1 ? 'right' : 'left'
        return <Button key={title} variant="ghost" aria-label={title}
          onFocus={event => { if (event.target.matches(':focus-visible')) setActive(index) }}
          onPointerMove={moveLight}
          onPointerLeave={event => {
            event.currentTarget.style.removeProperty('--light-x')
            event.currentTarget.style.removeProperty('--light-on')
            event.currentTarget.style.removeProperty('--light-y')
            event.currentTarget.style.removeProperty('--tilt-x')
            event.currentTarget.style.removeProperty('--tilt-y')
          }}
          className="spatial-suggestions__card prompt-suggestion__item" data-position={position} data-tone={index % 3}
          onPress={() => {
            if (swiped.current) { swiped.current = false; return }
            if (index === current) onSelect(prompt)
            else { setActive(index); setCycle(value => value + 1) }
          }}>
          <span className="spatial-suggestions__texture" aria-hidden="true" />
          <span className="spatial-suggestions__top"><span className="spatial-suggestions__icon"><Icon size={22} aria-hidden="true" /></span>
            <span className="type-label">{category}</span></span>
          <span className="spatial-suggestions__copy"><span className="type-section-title">{title}</span>
            <span className="type-meta spatial-suggestions__subtitle">深度分析建议</span></span>
          <span className="spatial-suggestions__footer type-meta"><span>{description}</span><span aria-hidden="true">↗</span></span>
        </Button>
      })}
    </div>
    </div>
    <span className="sr-only" aria-live="polite" aria-atomic="true">{current + 1} / {items.length} · {items[current].title}</span>
  </div>
}
