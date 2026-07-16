import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { FeedItem } from '../../api/types'
import { FeedWorkspace } from './FeedWorkspace'

const items: FeedItem[] = [
  {
    id: 'article-1', title: 'Codex 推出新的协作工作流', url: 'https://openai.com/codex',
    source: 'OpenAI Blog', summary_zh: '更清晰的任务分解与上下文协作。',
    action_suggestion: '关注任务交接和状态追踪。', score: 9.2, channel: 'AI', signal_type: '产品更新', topics: ['Codex'],
    published_at: '2026-07-13T08:00:00Z', subscription_ids: ['sub-a'],
    presentation: {
      version: 1,
      source: { id: 'source-a', catalog_type: 'rss', platform: 'rss', name: 'OpenAI Blog' },
      author: { name: 'OpenAI', kind: 'organization' },
      timing: { published_at: '2026-07-13T08:00:00Z', fetched_at: '2026-07-13T08:05:00Z' },
      links: { canonical_url: 'https://openai.com/codex', source_url: 'https://openai.com/news/codex' },
      content: { title: 'Codex 推出新的协作工作流', title_origin: 'native', excerpt: 'OpenAI 发布了 Codex 协作工作流的原始说明。', content_kind: 'feed_summary', excerpt_truncated: false },
      taxonomy: { channel: 'AI', configured_topics: ['Codex'], inferred_topics: [], topics: ['Codex'], entities: ['OpenAI'] },
      engagement: { native_score: null, likes: 12, comments: 3, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'ai', score: 9.2, signal_strength: 'strong', signal_type: 'release', summary_zh: '更清晰的任务分解与上下文协作。', action_suggestion: '关注任务交接和状态追踪。' },
    },
    user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
  },
]

