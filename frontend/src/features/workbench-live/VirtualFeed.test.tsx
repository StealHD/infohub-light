import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { FeedItem } from '../../api/types'
import { toWorkbenchCardModel } from './workbenchModel'
import { VirtualFeed } from './VirtualFeed'

const makeItem = (index: number): FeedItem => ({
  id: `item-${index}`,
  title: `信息 ${index}`,
  url: `https://example.com/${index}`,
  source: '测试来源',
  summary_zh: `这是第 ${index} 条摘要`,
  published_at: new Date(Date.UTC(2026, 6, 1, 0, index)).toISOString(),
  channel: 'AI',
  topics: ['Codex'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
})

describe('VirtualFeed', () => {
  it('keeps a 200-item Feed bounded and exposes at most twelve progress ticks', async () => {
    const cards = Array.from({ length: 200 }, (_, index) => toWorkbenchCardModel(makeItem(index)))
    render(<VirtualFeed
      cards={cards}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect((await screen.findAllByTestId('workbench-card')).length).toBeLessThanOrEqual(40)
    expect(screen.getAllByRole('button', { name: /跳转到第 .* 条信息/ })).toHaveLength(12)
  })

  it('expands in place without implicitly marking the item read', async () => {
    const user = userEvent.setup()
    const onToggleExpanded = vi.fn()
    const onItemAction = vi.fn()
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={onItemAction}
    />)

    await user.click(await screen.findByRole('button', { name: '展开 信息 1' }))
    expect(onToggleExpanded).toHaveBeenCalledWith('item-1')
    expect(onItemAction).not.toHaveBeenCalled()
  })

  it('keeps viewer mutations disabled while open and copy remain available', async () => {
    const user = userEvent.setup()
    const copy = vi.fn()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      expandedId="item-1"
      contextIds={[]}
      readonly
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const card = await screen.findByRole('article', { name: '信息 1' })
    expect(within(card).getByRole('link', { name: '打开 信息 1 原文' })).toHaveAttribute('href', 'https://example.com/1')
    expect(within(card).getByRole('button', { name: '收藏 信息 1' })).toBeDisabled()
    await user.click(within(card).getByRole('button', { name: '更多操作 信息 1' }))
    expect(within(card).getByRole('button', { name: '标记已读' })).toBeDisabled()
    expect(within(card).getByRole('button', { name: '忽略' })).toBeDisabled()
    await user.click(within(card).getByRole('button', { name: '复制摘要' }))
    expect(copy).toHaveBeenCalledWith('这是第 1 条摘要')
  })

  it('preserves an away-from-bottom anchor and offers an explicit new-item jump', async () => {
    const user = userEvent.setup()
    const initial = [0, 1].map((index) => toWorkbenchCardModel(makeItem(index)))
    const view = render(<VirtualFeed
      cards={initial}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const scroll = screen.getByTestId('workbench-feed-scroll')
    Object.defineProperties(scroll, {
      scrollHeight: { configurable: true, value: 2000 },
      clientHeight: { configurable: true, value: 720 },
      scrollTop: { configurable: true, writable: true, value: 200 },
    })
    fireEvent.scroll(scroll)

    view.rerender(<VirtualFeed
      cards={[...initial, toWorkbenchCardModel(makeItem(2))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(await screen.findByRole('button', { name: '查看 1 条新内容' })).toBeInTheDocument()
    expect(scroll.scrollTop).toBe(200)
    await user.click(screen.getByRole('button', { name: '查看 1 条新内容' }))
    expect(screen.queryByRole('button', { name: '查看 1 条新内容' })).not.toBeInTheDocument()
  })

  it('does not label newly revealed filtered cards as new source content', () => {
    const initial = [0, 1].map((index) => toWorkbenchCardModel(makeItem(index)))
    const view = render(<VirtualFeed
      cards={initial}
      sourceItemCount={3}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const scroll = screen.getByTestId('workbench-feed-scroll')
    Object.defineProperties(scroll, {
      scrollHeight: { configurable: true, value: 2000 },
      clientHeight: { configurable: true, value: 720 },
      scrollTop: { configurable: true, writable: true, value: 200 },
    })
    fireEvent.scroll(scroll)

    view.rerender(<VirtualFeed
      cards={[...initial, toWorkbenchCardModel(makeItem(2))]}
      sourceItemCount={3}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.queryByRole('button', { name: /条新内容/ })).not.toBeInTheDocument()
  })
})
