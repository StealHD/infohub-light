import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter, MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import { changelogMonths } from './changelogEntries'
import { HeroChangelogPage } from './HeroChangelogPage'

function HashProbe() {
  return <output data-testid="hash-probe">{useLocation().hash}</output>
}

function renderChangelog(path = '/changelog') {
  return render(<MemoryRouter initialEntries={[path]}>
    <DesignSystemProvider>
      <HeroChangelogPage />
      <HashProbe />
    </DesignSystemProvider>
  </MemoryRouter>)
}

function renderBrowserChangelog() {
  return render(<BrowserRouter>
    <DesignSystemProvider>
      <HeroChangelogPage />
      <HashProbe />
    </DesignSystemProvider>
  </BrowserRouter>)
}

describe('HeroChangelogPage', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/changelog')
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders source-controlled Chinese entries as an accessible timeline with responsive month navigation', () => {
    renderChangelog('/changelog#month-2026-07')

    expect(screen.getByRole('heading', { level: 2, name: '2026 年 7 月' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '信息流末尾有了明确提示' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '常用页面打开更快，后台列表更轻' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'OpenClaw 可按名称订阅 YouTube 频道' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '全局与单源周期不再重复抓取' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '更新日志改为清晰时间线' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '可直接订阅 YouTube 公开频道' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '操作手册与发布入口' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '操作结果不再挤压页面' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: '更清晰的交互反馈' })).toBeInTheDocument()
    expect(screen.getByText(/每次产品代码合并都由 Test Gate 验证/)).toBeInTheDocument()
    expect(screen.getByText(/鼠标与键盘触发的说明现在优先显示在控件右侧/)).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' })).toHaveAttribute('aria-current', 'location')
    expect(within(screen.getByRole('navigation', { name: '更新月份' })).getByRole('button', { name: '2026 年 7 月' })).toHaveAttribute('aria-current', 'location')
    const timeline = screen.getByRole('list', { name: '2026 年 7 月更新记录' })
    const entries = timeline.querySelectorAll(':scope > [data-timeline-item]')
    expect(entries.length).toBeGreaterThan(2)
    expect(entries[0]).toHaveAttribute('aria-current', 'true')
    expect(entries[1]).not.toHaveAttribute('aria-current')
    expect(entries[2]).not.toHaveAttribute('aria-current')
    expect(within(entries[0] as HTMLElement).getByText('最终页才提示')).toBeVisible()
    expect(within(entries[0] as HTMLElement).getByText('AI 后台低优先级生成')).toBeVisible()
    expect(within(entries[0] as HTMLElement).getByText('2026-07-29')).toHaveAttribute('datetime', '2026-07-29')
    expect(within(entries[1] as HTMLElement).getByText('低频页面按需加载')).toBeVisible()
    expect(within(entries[1] as HTMLElement).getByText('稳定数据减少重复请求')).toBeVisible()
    expect(within(entries[1] as HTMLElement).getByText('2026-07-29')).toHaveAttribute('datetime', '2026-07-29')
    expect(within(entries[2] as HTMLElement).getByText('通用解析入口')).toBeVisible()
    expect(within(entries[2] as HTMLElement).getByText('名称由 Agent 发现')).toBeVisible()
    expect(within(entries[2] as HTMLElement).getByText('2026-07-29')).toHaveAttribute('datetime', '2026-07-29')
    expect(within(entries[3] as HTMLElement).getByText('默认跟随全局')).toBeVisible()
    expect(within(entries[3] as HTMLElement).getByText('卡片信息更准确')).toBeVisible()
    expect(within(entries[3] as HTMLElement).getByText('2026-07-28')).toHaveAttribute('datetime', '2026-07-28')
  })

  it('keeps a plain changelog entry at the page introduction', async () => {
    renderChangelog()

    await waitFor(() => expect(HTMLElement.prototype.scrollTo).toHaveBeenCalledWith({ top: 0 }))
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it('keeps explicit month selection keyboard-operable and scrolls exactly once', async () => {
    const browser = userEvent.setup()
    renderChangelog()

    const button = within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' })
    button.focus()
    await browser.keyboard('{Enter}')
    expect(button).toHaveAttribute('aria-current', 'location')
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('#month-2026-07')
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
  })

  it('uses immediate explicit scrolling when Reduced Motion is enabled', async () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    const browser = userEvent.setup()
    renderChangelog()

    await browser.click(within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' }))

    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
  })

  it('uses the browser hash after passive scrolling when recording an explicit month selection', async () => {
    const priorMonth = {
      id: 'month-2026-06' as const,
      label: '2026 年 6 月',
      entries: [{
        date: '2026-06-30',
        title: '上一月更新',
        summary: '用于验证跨月份历史导航。',
        items: [{ title: '历史记录', description: '显式返回月份时应创建可返回的浏览记录。' }],
      }],
    }
    changelogMonths.push(priorMonth)
    window.history.replaceState({}, '', '/changelog#month-2026-07')

    try {
      const browser = userEvent.setup()
      const { container } = renderBrowserChangelog()
      await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1))
      vi.mocked(Element.prototype.scrollIntoView).mockClear()

      const scrollRegion = container.querySelector<HTMLElement>('.quiet-scroll-region.h-full')
      expect(scrollRegion).not.toBeNull()
      fireEvent.scroll(scrollRegion as HTMLElement)
      await waitFor(() => expect(window.location.hash).toBe('#month-2026-06'))

      const pushState = vi.spyOn(window.history, 'pushState')
      await browser.click(within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' }))

      await waitFor(() => expect(pushState).toHaveBeenCalledTimes(1))
      expect(window.location.hash).toBe('#month-2026-07')
      await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1))
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })

      vi.mocked(Element.prototype.scrollIntoView).mockClear()
      window.history.back()
      await waitFor(() => expect(screen.getByTestId('hash-probe')).toHaveTextContent('#month-2026-06'))
      await waitFor(() => expect(within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 6 月' })).toHaveAttribute('aria-current', 'location'))
      await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1))
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })

      vi.mocked(Element.prototype.scrollIntoView).mockClear()
      window.history.forward()
      await waitFor(() => expect(screen.getByTestId('hash-probe')).toHaveTextContent('#month-2026-07'))
      await waitFor(() => expect(within(screen.getByRole('navigation', { name: '更新月份时间线' })).getByRole('button', { name: '2026 年 7 月' })).toHaveAttribute('aria-current', 'location'))
      await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1))
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
    } finally {
      changelogMonths.pop()
    }
  })
})