describe('FeedWorkspace', () => {
  it('opens a story without changing its read state', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const onStateAction = vi.fn()
    const view = render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={items}
        onSelect={onSelect}
        onStateAction={onStateAction}
        sourceHealth={[]}
      />,
    )

    expect(onStateAction).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('feed-story'))
    expect(onSelect).toHaveBeenCalledWith('article-1')
    expect(onStateAction).not.toHaveBeenCalled()

    view.rerender(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={[{ ...items[0], user_state: { ...items[0].user_state!, is_read: true } }]}
        onSelect={onSelect}
        onStateAction={onStateAction}
        sourceHealth={[]}
      />,
    )
    await user.click(screen.getByTestId('feed-story'))
    expect(onStateAction).not.toHaveBeenCalled()
  })

  it('does not auto-mark stories read for a viewer', async () => {
    const user = userEvent.setup()
    const onStateAction = vi.fn()
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={items}
        onSelect={vi.fn()}
        onStateAction={onStateAction}
        sourceHealth={[]}
        readonly
      />,
    )

    await user.click(screen.getByTestId('feed-story'))
    expect(onStateAction).not.toHaveBeenCalled()
  })

  it('shows a closable error when an optimistic item-state update rolls back', async () => {
    const user = userEvent.setup()
    const onDismissActionError = vi.fn()
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={items}
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
        actionError="标记已读失败，状态已恢复。"
        onDismissActionError={onDismissActionError}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('标记已读失败，状态已恢复。')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onDismissActionError).toHaveBeenCalledOnce()
  })

  it('renders one concise decision brief and keeps secondary actions in the more menu', async () => {
    const user = userEvent.setup()
    const onStateAction = vi.fn()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn() } })
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条高价值信号"
        items={items}
        selectedId="article-1"
        onSelect={vi.fn()}
        onStateAction={onStateAction}
        sourceHealth={[{ subscription_id: 'sub-a', source_id: 'source-a', status: 'healthy', consecutive_failures: 0 }]}
      />,
    )

    expect(screen.getAllByText('Codex 推出新的协作工作流')).toHaveLength(2)
    const reader = within(screen.getByRole('region', { name: '阅读详情' }))
    expect(reader.getByLabelText('文章内容')).toHaveAttribute('tabindex', '0')
    expect(reader.getAllByText('更清晰的任务分解与上下文协作。')).toHaveLength(1)
    expect(reader.queryByRole('heading', { name: 'AI 概括' })).not.toBeInTheDocument()
    expect(reader.queryByRole('heading', { name: '为什么值得关注' })).not.toBeInTheDocument()
    expect(reader.queryByRole('heading', { name: '来源摘录' })).not.toBeInTheDocument()
    expect(reader.getByText('OpenAI 发布了 Codex 协作工作流的原始说明。')).toBeInTheDocument()
    expect(reader.getByText(/OpenAI ·/)).toBeInTheDocument()
    expect(reader.getByText('点赞 12')).toBeInTheDocument()
    expect(reader.queryByRole('heading', { name: '建议动作' })).not.toBeInTheDocument()
    expect(reader.queryByText('关注任务交接和状态追踪。')).not.toBeInTheDocument()
    expect(reader.getByText('9.2 强信号')).toBeInTheDocument()
    expect(reader.getByText('AI')).toBeInTheDocument()
    expect(reader.getByText('release')).toBeInTheDocument()
    expect(reader.getByText('来源健康：正常')).toBeInTheDocument()
    expect(reader.getByRole('link', { name: '打开原文' })).toHaveAttribute('href', 'https://openai.com/codex')
    expect(reader.getByRole('link', { name: '查看原帖' })).toHaveAttribute('href', 'https://openai.com/news/codex')

    await user.click(reader.getByRole('button', { name: '稍后读' }))
    expect(onStateAction).toHaveBeenCalledWith('article-1', 'is_later', true)
    await user.click(reader.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: '标记已读' }))
    expect(onStateAction).toHaveBeenCalledWith('article-1', 'is_read', true)
  })

  it('allows an explicitly read item to be marked unread', async () => {
    const user = userEvent.setup()
    const onStateAction = vi.fn()
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={[{ ...items[0], user_state: { ...items[0].user_state!, is_read: true } }]}
        selectedId="article-1"
        onSelect={vi.fn()}
        onStateAction={onStateAction}
        sourceHealth={[]}
      />,
    )

    await user.click(screen.getByRole('button', { name: '更多操作' }))
    await user.click(screen.getByRole('menuitem', { name: '标记未读' }))
    expect(onStateAction).toHaveBeenCalledWith('article-1', 'is_read', false)
  })

  it('renders the cached source avatar, list thumbnail and detail gallery', () => {
    const mediaItem: FeedItem = {
      ...items[0],
      image_url: '/api/media/med_first',
      presentation: {
        ...items[0].presentation!,
        version: 2,
        source: { ...items[0].presentation!.source, avatar_url: '/api/media/med_avatar' },
        content: {
          ...items[0].presentation!.content,
          body_text: '完整抓取正文',
          body_truncated: false,
          body_completeness: 'captured',
        },
        media: {
          images: [
            { asset_id: 'med_first', url: '/api/media/med_first', alt: '第一张' },
            { asset_id: 'med_second', url: '/api/media/med_second', alt: '第二张' },
          ],
          count: 2,
        },
      },
    }
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={[mediaItem]}
        selectedId="article-1"
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
      />,
    )

    expect(screen.getAllByRole('img', { name: 'OpenAI Blog' }).length).toBeGreaterThan(0)
    expect(screen.getByRole('img', { name: 'Codex 推出新的协作工作流 缩略图' })).toHaveAttribute('src', '/api/media/med_first')
    expect(screen.getByText('完整抓取正文')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '第一张' })).toHaveAttribute('src', '/api/media/med_first')
    expect(screen.getByRole('img', { name: '第二张' })).toHaveAttribute('src', '/api/media/med_second')
  })

  it('allows a viewer to open and copy while disabling all state mutations', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={items}
        selectedId="article-1"
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
        readonly
      />,
    )

    expect(screen.getByRole('link', { name: '打开原文' })).toHaveAttribute('href', 'https://openai.com/codex')
    expect(screen.getByRole('button', { name: '稍后读' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '收藏' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '更多操作' }))
    expect(screen.getByRole('menuitem', { name: '标记已读' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('menuitem', { name: '忽略' })).toHaveAttribute('aria-disabled', 'true')
    await user.click(screen.getByRole('menuitem', { name: '复制摘要' }))
    expect(writeText).toHaveBeenCalledWith('更清晰的任务分解与上下文协作。')
  })

  it('shows explicit fallback copy when classification and analysis are missing', () => {
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={[{ id: 'missing', title: '只有标题的条目', url: '' }]}
        selectedId="missing"
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
      />,
    )

    const reader = within(screen.getByRole('region', { name: '阅读详情' }))
    expect(reader.getByText('暂无概括；请打开原文核对完整内容。')).toBeInTheDocument()
    expect(reader.getByText('未评分')).toBeInTheDocument()
    expect(reader.getByText('未分类频道')).toBeInTheDocument()
    expect(reader.getByText('未分类类型')).toBeInTheDocument()
    expect(reader.queryByRole('heading', { name: '为什么值得关注' })).not.toBeInTheDocument()
    expect(reader.getByText('该条内容未保存正文片段；重新获取来源后可显示。')).toBeInTheDocument()
    expect(reader.queryByText('暂无来源摘录。')).not.toBeInTheDocument()
    expect(reader.queryByText('暂无建议动作；打开原文后再决定是否跟进。')).not.toBeInTheDocument()
    expect(reader.getByText('来源健康：尚未抓取')).toBeInTheDocument()
    expect(reader.getByText('原文链接不可用')).toBeInTheDocument()
  })

  it('degrades a partially projected legacy detail without crashing the workspace', () => {
    const legacyDetail = {
      id: 'legacy-detail',
      title: '迁移后的旧条目',
      url: 'https://example.com/legacy-detail',
      source: 'Legacy RSS',
      summary_zh: '旧快照摘要',
      presentation: {
        version: 2,
        source: { avatar_url: '' },
        content: {
          body_text: '旧快照摘要',
          body_truncated: false,
          body_completeness: 'excerpt_only',
        },
        media: { images: [], count: 0 },
      },
    } as unknown as FeedItem

    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={[legacyDetail]}
        selectedId="legacy-detail"
        selectedItem={legacyDetail}
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
      />,
    )

    const reader = within(screen.getByRole('region', { name: '阅读详情' }))
    expect(reader.getByRole('heading', { name: '迁移后的旧条目' })).toBeInTheDocument()
    expect(reader.getByRole('link', { name: '打开原文' })).toHaveAttribute('href', 'https://example.com/legacy-detail')
    expect(reader.getAllByText('旧快照摘要')).toHaveLength(1)
    expect(reader.getByText('来源暂未提供可保存的全文；当前仅展示上方概括。')).toBeInTheDocument()
    expect(reader.getByText('未评分')).toBeInTheDocument()
  })

  it('marks a bounded body preview as truncated without rendering source HTML', () => {
    const item = {
      ...items[0],
      id: 'article-truncated',
      presentation: {
        ...items[0].presentation!,
        content: {
          ...items[0].presentation!.content,
          excerpt: '第一段\n\n第二段',
          excerpt_truncated: true,
        },
      },
    }
    render(
      <FeedWorkspace
        title="今日信息流"
        description="1 条"
        items={[item]}
        selectedId="article-truncated"
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
      />,
    )

    const reader = within(screen.getByRole('region', { name: '阅读详情' }))
    expect(reader.getByText(/第一段/)).toHaveTextContent('第一段 第二段')
    expect(reader.getByText('内容已截断，打开原文查看完整内容。')).toBeInTheDocument()
  })

  it('offers retry for errors and clear filters for an empty result', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    const onClearFilters = vi.fn()
    const { rerender } = render(
      <FeedWorkspace
        title="今日信息流"
        description="0 条"
        items={[]}
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
        error="信息流加载失败"
        onRetry={onRetry}
      />,
    )
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalledOnce()

    rerender(
      <FeedWorkspace
        title="今日信息流"
        description="0 条"
        items={[]}
        onSelect={vi.fn()}
        onStateAction={vi.fn()}
        sourceHealth={[]}
        onClearFilters={onClearFilters}
      />,
    )
    await user.click(screen.getByRole('button', { name: '清除筛选' }))
    expect(onClearFilters).toHaveBeenCalledOnce()
  })
})
