import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import { FeedRefreshButton } from './FeedRefreshButton'

describe('FeedRefreshButton', () => {
  it('accepts only one start or stop activation before external state renders', () => {
    const onRefresh = vi.fn()
    const onStop = vi.fn()
    const view = render(<MemoryRouter><DesignSystemProvider>
      <FeedRefreshButton role="member" pending={false} stopping={false} canStop={false} onRefresh={onRefresh} onStop={onStop} />
    </DesignSystemProvider></MemoryRouter>)

    const start = screen.getByRole('button', { name: '获取新内容' })
    fireEvent.click(start)
    fireEvent.click(start)
    expect(onRefresh).toHaveBeenCalledOnce()

    view.rerender(<MemoryRouter><DesignSystemProvider>
      <FeedRefreshButton role="member" pending stopping={false} canStop={false} onRefresh={onRefresh} onStop={onStop} />
    </DesignSystemProvider></MemoryRouter>)
    expect(screen.getByRole('button', { name: '正在提交获取新内容' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '正在提交获取新内容' })).toHaveAttribute('aria-busy', 'true')

    view.rerender(<MemoryRouter><DesignSystemProvider>
      <FeedRefreshButton role="member" pending={false} stopping={false} canStop onRefresh={onRefresh} onStop={onStop} />
    </DesignSystemProvider></MemoryRouter>)
    const stop = screen.getByRole('button', { name: '安全停止获取新内容' })
    fireEvent.click(stop)
    fireEvent.click(stop)
    expect(onStop).toHaveBeenCalledOnce()
  })
})
