import { act, fireEvent, render, screen } from '@testing-library/react'
import { createRef, useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from './DesignSystemProvider'
import { StableAsyncButton } from './StableAsyncButton'

describe('StableAsyncButton', () => {
  it('keeps idle and pending content in the same layout track', () => {
    const { rerender } = render(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton pending={false} pendingContent="保存中…">保存通知设置</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)

    const idle = screen.getByText('保存通知设置')
    const pending = screen.getByText('保存中…')
    const button = screen.getByRole('button', { name: '保存通知设置' })
    expect(idle.parentElement).toHaveClass('grid')
    expect(pending).toHaveClass('invisible')
    expect(pending).toHaveAttribute('aria-hidden', 'true')

    rerender(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton pending pendingContent="保存中…">保存通知设置</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)

    expect(screen.getByRole('button', { name: '保存中…' })).toBe(button)
    expect(button).toBeDisabled()
    expect(idle.parentElement).toHaveAttribute('aria-busy', 'true')
    expect(idle).toHaveClass('invisible')
    expect(idle).toHaveAttribute('aria-hidden', 'true')
    expect(pending).not.toHaveClass('invisible')
  })

  it('forwards the real button ref', () => {
    const ref = createRef<HTMLButtonElement>()
    render(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton ref={ref} pending={false} pendingContent="处理中…">提交</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)
    expect(ref.current).toBe(screen.getByRole('button', { name: '提交' }))
  })

  it('locks repeated activation synchronously until an accepted Promise settles', async () => {
    let resolve!: () => void
    const operation = new Promise<void>((done) => { resolve = done })
    const onPress = vi.fn(() => operation)
    render(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton pending={false} pendingContent="提交中…" onPress={onPress}>提交</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)

    const button = screen.getByRole('button', { name: '提交' })
    fireEvent.click(button)
    fireEvent.click(button)

    expect(onPress).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: '提交中…' })).toBeDisabled()

    await act(async () => resolve())
    expect(screen.getByRole('button', { name: '提交' })).toBeEnabled()
  })

  it('releases after a rejected Promise and accepts a safe retry', async () => {
    let reject!: (error: Error) => void
    const operation = new Promise<void>((_, fail) => { reject = fail })
    const onPress = vi.fn(() => operation)
    render(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton pending={false} pendingContent="保存中…" onPress={onPress}>保存</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await act(async () => reject(new Error('request failed')))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(onPress).toHaveBeenCalledTimes(2)
  })

  it('covers a form submit while external pending starts and ends', async () => {
    function SubmitFixture() {
      const [pending, setPending] = useState(false)
      return <form onSubmit={(event) => { event.preventDefault(); setPending(true) }}>
        <StableAsyncButton type="submit" pending={pending} pendingContent="发送中…">发送</StableAsyncButton>
        <button type="button" onClick={() => setPending(false)}>完成</button>
      </form>
    }
    render(<MemoryRouter><DesignSystemProvider><SubmitFixture /></DesignSystemProvider></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    expect(screen.getByRole('button', { name: '发送中…' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '完成' }))
    expect(screen.getByRole('button', { name: '发送' })).toBeEnabled()
  })

  it('releases a synchronous action on the next frame', () => {
    vi.useFakeTimers()
    const onPress = vi.fn()
    render(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton pending={false} pendingContent="处理中…" onPress={onPress}>执行</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '执行' }))
    expect(screen.getByRole('button', { name: '处理中…' })).toBeDisabled()
    act(() => vi.runAllTimers())
    expect(screen.getByRole('button', { name: '执行' })).toBeEnabled()
    vi.useRealTimers()
  })

  it('releases its activation lock when the handler throws synchronously', async () => {
    const failure = new Error('synchronous failure')
    const onPress = vi.fn(() => { throw failure })
    const errors: unknown[] = []
    const handleError = (event: ErrorEvent) => { event.preventDefault(); errors.push(event.error) }
    window.addEventListener('error', handleError)
    render(<MemoryRouter><DesignSystemProvider>
      <StableAsyncButton pending={false} pendingContent="处理中…" onPress={onPress}>执行</StableAsyncButton>
    </DesignSystemProvider></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: '执行' }))
    await vi.waitFor(() => expect(errors).toContain(failure))
    expect(screen.getByRole('button', { name: '执行' })).toBeEnabled()
    window.removeEventListener('error', handleError)
  })
})
