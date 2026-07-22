import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HeroChangelogPage } from './HeroChangelogPage'

function HashProbe() {
  return <output data-testid="hash-probe">{useLocation().hash}</output>
}

describe('HeroChangelogPage', () => {
  beforeEach(() => {
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  })

  it('renders source-controlled Chinese entries with desktop and compact month navigation', () => {
    render(<MemoryRouter initialEntries={['/changelog#month-2026-07']}><HeroChangelogPage /></MemoryRouter>)

    expect(screen.getByRole('heading', { level: 2, name: '2026 年 7 月' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '更清晰的交互反馈' })).toBeInTheDocument()
    expect(screen.getByText(/鼠标与键盘触发的说明现在优先显示在控件右侧/)).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' })).toHaveAttribute('aria-current', 'location')
    expect(within(screen.getByRole('navigation', { name: '更新月份' })).getByRole('button', { name: '2026 年 7 月' })).toHaveAttribute('aria-current', 'location')
  })

  it('keeps explicit month selection keyboard-operable and updates the hash destination', async () => {
    const browser = userEvent.setup()
    render(<MemoryRouter initialEntries={['/changelog']}><HeroChangelogPage /><HashProbe /></MemoryRouter>)

    const button = within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' })
    button.focus()
    await browser.keyboard('{Enter}')
    expect(button).toHaveAttribute('aria-current', 'location')
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('#month-2026-07')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })
})
