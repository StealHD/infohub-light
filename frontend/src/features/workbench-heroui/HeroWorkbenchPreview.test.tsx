import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HeroWorkbenchPreview } from './HeroWorkbenchPreview'

beforeEach(() => {
  Object.defineProperty(window, 'ResizeObserver', {
    configurable: true,
    value: class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  })
  Object.defineProperty(globalThis, 'ResizeObserver', {
    configurable: true,
    value: window.ResizeObserver,
  })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
  Element.prototype.scrollIntoView = vi.fn()
})

describe('HeroWorkbenchPreview', () => {
  it('renders the isolated HeroUI workbench with the shared story and navigation model', () => {
    const { container } = render(<HeroWorkbenchPreview />)

    const root = container.querySelector('[data-ui-system="heroui"]')
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(root).toHaveClass('dark')
    expect(container.querySelector('[class*="Mui"]')).not.toBeInTheDocument()

    const navigation = within(screen.getByRole('navigation', { name: '工作台导航' }))
    expect(navigation.getByRole('link', { name: '信息流' })).toHaveAttribute('href', '/feed')
    expect(navigation.getByRole('link', { name: '收藏' })).toHaveAttribute('href', '/saved')
    expect(navigation.getByRole('link', { name: '历史' })).toHaveAttribute('href', '/history')
    expect(navigation.getByRole('link', { name: '订阅' })).toHaveAttribute('href', '/subscriptions')
    expect(navigation.getByRole('link', { name: '助手连接' })).toHaveAttribute('href', '/agents')
    expect(navigation.getByRole('link', { name: '设置' })).toHaveAttribute('href', '/settings')
    expect(screen.queryByRole('link', { name: /切换到 MUI/ })).not.toBeInTheDocument()
    expect(screen.queryByText('稍后读')).not.toBeInTheDocument()
    expect(screen.queryByText('精选')).not.toBeInTheDocument()
    expect(screen.queryByText('日报')).not.toBeInTheDocument()

    const cards = screen.getAllByRole('article')
    expect(cards).toHaveLength(10)
    expect(cards[0]).toHaveAttribute('data-slot', 'card')
    expect(cards[0]).toHaveClass('card')
  })

  it('expands a HeroUI card, saves it and moves it in and out of Agent context', async () => {
    const user = userEvent.setup()
    render(<HeroWorkbenchPreview />)

    const title = '从任务到结果：AI 原生产品的交互范式演进'
    const card = screen.getByRole('article', { name: title })
    const expand = within(card).getByRole('button', { name: `展开 ${title}` })
    expect(expand).toHaveAttribute('aria-expanded', 'false')
    await user.click(expand)
    expect(expand).toHaveAttribute('aria-expanded', 'true')
    expect(within(card).getByText(/产品设计的重点正在从功能堆叠转向结果交付/)).toBeVisible()

    await user.click(within(card).getByRole('button', { name: `收藏 ${title}` }))
    expect(within(card).getByRole('button', { name: `取消收藏 ${title}` })).toBeInTheDocument()

    await user.click(within(card).getByRole('button', { name: `将 ${title} 加入 Agent 上下文` }))
    await user.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    const agent = screen.getByRole('complementary', { name: 'OpenClaw 上下文' })
    expect(within(agent).getByText('1 / 8')).toBeInTheDocument()
    expect(within(agent).getByText(title)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: `将 ${title} 移出 Agent 上下文` })).toBeInTheDocument()

    await user.click(within(agent).getByRole('button', { name: `移除 ${title}` }))
    expect(within(agent).getByText('0 / 8')).toBeInTheDocument()
  })

  it('supports search, short-rail navigation, new content and a bounded copied handoff prompt', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    render(<HeroWorkbenchPreview />)

    const progress = within(screen.getByRole('navigation', { name: '信息流进度' }))
    const thirdTick = progress.getByRole('button', { name: '跳转到第 3 条信息' })
    await user.click(thirdTick)
    expect(thirdTick).toHaveAttribute('aria-current', 'true')

    await user.click(screen.getByRole('button', { name: '查看 2 条新内容' }))
    expect(screen.queryByRole('button', { name: '查看 2 条新内容' })).not.toBeInTheDocument()

    await user.type(screen.getByRole('searchbox', { name: '搜索信息流' }), 'OpenClaw')
    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByRole('article', { name: 'Remote MCP 让本地 Agent 安全读取远程个人数据' })).toBeInTheDocument()
    await user.clear(screen.getByRole('searchbox', { name: '搜索信息流' }))

    await user.click(screen.getAllByRole('button', { name: /加入 Agent 上下文$/ })[0])
    await user.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    await user.type(screen.getByRole('textbox', { name: '交给 OpenClaw 的问题' }), '请提炼产品机会')
    await user.click(screen.getByRole('button', { name: '复制并交给 OpenClaw' }))
    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText.mock.calls[0][0]).toContain('请提炼产品机会')
    expect(writeText.mock.calls[0][0]).toContain('get_item')
    expect(screen.getByRole('status')).toHaveTextContent('交接提示词已复制')
  })

  it('limits Agent context to eight stories', async () => {
    const user = userEvent.setup()
    render(<HeroWorkbenchPreview />)

    const addButtons = screen.getAllByRole('button', { name: /加入 Agent 上下文$/ })
    for (const button of addButtons.slice(0, 8)) await user.click(button)

    await user.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    expect(screen.getByText('8 / 8')).toBeInTheDocument()
    expect(addButtons[8]).toBeDisabled()
    expect(addButtons[9]).toBeDisabled()
  })
})
