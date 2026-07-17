import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HeroActionNotice } from './HeroActionNotice'

describe('HeroActionNotice', () => {
  afterEach(() => vi.useRealTimers())

  it.each([
    ['succeeded', 4_000],
    ['partial', 8_000],
    ['failed', 8_000],
    ['blocked', 8_000],
  ] as const)('auto-dismisses %s feedback after %i ms', (phase, duration) => {
    vi.useFakeTimers()
    const onClose = vi.fn()
    render(<HeroActionNotice phase={phase} message={`${phase} notice`} onClose={onClose} />)

    act(() => vi.advanceTimersByTime(duration - 1))
    expect(onClose).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(1))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('lets the user close feedback immediately', () => {
    const onClose = vi.fn()
    render(<HeroActionNotice phase="failed" message="manual notice" onClose={onClose} />)

    fireEvent.click(screen.getByRole('button', { name: '关闭通知' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('does not restart the timer when polling rerenders with the same event', () => {
    vi.useFakeTimers()
    const firstClose = vi.fn()
    const latestClose = vi.fn()
    const view = render(<HeroActionNotice phase="succeeded" message="same polled event" onClose={firstClose} />)

    act(() => vi.advanceTimersByTime(2_000))
    view.rerender(<HeroActionNotice phase="succeeded" message="same polled event" onClose={latestClose} />)
    act(() => vi.advanceTimersByTime(1_999))
    expect(latestClose).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(1))
    expect(firstClose).not.toHaveBeenCalled()
    expect(latestClose).toHaveBeenCalledOnce()
  })
})
