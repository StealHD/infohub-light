import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from './DesignSystemProvider'
import { OverflowValue } from './OverflowValue'

afterEach(() => vi.restoreAllMocks())

describe('OverflowValue', () => {
  it('keeps an untruncated value as ordinary text', () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(200)
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(100)
    render(<MemoryRouter><DesignSystemProvider>
      <OverflowValue value="短名称" ariaLabel="查看完整名称" />
    </DesignSystemProvider></MemoryRouter>)

    expect(screen.queryByRole('button', { name: '查看完整名称' })).not.toBeInTheDocument()
    expect(screen.getByText('短名称')).toBeVisible()
  })

  it('offers a keyboard and touch-capable Popover when the value overflows', async () => {
    const user = userEvent.setup()
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(100)
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(240)
    render(<MemoryRouter><DesignSystemProvider>
      <OverflowValue value="这是一个非常长的连接名称" ariaLabel="查看完整连接名称" />
    </DesignSystemProvider></MemoryRouter>)

    const trigger = await screen.findByRole('button', { name: '查看完整连接名称' })
    await user.click(trigger)
    expect(await screen.findByRole('dialog', { name: '查看完整连接名称' })).toHaveTextContent('这是一个非常长的连接名称')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '查看完整连接名称' })).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
