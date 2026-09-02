import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from './DesignSystemProvider'
import { REFRESH_FEEDBACK_MIN_MS, RefreshButton } from './RefreshButton'

afterEach(() => vi.useRealTimers())

describe('RefreshButton', () => {
  it('starts rotating immediately and keeps fast refresh feedback perceptible', () => {
    vi.useFakeTimers()
    const onPress = vi.fn()
    render(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending={false} onPress={onPress} />
    </DesignSystemProvider></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    const button = screen.getByRole('button', { name: '正在刷新' })
    const content = button.querySelector('[data-refresh-button-content]')
    expect(onPress).toHaveBeenCalledOnce()
    expect(button).toBeDisabled()
    expect(content).toHaveAttribute('aria-busy', 'true')
    expect(content?.querySelector('svg')).toHaveClass('animate-spin', 'motion-reduce:animate-none')

    act(() => vi.advanceTimersByTime(REFRESH_FEEDBACK_MIN_MS - 1))
    expect(button).toBeDisabled()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByRole('button', { name: '刷新' })).toBeEnabled()
  })

  it('synchronously rejects repeated activation', () => {
    vi.useFakeTimers()
    const onPress = vi.fn()
    render(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending={false} onPress={onPress} />
    </DesignSystemProvider></MemoryRouter>)

    const button = screen.getByRole('button', { name: '刷新' })
    fireEvent.click(button)
    fireEvent.click(button)

    expect(onPress).toHaveBeenCalledOnce()
  })

  it('keeps the icon rotating for the complete external request', () => {
    const { rerender } = render(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending label="刷新日志" />
    </DesignSystemProvider></MemoryRouter>)
    const button = screen.getByRole('button', { name: '正在刷新日志' })
    expect(button).toBeDisabled()
    expect(button.querySelector('svg')).toHaveClass('animate-spin')

    rerender(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending={false} label="刷新日志" />
    </DesignSystemProvider></MemoryRouter>)
    expect(screen.getByRole('button', { name: '刷新日志' })).toBeEnabled()
  })
})
