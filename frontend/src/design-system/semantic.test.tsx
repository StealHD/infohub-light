import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CountBadge, MetaTag, RemovableTag, StatusIndicator } from './semantic'

describe('semantic indicators', () => {
  it('keeps status, metadata and counts as distinct visual semantics', () => {
    render(<>
      <StatusIndicator label="运行中" tone="accent" />
      <MetaTag tone="accent">AI</MetaTag>
      <CountBadge count={3} label="已启用 3 项筛选" />
    </>)

    expect(screen.getByText('运行中').closest('[data-status-indicator]')).toHaveAttribute('data-tone', 'accent')
    expect(screen.getByText('AI').closest('[data-meta-tag]')).toHaveAttribute('data-tone', 'accent')
    expect(screen.getByLabelText('已启用 3 项筛选')).toHaveTextContent('3')
  })

  it('keeps compact status text accessible and reveals it on hover or focus', async () => {
    const browser = userEvent.setup()
    render(<StatusIndicator label="运行中" tone="accent" iconOnly />)

    const indicator = screen.getByText('运行中').closest('[data-status-indicator]')
    expect(indicator).toHaveAttribute('data-icon-only', 'true')
    expect(screen.getByText('运行中')).toHaveClass('sr-only')
    const trigger = indicator?.parentElement
    expect(trigger).toHaveAttribute('tabindex', '0')

    await browser.hover(trigger!)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('运行中')
    await browser.unhover(trigger!)
    trigger?.focus()
    expect(await screen.findByRole('tooltip')).toHaveTextContent('运行中')
  })

  it('gives removable tags a full-size named control and pending lock', async () => {
    const browser = userEvent.setup()
    const remove = vi.fn()
    const view = render(<RemovableTag label="视觉系统" onRemove={remove} />)

    const button = screen.getByRole('button', { name: '移除 视觉系统' })
    expect(button).toHaveClass('size-7')
    await browser.click(button)
    expect(remove).toHaveBeenCalledTimes(1)

    view.rerender(<RemovableTag label="视觉系统" onRemove={remove} pending />)
    expect(screen.getByRole('button', { name: '移除 视觉系统' })).toBeDisabled()
    expect(screen.getByText('视觉系统').closest('[data-removable-tag]')).toHaveAttribute('aria-busy', 'true')
  })
})
