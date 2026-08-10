import { act, render, screen } from '@testing-library/react'
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
  it('starts source sections collapsed and exposes one compact source feed at a time', async () => {
    const browser = userEvent.setup()
    const sections = buildSourceOverviewSections([
      card('a-old', 'source-a', '来源 A', '2026-08-01T00:00:00Z', ['AI', '产品']),
      card('b-new', 'source-b', '来源 B', '2026-08-03T00:00:00Z', ['工程']),
      card('a-new', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI']),
    ])

    const onToggleSource = vi.fn()
    const { rerender } = render(<SourceOverviewFeed
      sections={sections}
      contextIds={[]}
      onToggleSource={onToggleSource}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)

    const sourceB = await screen.findByRole('button', { name: '展开专题 来源 B' })
    expect(sourceB).toHaveAttribute('aria-expanded', 'false')
    expect(sourceB).toHaveAttribute('aria-controls', 'source-section-content-source:source-b')
    expect(document.querySelectorAll('[data-source-group-card]')).toHaveLength(2)
    expect(sourceB.closest('[data-source-group-card]')).toHaveAttribute('data-state', 'collapsed')
    expect(screen.getByText('近7天 · 1 篇内容 · 1 个主题')).toBeInTheDocument()
    expect(screen.queryByRole('article', { name: '来源 B 的最新内容' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('source-insight')).not.toBeInTheDocument()
    expect(screen.queryByText('#工程')).not.toBeInTheDocument()

    await browser.click(sourceB)
    expect(onToggleSource).toHaveBeenCalledWith('source:source-b')
    rerender(<SourceOverviewFeed
      sections={sections}
      expandedSourceId="source:source-b"
      contextIds={[]}
      onToggleSource={onToggleSource}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
    />)
    const sourceArticle = screen.getByRole('article', { name: '标题 b-new' })
    expect(sourceArticle).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起专题 来源 B' }).closest('[data-source-group-card]')).toHaveAttribute('data-state', 'expanded')
    expect(sourceArticle.closest('[data-source-group-card]')).toBe(screen.getByRole('button', { name: '收起专题 来源 B' }).closest('[data-source-group-card]'))
    expect(sourceArticle.closest('[data-source-feed-row]')).toBeInTheDocument()
    expect(sourceArticle.closest('[data-timeline-item]')).toBeInTheDocument()
    expect(screen.getAllByTestId('workbench-card').every((element) => element.getAttribute('data-card-variant') === 'source-overview')).toBe(true)
  })

  it('keeps detail expansion while removing per-article actions and tags from compact rows', async () => {
    const browser = userEvent.setup()
    const story = card('a-detail', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI'])
    const onToggleExpanded = vi.fn()
    const onToggleSaved = vi.fn()
    const onToggleContext = vi.fn()
    const onItemAction = vi.fn()

    render(<SourceOverviewFeed
      sections={buildSourceOverviewSections([story])}
      expandedSourceId="source:source-a"
      expandedId={undefined}
      contextIds={[]}
      onToggleSource={vi.fn()}
      onToggleExpanded={onToggleExpanded}
      onToggleSaved={onToggleSaved}
      onToggleContext={onToggleContext}
      onItemAction={onItemAction}
    />)

    await browser.click(await screen.findByRole('button', { name: '打开详情 标题 a-detail' }))
    expect(onToggleExpanded).toHaveBeenCalledWith('a-detail')
    expect(screen.queryByRole('button', { name: '收藏 标题 a-detail' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '将 标题 a-detail 加入 Agent 上下文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /原文/u })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /更多操作/u })).not.toBeInTheDocument()
    expect(screen.queryByText('#AI')).not.toBeInTheDocument()
    expect(onToggleSaved).not.toHaveBeenCalled()
    expect(onToggleContext).not.toHaveBeenCalled()
    expect(onItemAction).not.toHaveBeenCalled()
  })

  it('keeps source AI and Agent actions separate from the accordion trigger', async () => {
    const browser = userEvent.setup()
    const section = buildSourceOverviewSections([card('a-ai', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI'])])[0]
    const onRequestSummary = vi.fn()
    const onAskAgent = vi.fn()
    const onToggleSource = vi.fn()
    const { rerender } = render(<SourceOverviewFeed
      sections={[section]}
      contextIds={[]}
      onToggleSource={onToggleSource}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
      onRequestSummary={onRequestSummary}
      onAskAgent={onAskAgent}
    />)

    await browser.click(screen.getByRole('button', { name: '总结专题 来源 A' }))
    expect(onRequestSummary).toHaveBeenCalledWith(section, false)
    expect(onToggleSource).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '针对专题 来源 A 问 Agent' }))
    expect(onAskAgent).toHaveBeenCalledWith(section)
    expect(onToggleSource).not.toHaveBeenCalled()

    onRequestSummary.mockClear()
    rerender(<SourceOverviewFeed
      sections={[section]}
      contextIds={[]}
      summaryStates={{
        [section.id]: {
          fingerprint: section.contentFingerprint,
          status: 'success',
          data: { schema_version: 1, overview: '缓存概览', highlights: ['[1] 缓存要点'], item_count: 1 },
        },
      }}
      onToggleSource={onToggleSource}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
      onRequestSummary={onRequestSummary}
      onAskAgent={onAskAgent}
    />)
    const viewSummary = screen.getByRole('button', { name: '查看总结专题 来源 A' })
    expect(viewSummary).toHaveTextContent('查看总结')
    await browser.click(viewSummary)
    expect(onToggleSource).toHaveBeenLastCalledWith(section.id)
    expect(onRequestSummary).not.toHaveBeenCalled()

    rerender(<SourceOverviewFeed
      sections={[section]}
      expandedSourceId={section.id}
      contextIds={[]}
      summaryStates={{
        [section.id]: {
          fingerprint: section.contentFingerprint,
          status: 'success',
          data: { schema_version: 1, overview: '缓存概览', highlights: ['[1] 缓存要点'], item_count: 1 },
        },
      }}
      onToggleSource={onToggleSource}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
      onRequestSummary={onRequestSummary}
      onAskAgent={onAskAgent}
    />)
    const regenerateSummary = screen.getByRole('button', { name: '重新总结专题 来源 A' })
    expect(regenerateSummary).toHaveTextContent('重新总结')
    await browser.click(regenerateSummary)
    expect(onRequestSummary).toHaveBeenLastCalledWith(section, true)

    rerender(<SourceOverviewFeed
      sections={[section]}
      contextIds={[]}
      canSummarize={false}
      onToggleSource={onToggleSource}
      onToggleExpanded={vi.fn()}
      onToggleSaved={vi.fn()}
      onToggleContext={vi.fn()}
      onItemAction={vi.fn()}
      onRequestSummary={onRequestSummary}
      onAskAgent={onAskAgent}
    />)
    expect(screen.getByRole('button', { name: '总结专题 来源 A' })).toBeDisabled()
  })

  it('renders source summary success, loading, failure, and retry inside the same group card', async () => {
    const browser = userEvent.setup()
    const section = buildSourceOverviewSections([card('a-summary', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI'])])[0]
    const onRequestSummary = vi.fn()
    const baseProps = {
      sections: [section],
      expandedSourceId: section.id,
      contextIds: [],
      onToggleSource: vi.fn(),
      onToggleExpanded: vi.fn(),
      onToggleSaved: vi.fn(),
      onToggleContext: vi.fn(),
      onItemAction: vi.fn(),
      onRequestSummary,
    }
    const { rerender } = render(<SourceOverviewFeed {...baseProps} summaryStates={{
      [section.id]: { fingerprint: section.contentFingerprint, status: 'loading' },
    }} />)
    expect(screen.getByRole('status')).toHaveTextContent('正在总结当前专题')
    expect(screen.getByRole('button', { name: '总结专题 来源 A' })).toBeDisabled()

    rerender(<SourceOverviewFeed {...baseProps} summaryStates={{
      [section.id]: { fingerprint: section.contentFingerprint, status: 'error', message: '生成暂时失败' },
    }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('生成暂时失败')
    await browser.click(screen.getByRole('button', { name: '重试' }))
    expect(onRequestSummary).toHaveBeenLastCalledWith(section, true)

    rerender(<SourceOverviewFeed {...baseProps} summaryStates={{
      [section.id]: {
        fingerprint: section.contentFingerprint,
        status: 'success',
        data: { schema_version: 1, overview: '近期更新集中在产品发布。', highlights: ['发布新版', '补充安全说明'], item_count: 1 },
      },
    }} />)
    expect(screen.getByText('近期更新集中在产品发布。')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '专题总结关键要点' })).toHaveTextContent('发布新版')
    await browser.click(screen.getByRole('button', { name: '重新总结' }))
    expect(onRequestSummary).toHaveBeenLastCalledWith(section, true)
  })

  it('keeps SourceInsight absent until a summary state is provided', () => {
    const { container, rerender } = render(<SourceInsight />)
    expect(container.querySelector('[data-source-insight]')).not.toBeInTheDocument()
    rerender(<SourceInsight state={{
      fingerprint: 'one',
      status: 'success',
      data: { schema_version: 1, overview: '未来洞察', highlights: ['关键要点'], item_count: 1 },
    }} />)
    expect(container.querySelector('[data-source-insight]')).toHaveTextContent('未来洞察')
  })

  it('keeps the terminal copy stable while its visible text rerenders', () => {
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
    const sections = buildSourceOverviewSections([card('a-terminal', 'source-a', '来源 A', '2026-08-02T00:00:00Z', ['AI'])])

    try {
      const { rerender } = render(<SourceOverviewFeed
        sections={sections}
        contextIds={[]}
        terminal={<p>第一句</p>}
        terminalKey="feed"
        onTerminalReach={onTerminalReach}
        onToggleSource={vi.fn()}
        onToggleExpanded={vi.fn()}
        onToggleSaved={vi.fn()}
        onToggleContext={vi.fn()}
        onItemAction={vi.fn()}
      />)

      act(() => emitVisibility?.(true))
      rerender(<SourceOverviewFeed
        sections={sections}
        contextIds={[]}
        terminal={<p>第二句</p>}
        terminalKey="feed"
        onTerminalReach={onTerminalReach}
        onToggleSource={vi.fn()}
        onToggleExpanded={vi.fn()}
        onToggleSaved={vi.fn()}
        onToggleContext={vi.fn()}
        onItemAction={vi.fn()}
      />)
      act(() => emitVisibility?.(true))
      expect(onTerminalReach).toHaveBeenCalledTimes(1)

      act(() => emitVisibility?.(false))
      act(() => emitVisibility?.(true))
      expect(onTerminalReach).toHaveBeenCalledTimes(2)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
