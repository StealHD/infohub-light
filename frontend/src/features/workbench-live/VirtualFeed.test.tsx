import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

function galleryItem(): FeedItem {
  const item = socialItem()
  if (!item.presentation) throw new Error('presentation fixture missing')
  item.presentation.content.format = 'gallery'
  item.presentation.content.format_origin = 'upstream'
  item.presentation.content.body_completeness = 'excerpt_only'
  item.presentation.media = {
    images: [
      { asset_id: 'one', url: '/api/media/one', alt: '图片一' },
      { asset_id: 'two', url: '/api/media/two', alt: '图片二' },
    ],
    count: 2,
    total_image_count: 8,
    truncated: true,
  }
  return item
}

function singleImageItem(): FeedItem {
  const item = galleryItem()
  if (!item.presentation?.media) throw new Error('media fixture missing')
  item.presentation.media = {
    images: item.presentation.media.images.slice(0, 1),
    count: 1,
    total_image_count: 1,
    truncated: false,
  }
  return item
}

function twoImageItem(): FeedItem {
  const item = galleryItem()
  if (!item.presentation?.media) throw new Error('media fixture missing')
  item.presentation.media = {
    ...item.presentation.media,
    total_image_count: 2,
    truncated: false,
  }
  return item
}

function truncatedSingleImageItem(): FeedItem {
  const item = galleryItem()
  if (!item.presentation?.media) throw new Error('media fixture missing')
  item.presentation.media = {
    images: item.presentation.media.images.slice(0, 1),
    count: 1,
    total_image_count: 8,
    truncated: true,
  }
  return item
}

