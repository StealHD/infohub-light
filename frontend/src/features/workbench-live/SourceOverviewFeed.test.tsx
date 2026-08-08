import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { FeedItem } from '../../api/types'
import { toWorkbenchCardModel } from './workbenchModel'
import { SourceInsight, SourceOverviewFeed } from './SourceOverviewFeed'
import { buildSourceOverviewSections } from './sourceOverviewModel'

function card(id: string, sourceId: string, sourceName: string, publishedAt: string, topics: string[]) {
  const item: FeedItem = {
    id,
    title: `标题 ${id}`,
    summary_zh: `摘要 ${id}`,
    url: `https://example.com/${id}`,
    source: sourceName,
    source_id: sourceId,
    published_at: publishedAt,
    topics,
    user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
    presentation: {
      version: 2,
      source: { id: sourceId, catalog_type: 'rss', platform: 'rss', name: sourceName },
      author: { name: sourceName, kind: 'organization' },
      timing: { published_at: publishedAt, fetched_at: publishedAt },
      links: { canonical_url: `https://example.com/${id}`, source_url: `https://example.com/${id}` },
      content: { title: `标题 ${id}`, title_origin: 'native', excerpt: `摘要 ${id}`, body_text: `详情 ${id}`, content_kind: 'feed_summary', excerpt_truncated: false, body_truncated: false },
      taxonomy: { channel: 'AI', configured_topics: [], inferred_topics: topics, topics, entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'disabled', score: 0, signal_strength: 'unknown', signal_type: 'unknown', summary_zh: `摘要 ${id}` },
    },
  }
  return toWorkbenchCardModel(item)
}

describe('SourceOverviewFeed', () => {
  it('renders contiguous compact source sections without an empty insight placeholder', async () => {
    const sections = buildSourceOverviewSections([
      card('a-old', 'source-a', '来源 A', '2026-08-01T00:00:00Z', ['AI', '产品']),
      card('b-new', 'source-b', '来源 B', '2026-08-03T00:00:00Z', ['工程']),
      card('a-new', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI']),
    ])

    render(<SourceOverviewFeed
      sections={sections}
      contextIds={[]}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    expect(await screen.findByText('来源 B', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getByText('近7天 · 1 篇内容 · 1 个主题')).toBeInTheDocument()
    expect(screen.getAllByTestId('workbench-card').every((element) => element.getAttribute('data-card-variant') === 'source-overview')).toBe(true)
    expect(screen.queryByTestId('source-insight')).not.toBeInTheDocument()
    expect(screen.getAllByText('#工程')).toHaveLength(2)
  })

  it('keeps the existing article actions and detail callbacks available in compact rows', async () => {
    const browser = userEvent.setup()
    const story = card('a-detail', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI'])
    const onToggleExpanded = vi.fn()
    const onToggleSaved = vi.fn()
    const onToggleContext = vi.fn()
    const onItemAction = vi.fn()

    render(<SourceOverviewFeed
      sections={buildSourceOverviewSections([story])}
      expandedId={undefined}
      contextIds={[]}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={onToggleSaved}
      onToggleContext={onToggleContext}
      onItemAction={onItemAction}
    />)

    await browser.click(await screen.findByRole('button', { name: '展开 标题 a-detail' }))
    expect(onToggleExpanded).toHaveBeenCalledWith('a-detail')
    await browser.click(screen.getByRole('button', { name: '收藏 标题 a-detail' }))
    expect(onToggleSaved).toHaveBeenCalledWith('a-detail', true)
    await browser.click(screen.getByRole('button', { name: '将 标题 a-detail 加入 Agent 上下文' }))
    expect(onToggleContext).toHaveBeenCalledWith(story)
    expect(onItemAction).not.toHaveBeenCalled()
  })

  it('keeps SourceInsight optional for future content', () => {
    const { container } = render(<SourceInsight><p>未来洞察</p></SourceInsight>)
    expect(container.querySelector('[data-source-insight]')).toHaveTextContent('未来洞察')
  })
})
