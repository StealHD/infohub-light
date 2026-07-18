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
  it('keeps a 200-item collection bounded and exposes at most twelve progress ticks', async () => {
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

  it('removes the progress rail and its reserved gutter from the Quiet Studio Feed', async () => {
    const cards = Array.from({ length: 200 }, (_, index) => toWorkbenchCardModel(makeItem(index)))
    render(<VirtualFeed
      visualVariant="quiet-studio"
      cards={cards}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect((await screen.findAllByTestId('workbench-card')).length).toBeLessThanOrEqual(40)
    expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
    const scroll = screen.getByTestId('workbench-feed-scroll')
    expect(scroll).toHaveAttribute('data-feed-visual', 'quiet-studio')
    expect(scroll.className).not.toContain('pl-16')
  })

  it('keeps the compact progress rail for collection routes', () => {
    render(<VirtualFeed
      visualVariant="collection"
      cards={Array.from({ length: 20 }, (_, index) => toWorkbenchCardModel(makeItem(index)))}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.getAllByRole('button', { name: /跳转到第 .* 条信息/ })).toHaveLength(12)
  })

  it('applies Quiet Studio card hierarchy without leaking it to collection cards', () => {
    const card = toWorkbenchCardModel(makeItem(1))
    const view = render(<VirtualFeed
      visualVariant="quiet-studio"
      cards={[card]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.getByRole('article', { name: '信息 1' })).toHaveAttribute('data-card-visual', 'quiet-studio')
    expect(screen.getByTestId('card-details-item-1')).toHaveAttribute('data-state', 'collapsed')

    view.rerender(<VirtualFeed
      visualVariant="collection"
      cards={[card]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByRole('article', { name: '信息 1' })).toHaveAttribute('data-card-visual', 'collection')
    expect(screen.queryByTestId('card-details-item-1')).not.toBeInTheDocument()
  })

  it('animates Quiet Studio details and exposes a confirmation state for Agent context', () => {
    render(<VirtualFeed
      visualVariant="quiet-studio"
      cards={[toWorkbenchCardModel(makeItem(1))]}
      expandedId="item-1"
      contextIds={['item-1']}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const details = screen.getByTestId('card-details-item-1')
    expect(details).toHaveAttribute('data-state', 'expanded')
    expect(details.className).toContain('grid-rows-[1fr]')
    expect(screen.getByRole('button', { name: '将 信息 1 移出 Agent 上下文' })).toHaveAttribute('data-context-state', 'selected')
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
      {...{ sourceItemIds: initial.map((card) => card.id) }}
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
      {...{ sourceItemIds: ['item-0', 'item-1', 'item-2'] }}
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
      {...{ sourceItemIds: ['item-0', 'item-1', 'item-2'] }}
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
      {...{ sourceItemIds: ['item-0', 'item-1', 'item-2'] }}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.queryByRole('button', { name: /条新内容/ })).not.toBeInTheDocument()
  })

  it('detects a newly added ID in a fixed-length rolling window', async () => {
    const initial = [0, 1].map((index) => toWorkbenchCardModel(makeItem(index)))
    const view = render(<VirtualFeed
      cards={initial}
      {...{ sourceItemIds: ['item-0', 'item-1'] }}
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
      cards={[1, 2].map((index) => toWorkbenchCardModel(makeItem(index)))}
      {...{ sourceItemIds: ['item-1', 'item-2'] }}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(await screen.findByRole('button', { name: '查看 1 条新内容' })).toBeInTheDocument()
  })

  it('clears the new-content badge when the user manually returns to the bottom zone', async () => {
    const initial = [0, 1].map((index) => toWorkbenchCardModel(makeItem(index)))
    const view = render(<VirtualFeed
      cards={initial}
      {...{ sourceItemIds: ['item-0', 'item-1'] }}
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
      {...{ sourceItemIds: ['item-0', 'item-1', 'item-2'] }}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(await screen.findByRole('button', { name: '查看 1 条新内容' })).toBeInTheDocument()

    scroll.scrollTop = 1280
    fireEvent.scroll(scroll)
    expect(screen.queryByRole('button', { name: '查看 1 条新内容' })).not.toBeInTheDocument()
  })
})