describe('VirtualFeed', () => {
  it('fires the terminal sentinel only on visible entry and again after leaving', () => {
    let emitVisibility: ((visible: boolean) => void) | undefined
    class TestIntersectionObserver {
      constructor(callback: IntersectionObserverCallback) {
        emitVisibility = (visible) => callback(
          [{ isIntersecting: visible } as IntersectionObserverEntry],
          this as unknown as IntersectionObserver,
        )
      }
      observe() {}
      disconnect() {}
      unobserve() {}
      takeRecords() { return [] }
      root = null
      rootMargin = '0px'
      thresholds = [0.01]
    }
    vi.stubGlobal('IntersectionObserver', TestIntersectionObserver)
    const onTerminalReach = vi.fn()

    try {
      render(<VirtualFeed
        cards={[toWorkbenchCardModel(makeItem(1))]}
        terminal={<p>当前信息流已全部显示</p>}
        terminalKey="feed"
        contextIds={[]}
        onToggleExpanded={vi.fn()}
        onToggleSaved={vi.fn()}
        onToggleContext={vi.fn()}
        onItemAction={vi.fn()}
        onTerminalReach={onTerminalReach}
      />)

      expect(screen.getByTestId('feed-end-sentinel')).toHaveTextContent('当前信息流已全部显示')
      act(() => emitVisibility?.(true))
      act(() => emitVisibility?.(true))
      expect(onTerminalReach).toHaveBeenCalledTimes(1)

      act(() => emitVisibility?.(false))
      act(() => emitVisibility?.(true))
      expect(onTerminalReach).toHaveBeenCalledTimes(2)
    } finally {
      vi.unstubAllGlobals()
    }
  })

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

  it('uses the measured floating-toolbar inset instead of a fixed top padding', () => {
    render(<VirtualFeed
      topInset={94}
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const scroll = screen.getByTestId('workbench-feed-scroll')
    expect(scroll).toHaveAttribute('data-top-inset', '94')
    expect(scroll).toHaveStyle({ paddingTop: '94px' })
    expect(scroll.className).not.toContain('pt-16')
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
    expect(screen.getByTestId('card-details-item-1')).toHaveAttribute('inert')

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

  it('keeps the Agent context action neutral until selected and uses the same sparkle icon', () => {
    const view = render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      expandedId="item-1"
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const details = screen.getByTestId('card-details-item-1')
    expect(details).toHaveAttribute('data-state', 'expanded')
    expect(details).not.toHaveAttribute('inert')
    expect(details.className).toContain('grid-rows-[1fr]')
    const idleButton = screen.getByRole('button', { name: '将 信息 1 加入 Agent 上下文' })
    expect(idleButton).toHaveAttribute('data-context-state', 'idle')
    expect(idleButton).toHaveAttribute('aria-pressed', 'false')
    expect(idleButton).toHaveClass('bg-transparent', 'text-muted')
    expect(idleButton).not.toHaveClass('bg-accent/15', 'text-accent')

    view.rerender(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      expandedId="item-1"
      contextIds={['item-1']}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const contextButton = screen.getByRole('button', { name: '将 信息 1 移出 Agent 上下文' })
    expect(contextButton).toHaveAttribute('data-context-state', 'selected')
    expect(contextButton).toHaveAttribute('aria-pressed', 'true')
    expect(contextButton).toHaveClass('data-[context-state=selected]:bg-accent/15', 'data-[context-state=selected]:text-accent')
    expect(contextButton.querySelector('.lucide-sparkles')).not.toBeNull()
    expect(contextButton.querySelector('.lucide-check')).toBeNull()
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
    const compactActions = [
      within(card).getByRole('link', { name: '打开 信息 1 原文' }),
      within(card).getByRole('button', { name: '收藏 信息 1' }),
      within(card).getByRole('button', { name: '更多操作 信息 1' }),
    ]

    for (const action of compactActions) {
      expect(action).toHaveClass('size-8')
      expect(action).toHaveClass('pointer-coarse:size-11')
      expect(action.className).not.toContain('min-[768px]:size-8')
    }
    const agentAction = within(card).getByRole('button', { name: '将 信息 1 加入 Agent 上下文' })
    expect(agentAction).toHaveClass('min-h-8', 'pointer-coarse:min-h-11')
    expect(agentAction).toHaveTextContent('问 Agent')
  })

  it('uses the sidebar star icon and fills it only for saved content', () => {
    const unsaved = toWorkbenchCardModel(makeItem(1))
    const saved = toWorkbenchCardModel({
      ...makeItem(2),
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    })
    render(<VirtualFeed
      cards={[unsaved, saved]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const unsavedIcon = screen.getByRole('button', { name: '收藏 信息 1' }).querySelector('.lucide-star')
    const savedIcon = screen.getByRole('button', { name: '取消收藏 信息 2' }).querySelector('.lucide-star')
    expect(unsavedIcon).toHaveAttribute('fill', 'none')
    expect(savedIcon).toHaveAttribute('fill', 'currentColor')
  })

  it('does not nest interactive card actions inside tooltip trigger controls', () => {
    const view = render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const nestedTriggers = Array.from(view.container.querySelectorAll('[data-slot="tooltip-trigger"]'))
      .filter((trigger) => trigger.querySelector('a[href], button, summary'))

    expect(nestedTriggers).toHaveLength(0)
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
      cards={[toWorkbenchCardModel(socialItem())]}
      contextIds={[]}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={onItemAction}
    />)

    await user.click(await screen.findByRole('button', { name: /^展开 / }))
    expect(onToggleExpanded).toHaveBeenCalledWith('social-x')
    expect(onItemAction).not.toHaveBeenCalled()
  })

  it('uses an explicit expand control while footer metadata shares the pointer expansion target', async () => {
    const user = userEvent.setup()
    const onToggleExpanded = vi.fn()
    const onToggleSaved = vi.fn()
    const onToggleContext = vi.fn()
    const view = render(<VirtualFeed
      cards={[toWorkbenchCardModel(socialItem())]}
      contextIds={[]}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={onToggleSaved}
      onToggleContext={onToggleContext}
      onItemAction={vi.fn()}
    />)

    const card = screen.getByRole('article')
    const expandZone = within(card).getByLabelText('内容分类、频道和主题')
    const expandButton = within(card).getByRole('button', { name: /^展开 / })
    const actions = card.querySelector<HTMLElement>('[data-card-actions]')
    if (!actions) throw new Error('card actions were not rendered')

    expect(expandButton).toHaveTextContent('')
    expect(expandButton.querySelector('.lucide-unfold-vertical')).not.toBeNull()
    expect(expandButton).toHaveAttribute('aria-controls', 'card-details-social-x')
    expect(expandButton).toHaveAttribute('aria-expanded', 'false')
    expect(expandZone).not.toContainElement(expandButton)
    expect(expandZone).not.toContainElement(actions)

    await user.click(expandZone)
    expect(onToggleExpanded).toHaveBeenCalledTimes(1)
    await user.click(expandButton)
    expect(onToggleExpanded).toHaveBeenCalledTimes(2)

    await user.click(within(actions).getByRole('button', { name: /^收藏 / }))
    await user.click(within(actions).getByRole('button', { name: /^将 .* 加入 Agent 上下文$/ }))
    await user.click(within(actions).getByRole('button', { name: /^更多操作 / }))
    expect(onToggleSaved).toHaveBeenCalledTimes(1)
    expect(onToggleContext).toHaveBeenCalledTimes(1)
    expect(onToggleExpanded).toHaveBeenCalledTimes(2)
    await user.keyboard('{Escape}')

    fireEvent.pointerEnter(expandButton, { pointerType: 'mouse' })
    expect(await screen.findByRole('tooltip')).toHaveTextContent('展开内容')

    view.rerender(<VirtualFeed
      cards={[toWorkbenchCardModel(socialItem())]}
      expandedId="social-x"
      contextIds={[]}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={onToggleSaved}
      onToggleContext={onToggleContext}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByRole('button', { name: /^收起 / }).querySelector('.lucide-fold-vertical')).not.toBeNull()
  })

  it('keeps only one card action menu open at a time', async () => {
    const user = userEvent.setup()
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1)), toWorkbenchCardModel(makeItem(2))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const firstTrigger = screen.getByRole('button', { name: '更多操作 信息 1' })
    const secondTrigger = screen.getByRole('button', { name: '更多操作 信息 2' })
    await user.click(firstTrigger)
    expect(screen.getByRole('dialog', { name: '信息 1 更多操作' })).toBeInTheDocument()

    secondTrigger.focus()
    fireEvent.click(secondTrigger)
    expect(screen.queryByRole('dialog', { name: '信息 1 更多操作' })).not.toBeInTheDocument()
    const secondDialog = screen.getByRole('dialog', { name: '信息 2 更多操作' })
    expect(secondDialog).toBeInTheDocument()

    secondDialog.focus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '信息 2 更多操作' })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '更多操作 信息 2' })).toHaveFocus())
  })

  it('does not render a fake expand control for fully visible short content', () => {
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.queryByRole('button', { name: /^展开 / })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^打开详情 / })).not.toBeInTheDocument()
  })

  it('reveals an expand control when the rendered text is actually line-clamped', async () => {
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const title = screen.getByText('信息 1')
    Object.defineProperties(title, {
      scrollHeight: { configurable: true, value: 80 },
      clientHeight: { configurable: true, value: 40 },
    })
    fireEvent(window, new Event('resize'))

    expect(await screen.findByRole('button', { name: '展开 信息 1' })).toBeInTheDocument()
  })

  it('shows one representative thumbnail with the cached and original image counts', () => {
    const item = galleryItem()
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(item)]}
      expandedId="social-x"
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.getByText('图集')).toBeInTheDocument()
    expect(screen.getByText('图片 2/8')).toBeInTheDocument()
    const preview = screen.getByLabelText('图片预览，共 2 张可查看图片')
    const trigger = within(preview).getByRole('button', { name: '打开图片预览，从第 1 张开始，可查看 2 张，共 8 张' })
    expect(trigger).toHaveClass('aspect-[4/3]', 'max-w-lg')
    expect(screen.queryByTestId('card-media-stack')).not.toBeInTheDocument()
    expect(preview.querySelectorAll('img')).toHaveLength(1)
    expect(within(preview).getByRole('img', { name: '图片一' })).toHaveClass('object-contain', 'size-full')
    expect(within(preview).queryByRole('img', { name: '图片二' })).not.toBeInTheDocument()
    expect(within(preview).getByText('可看 2 / 共 8')).toBeInTheDocument()
    expect(screen.getByText('仅获取到内容片段，打开原文查看完整内容。')).toBeInTheDocument()
  })

  it('shows one compact representative image with bounded decorative stack layers while collapsed', () => {
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(galleryItem())]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const stack = screen.getByTestId('card-media-stack')
    const details = screen.getByTestId('card-details-social-x')
    expect(stack).toHaveAttribute('data-stack-depth', '2')
    expect(stack).toHaveAccessibleName('打开图片预览，从第 1 张开始，可查看 2 张，共 8 张')
    expect(stack.querySelectorAll('[data-card-media-stack-layer]')).toHaveLength(2)
    expect(stack.querySelectorAll('img[src="/api/media/one"]')).toHaveLength(1)
    expect(stack.querySelector('img')).toHaveAttribute('alt', '')
    expect(stack.querySelector('img')).toHaveClass('object-contain', 'size-full')
    expect(details.querySelector('img')).not.toBeInTheDocument()
  })

  it('uses zero, one or two decorative layers for one, two or three-plus original images', () => {
    const view = render(<VirtualFeed
      cards={[toWorkbenchCardModel(singleImageItem())]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.getByTestId('card-media-stack')).toHaveAttribute('data-stack-depth', '0')
    expect(screen.getByTestId('card-media-stack').querySelectorAll('[data-card-media-stack-layer]')).toHaveLength(0)

    view.rerender(<VirtualFeed
      cards={[toWorkbenchCardModel(twoImageItem())]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByTestId('card-media-stack')).toHaveAttribute('data-stack-depth', '1')
    expect(screen.getByTestId('card-media-stack').querySelectorAll('[data-card-media-stack-layer]')).toHaveLength(1)

    view.rerender(<VirtualFeed
      cards={[toWorkbenchCardModel(galleryItem())]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByTestId('card-media-stack')).toHaveAttribute('data-stack-depth', '2')
    expect(screen.getByTestId('card-media-stack').querySelectorAll('[data-card-media-stack-layer]')).toHaveLength(2)
  })

  it('does not add a compact media layout or trigger to a card without viewable images', () => {
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const card = screen.getByRole('article', { name: '信息 1' })
    expect(card.querySelector('[data-card-media-layout]')).not.toBeInTheDocument()
    expect(screen.queryByTestId('card-media-stack')).not.toBeInTheDocument()
  })

  it('opens the shared preview directly from a collapsed stack, then restores focus and scroll', async () => {
    const user = userEvent.setup()
    const onToggleExpanded = vi.fn()
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(galleryItem())]}
      contextIds={[]}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const scroll = screen.getByTestId('workbench-feed-scroll')
    Object.defineProperty(scroll, 'scrollTop', { configurable: true, writable: true, value: 180 })
    const firstThumbnail = screen.getByRole('button', { name: '打开图片预览，从第 1 张开始，可查看 2 张，共 8 张' })
    const expandButton = screen.getByRole('button', { name: /打开详情/ })
    expect(expandButton).toHaveAttribute('aria-expanded', 'false')

    await user.click(firstThumbnail)
    expect(expandButton).toHaveAttribute('aria-expanded', 'false')
    const dialog = await screen.findByRole('dialog', { name: /图片预览$/ })
    const stage = within(dialog).getByTestId('media-viewer-stage')
    expect(stage).toHaveClass('min-h-0', 'overflow-hidden')
    expect(within(dialog).getByRole('img', { name: '图片一' })).toHaveClass('object-contain', 'size-full', 'min-h-0')
    expect(within(dialog).getByRole('status')).toHaveTextContent('1 / 2')

    await user.keyboard('{ArrowLeft}')
    expect(within(dialog).getByRole('img', { name: '图片二' })).toBeInTheDocument()
    expect(within(dialog).getByRole('status')).toHaveTextContent('2 / 2')
    await user.keyboard('{ArrowRight}')
    expect(within(dialog).getByRole('img', { name: '图片一' })).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '下一张图片' }))
    expect(within(dialog).getByRole('img', { name: '图片二' })).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: '关闭图片预览' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /图片预览$/ })).not.toBeInTheDocument())
    await waitFor(() => expect(firstThumbnail).toHaveFocus())
    expect(scroll.scrollTop).toBe(180)
    expect(onToggleExpanded).not.toHaveBeenCalled()
  })

  it('supports thumbnail navigation, touch swipe and a local broken-image retry', async () => {
    const user = userEvent.setup()
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(galleryItem())]}
      expandedId="social-x"
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    await user.click(screen.getByRole('button', { name: '打开图片预览，从第 1 张开始，可查看 2 张，共 8 张' }))
    const dialog = await screen.findByRole('dialog', { name: /图片预览$/ })
    const thumbnails = within(dialog).getByRole('group', { name: '图片缩略图' })
    expect(within(thumbnails).getByRole('button', { name: '切换到第 1 张图片' })).toHaveAttribute('aria-current', 'true')
    await user.click(within(thumbnails).getByRole('button', { name: '切换到第 2 张图片' }))
    expect(within(dialog).getByRole('img', { name: '图片二' })).toBeInTheDocument()

    const stage = within(dialog).getByTestId('media-viewer-stage')
    fireEvent.pointerDown(stage, { pointerType: 'touch', pointerId: 1, clientX: 220 })
    fireEvent.pointerUp(stage, { pointerType: 'touch', pointerId: 1, clientX: 120 })
    expect(within(dialog).getByRole('img', { name: '图片一' })).toBeInTheDocument()

    fireEvent.error(within(dialog).getByRole('img', { name: '图片一' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('图片加载失败')
    await user.click(within(dialog).getByRole('button', { name: '重试这张图片' }))
    expect(within(dialog).getByLabelText('正在加载图片')).toBeInTheDocument()
  })

  it('keeps a truncated original stack while hiding carousel-only controls for one viewable image', async () => {
    const user = userEvent.setup()
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(truncatedSingleImageItem())]}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(screen.getByText('图片 1/8')).toBeInTheDocument()
    expect(screen.getByTestId('card-media-stack')).toHaveAttribute('data-stack-depth', '2')
    await user.click(screen.getByRole('button', { name: '打开图片预览，从第 1 张开始，可查看 1 张，共 8 张' }))
    const dialog = await screen.findByRole('dialog', { name: /图片预览$/ })
    expect(within(dialog).getByRole('status')).toHaveTextContent('1 / 1')
    expect(within(dialog).queryByRole('button', { name: '上一张图片' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '下一张图片' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('group', { name: '图片缩略图' })).not.toBeInTheDocument()
  })

  it('dismisses the image preview with Escape and by clicking the backdrop', async () => {
    const user = userEvent.setup()
    const view = render(<VirtualFeed
      cards={[toWorkbenchCardModel(galleryItem())]}
      expandedId="social-x"
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const thumbnail = screen.getByRole('button', { name: '打开图片预览，从第 1 张开始，可查看 2 张，共 8 张' })

    await user.click(thumbnail)
    expect(await screen.findByRole('dialog', { name: /图片预览$/ })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /图片预览$/ })).not.toBeInTheDocument())
    await waitFor(() => expect(thumbnail).toHaveFocus())

    await user.click(thumbnail)
    expect(await screen.findByRole('dialog', { name: /图片预览$/ })).toBeInTheDocument()
    const backdrop = view.baseElement.querySelector<HTMLElement>('[data-slot="modal-backdrop"]')
    if (!backdrop) throw new Error('modal backdrop was not rendered')
    await user.click(backdrop)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /图片预览$/ })).not.toBeInTheDocument())
    await waitFor(() => expect(thumbnail).toHaveFocus())
  })

  it('keeps detail loading and failure local to the expanded card', () => {
    const card = toWorkbenchCardModel(socialItem())
    const view = render(<VirtualFeed
      cards={[card]}
      expandedId="social-x"
      detailLoading
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByRole('status', { name: '正在读取详情' })).toBeInTheDocument()

    view.rerender(<VirtualFeed
      cards={[card]}
      expandedId="social-x"
      detailError
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    expect(screen.getByText('暂时无法读取更多内容；当前卡片仍可继续使用。')).toBeInTheDocument()
  })

  it('keeps viewer mutations disabled while open and copy remain available', async () => {
    const user = userEvent.setup()
    const copy = vi.fn().mockResolvedValue(undefined)
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
    expect(within(card).queryByRole('button', { name: /标记.*读/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '忽略' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '复制摘要' }))
    expect(copy).toHaveBeenCalledWith('这是第 1 条摘要')
    expect(await within(card).findByRole('status')).toHaveTextContent('摘要已复制')
  })

  it.each([
    ['clipboard permission is rejected', { writeText: vi.fn().mockRejectedValue(new Error('denied')) }],
    ['Clipboard API is unavailable', undefined],
  ])('shows a recoverable copy failure when %s', async (_name, clipboard) => {
    const user = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: clipboard })
    render(<VirtualFeed
      cards={[toWorkbenchCardModel(makeItem(1))]}
      expandedId="item-1"
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const card = await screen.findByRole('article', { name: '信息 1' })
    await user.click(within(card).getByRole('button', { name: '更多操作 信息 1' }))
    await user.click(screen.getByRole('button', { name: '复制摘要' }))

    expect(await within(card).findByRole('status')).toHaveTextContent('复制失败，请手动复制')
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

    const newContent = await screen.findByRole('button', { name: '查看 1 条新内容' })
    expect(newContent).not.toHaveClass('top-4')
    expect(newContent).toHaveStyle({ top: '80px' })
    scroll.scrollTop = 0
    fireEvent.scroll(scroll)
    expect(screen.queryByRole('button', { name: '查看 1 条新内容' })).not.toBeInTheDocument()
  })

  it('resets to the top when the sort definition changes in either direction', async () => {
    const ascending = Array.from({ length: 12 }, (_, index) => toWorkbenchCardModel(makeItem(index)))
    const view = render(<VirtualFeed
      freshEdge="start"
      resetToTopKey="published:newest"
      cards={[...ascending].reverse()}
      sourceItemIds={ascending.map((card) => card.id)}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const scroll = screen.getByTestId('workbench-feed-scroll')
    Object.defineProperties(scroll, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 720 },
      scrollTop: { configurable: true, writable: true, value: 360 },
    })
    fireEvent.scroll(scroll)
    view.rerender(<VirtualFeed
      freshEdge="end"
      resetToTopKey="published:oldest"
      cards={ascending}
      sourceItemIds={ascending.map((card) => card.id)}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    await waitFor(() => expect(scroll.scrollTop).toBe(0))
    // A mobile virtualizer can apply one late measurement correction after the
    // first reset frame; the reset remains authoritative until geometry settles.
    scroll.scrollTop = 456
    await waitFor(() => expect(scroll.scrollTop).toBe(0))

    scroll.scrollTop = 840
    fireEvent.scroll(scroll)
    view.rerender(<VirtualFeed
      freshEdge="start"
      resetToTopKey="ingested:newest"
      cards={[...ascending].reverse()}
      sourceItemIds={ascending.map((card) => card.id)}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    await waitFor(() => expect(scroll.scrollTop).toBe(0))
  })

  it('starts an oldest-first Feed at the top unless it has a navigation target', async () => {
    const cards = Array.from({ length: 12 }, (_, index) => toWorkbenchCardModel(makeItem(index)))
    render(<VirtualFeed
      freshEdge="end"
      cards={cards}
      sourceItemIds={cards.map((card) => card.id)}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const scroll = screen.getByTestId('workbench-feed-scroll')
    Object.defineProperties(scroll, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 720 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    })
    await waitFor(() => expect(scroll.scrollTop).toBe(0))
  })
})
