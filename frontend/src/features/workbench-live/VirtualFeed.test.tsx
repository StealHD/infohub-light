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

const socialItem = (): FeedItem => ({
  id: 'social-x',
  title: '@thsottiaux: Oops... I did it again. Enjoy reset usage limits for all paid users fo...',
  url: 'https://x.com/thsottiaux/status/1',
  source: 'X · @thsottiaux',
  source_type: 'apify_social',
  summary_zh: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.',
  published_at: '2026-07-18T08:00:00Z',
  channel: '其他',
  topics: ['行业动态'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
  presentation: {
    version: 2,
    source: { id: 'x-source', catalog_type: 'apify_social', platform: 'x', name: 'X · @thsottiaux' },
    author: { name: 'Tibo', kind: 'person' },
    timing: { published_at: '2026-07-18T08:00:00Z', fetched_at: '2026-07-18T08:05:00Z' },
    links: { canonical_url: 'https://x.com/thsottiaux/status/1', source_url: 'https://x.com/thsottiaux' },
    content: {
      title: '@thsottiaux: Oops... I did it again. Enjoy reset usage limits for all paid users fo...',
      title_origin: 'generated',
      excerpt: 'Oops... I did it again. Enjoy reset usage limits for all paid users.',
      body_text: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.',
      content_kind: 'post_body',
      excerpt_truncated: true,
      body_truncated: false,
    },
    taxonomy: { channel: '其他', configured_topics: [], inferred_topics: ['行业动态'], topics: ['行业动态'], entities: [] },
    engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
    analysis: { status: 'ai', score: 7, signal_strength: 'medium', signal_type: 'update', summary_zh: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.' },
  },
})

describe('VirtualFeed', () => {
  it('keeps a 200-item collection bounded without rendering a progress rail', async () => {
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
    expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
  })

  it('removes the progress rail and its reserved gutter from the Quiet Studio Feed', async () => {
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
    expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
    const scroll = screen.getByTestId('workbench-feed-scroll')
    expect(scroll).toHaveAttribute('data-feed-visual', 'quiet-studio')
    expect(scroll.className).not.toContain('pl-16')
  })

  it('uses the Quiet Studio surface without a reserved rail gutter for collection routes', () => {
    render(<VirtualFeed
      cards={Array.from({ length: 20 }, (_, index) => toWorkbenchCardModel(makeItem(index)))}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.queryByRole('navigation', { name: '信息流进度' })).not.toBeInTheDocument()
    const scroll = screen.getByTestId('workbench-feed-scroll')
    expect(scroll).toHaveAttribute('data-feed-visual', 'quiet-studio')
    expect(scroll.className).not.toContain('pr-10')
  })

  it('applies the same Quiet Studio card hierarchy to collection cards', () => {
    const card = toWorkbenchCardModel(makeItem(1))
    const view = render(<VirtualFeed
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
      cards={[card]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByRole('article', { name: '信息 1' })).toHaveAttribute('data-card-visual', 'quiet-studio')
    expect(screen.getByTestId('card-details-item-1')).toHaveAttribute('data-state', 'collapsed')
  })

  it('renders a social post as one source-first content block in both collapsed and expanded states', () => {
    const card = toWorkbenchCardModel(socialItem())
    const baseProps = {
      cards: [card],
      contextIds: [] as string[],
      onToggleExpanded: vi.fn(),
      onToggleSaved: vi.fn(),
      onToggleContext: vi.fn(),
      onItemAction: vi.fn(),
    }
    const view = render(<VirtualFeed {...baseProps} />)

    const metadata = screen.getByLabelText('来源信息')
    expect(within(metadata).getAllByText('X').length).toBeGreaterThan(0)
    expect(within(metadata).getByText('Tibo')).toBeInTheDocument()
    expect(within(metadata).getByText('@thsottiaux')).toBeInTheDocument()
    expect(screen.queryByText(socialItem().title)).not.toBeInTheDocument()
    expect(screen.getAllByText('Oops... I did it again. Enjoy reset usage limits for all paid users.')).toHaveLength(1)

    view.rerender(<VirtualFeed {...baseProps} expandedId="social-x" />)
    expect(screen.queryByText('Oops... I did it again. Enjoy reset usage limits for all paid users.')).not.toBeInTheDocument()
    expect(screen.getAllByText('Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.')).toHaveLength(1)
  })

  it('animates Quiet Studio details and exposes a confirmation state for Agent context', () => {
    render(<VirtualFeed
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

  it('keeps Quiet Studio card actions compact for fine pointers and 44px for coarse pointers at every width', () => {
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const card = screen.getByRole('article', { name: '信息 1' })
    const actions = [
      within(card).getByRole('link', { name: '打开 信息 1 原文' }),
      within(card).getByRole('button', { name: '收藏 信息 1' }),
      within(card).getByRole('button', { name: '将 信息 1 加入 Agent 上下文' }),
      within(card).getByRole('button', { name: '更多操作 信息 1' }),
    ]

    for (const action of actions) {
      expect(action).toHaveClass('size-8')
      expect(action).toHaveClass('pointer-coarse:size-11')
      expect(action.className).not.toContain('min-[768px]:size-8')
    }
  })

  it('only softens Quiet Studio card actions when the primary pointer is fine', () => {
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const actions = screen.getByRole('article', { name: '信息 1' }).querySelector<HTMLElement>('[data-card-actions]')
    if (!actions) throw new Error('Quiet Studio card actions were not rendered')

    expect(actions).toHaveClass(
      'opacity-100',
      'pointer-fine:opacity-60',
      'pointer-fine:group-hover/card:opacity-100',
      'pointer-fine:group-focus-within/card:opacity-100',
    )
    expect(actions.className).not.toContain('min-[768px]:opacity-60')
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

  it('treats the top as the fresh edge for newest-first Feed order', async () => {
    const initial = [1, 0].map((index) => toWorkbenchCardModel(makeItem(index)))
    const view = render(<VirtualFeed
      freshEdge="start"
      cards={initial}
      sourceItemIds={['item-1', 'item-0']}
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
      scrollTop: { configurable: true, writable: true, value: 240 },
    })
    fireEvent.scroll(scroll)

    view.rerender(<VirtualFeed
      freshEdge="start"
      cards={[toWorkbenchCardModel(makeItem(2)), ...initial]}
      sourceItemIds={['item-2', 'item-1', 'item-0']}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(await screen.findByRole('button', { name: '查看 1 条新内容' })).toHaveClass('top-4')
    scroll.scrollTop = 0
    fireEvent.scroll(scroll)
    expect(screen.queryByRole('button', { name: '查看 1 条新内容' })).not.toBeInTheDocument()
  })
})
