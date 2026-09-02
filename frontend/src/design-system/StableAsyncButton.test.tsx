import { render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

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
})
