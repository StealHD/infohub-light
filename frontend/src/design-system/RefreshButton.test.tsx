import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from './DesignSystemProvider'
import { REFRESH_FEEDBACK_MIN_MS, RefreshButton, RefreshIconButton } from './RefreshButton'

afterEach(() => vi.useRealTimers())

describe('RefreshButton', () => {
  it('provides an icon-only refresh trigger with nearby Tooltip and shared pending behavior', async () => {
    const user = userEvent.setup()
    const view = render(<MemoryRouter><DesignSystemProvider>
      <RefreshIconButton pending={false} label="重新载入" tooltip="重新载入本地数据" tooltipDelay={0} />
    </DesignSystemProvider></MemoryRouter>)

    await user.hover(screen.getByRole('button', { name: '重新载入' }))
    expect(await screen.findByRole('tooltip')).toHaveTextContent('重新载入本地数据')
    expect(screen.getByRole('button', { name: '重新载入' })).toHaveClass('pointer-coarse:min-h-11', 'pointer-coarse:min-w-11')

    view.rerender(<MemoryRouter><DesignSystemProvider>
      <RefreshIconButton pending label="重新载入" tooltip="重新载入本地数据" tooltipDelay={0} />
    </DesignSystemProvider></MemoryRouter>)
    expect(screen.getByRole('button', { name: '正在重新载入' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '正在重新载入' }).querySelector('svg')).toHaveClass('animate-spin', 'motion-reduce:animate-none')
  })

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

  it('keeps the activation locked until the accepted Promise and minimum feedback both finish', async () => {
    vi.useFakeTimers()
    let resolve!: () => void
    const operation = new Promise<void>((done) => { resolve = done })
    const onPress = vi.fn(() => operation)
    render(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending={false} label="刷新来源" onPress={onPress} />
    </DesignSystemProvider></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: '刷新来源' }))
    act(() => vi.advanceTimersByTime(REFRESH_FEEDBACK_MIN_MS))
    expect(screen.getByRole('button', { name: '正在刷新来源' })).toBeDisabled()

    await act(async () => resolve())
    expect(screen.getByRole('button', { name: '刷新来源' })).toBeEnabled()
  })

  it('keeps the activation locked after a fast Promise until external pending also settles', async () => {
    vi.useFakeTimers()
    const onPress = vi.fn(() => Promise.resolve())
    const view = render(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending={false} label="重试列表" onPress={onPress} />
    </DesignSystemProvider></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: '重试列表' }))
    await act(async () => {})
    view.rerender(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending label="重试列表" onPress={onPress} />
    </DesignSystemProvider></MemoryRouter>)
    act(() => vi.advanceTimersByTime(REFRESH_FEEDBACK_MIN_MS))
    expect(screen.getByRole('button', { name: '正在重试列表' })).toBeDisabled()

    view.rerender(<MemoryRouter><DesignSystemProvider>
      <RefreshButton pending={false} label="重试列表" onPress={onPress} />
    </DesignSystemProvider></MemoryRouter>)
    expect(screen.getByRole('button', { name: '重试列表' })).toBeEnabled()
  })
})
