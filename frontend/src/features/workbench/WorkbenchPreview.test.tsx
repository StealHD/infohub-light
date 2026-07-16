import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { WorkbenchPreview } from './WorkbenchPreview'

describe('WorkbenchPreview', () => {
  it('renders a browser-native Codex-inspired workspace without removed feed modes', () => {
    render(<WorkbenchPreview />)

    const navigation = within(screen.getByRole('navigation', { name: '工作台导航' }))
    expect(navigation.getByRole('link', { name: '信息流' })).toHaveAttribute('href', '/feed')
    expect(navigation.getByRole('link', { name: '收藏' })).toHaveAttribute('href', '/saved')
    expect(navigation.getByRole('link', { name: '历史' })).toHaveAttribute('href', '/history')
    expect(navigation.getByRole('link', { name: '订阅' })).toHaveAttribute('href', '/subscriptions')
    expect(navigation.getByRole('link', { name: '助手连接' })).toHaveAttribute('href', '/agents')
    expect(navigation.getByRole('link', { name: '设置' })).toHaveAttribute('href', '/settings')
    expect(screen.queryByText('稍后读')).not.toBeInTheDocument()
    expect(screen.queryByText('精选')).not.toBeInTheDocument()
    expect(screen.queryByText('日报')).not.toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeInTheDocument()
    expect(screen.getAllByRole('article').length).toBeGreaterThanOrEqual(9)
  })

  it('expands stories in place and adds or removes real Agent context', async () => {
    const user = userEvent.setup()
    render(<WorkbenchPreview />)

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

    await user.click(within(card).getByRole('button', { name: `将 ${title} 移出 Agent 上下文` }))
    expect(within(agent).getByText('0 / 8')).toBeInTheDocument()
  })

  it('uses the short progress rail, preserves new-content control and copies a bounded handoff prompt', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    Element.prototype.scrollIntoView = vi.fn()
    render(<WorkbenchPreview />)

    const progress = within(screen.getByRole('navigation', { name: '信息流进度' }))
    const thirdTick = progress.getByRole('button', { name: '跳转到第 3 条信息' })
    await user.click(thirdTick)
    expect(thirdTick).toHaveAttribute('aria-current', 'true')

    const newItems = screen.getByRole('button', { name: '查看 2 条新内容' })
    await user.click(newItems)
    expect(screen.queryByRole('button', { name: '查看 2 条新内容' })).not.toBeInTheDocument()

    const firstAdd = screen.getAllByRole('button', { name: /加入 Agent 上下文$/ })[0]
    await user.click(firstAdd)
    await user.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
    const question = screen.getByRole('textbox', { name: '交给 OpenClaw 的问题' })
    await user.type(question, '请提炼产品机会')
    await user.click(screen.getByRole('button', { name: '复制并交给 OpenClaw' }))
    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText.mock.calls[0][0]).toContain('请提炼产品机会')
    expect(writeText.mock.calls[0][0]).toContain('get_item')
    expect(screen.getByRole('status')).toHaveTextContent('交接提示词已复制')
  })
})
