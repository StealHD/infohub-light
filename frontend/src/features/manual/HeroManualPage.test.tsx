import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import { HeroManualPage } from './HeroManualPage'

function HashProbe() {
  return <output data-testid="hash-probe">{useLocation().hash}</output>
}

function renderManual(path = '/manual') {
  return render(<MemoryRouter initialEntries={[path]}>
    <DesignSystemProvider>
      <HeroManualPage />
      <HashProbe />
    </DesignSystemProvider>
  </MemoryRouter>)
}

describe('HeroManualPage', () => {
  beforeEach(() => {
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
  })

  it('renders the source-controlled operating guide, maintenance rule, and safe release destination', () => {
    renderManual('/manual#manual-start')

    expect(screen.getByText('Inteliscope 操作手册')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '快速开始' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Agent 与 OpenClaw' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '查看操作结果' })).toBeInTheDocument()
    expect(screen.getByText(/页面顶部会短暂显示可关闭的结果提示/)).toBeInTheDocument()
    expect(screen.getByText(/每次产品代码合并都由 Test Gate 检查/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /打开订阅与来源/ })).toHaveAttribute('href', '/subscriptions')
    expect(screen.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('href', PRODUCT_RELEASES_URL)
    expect(screen.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('rel', 'noopener noreferrer')
    expect(within(screen.getByRole('navigation', { name: '手册章节目录' })).getByRole('button', { name: '快速开始' })).toHaveAttribute('aria-current', 'location')
  })

  it('keeps a plain manual entry at the page introduction', () => {
    renderManual()

    expect(HTMLElement.prototype.scrollTo).toHaveBeenCalledWith({ top: 0 })
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it('keeps explicit section selection keyboard-operable and updates the hash destination', async () => {
    const browser = userEvent.setup()
    renderManual()

    const button = within(screen.getByRole('navigation', { name: '手册章节目录' })).getByRole('button', { name: '账户与设置' })
    button.focus()
    await browser.keyboard('{Enter}')

    expect(button).toHaveAttribute('aria-current', 'location')
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('#manual-account')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })
})
