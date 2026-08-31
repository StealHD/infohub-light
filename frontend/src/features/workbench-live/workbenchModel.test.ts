import { describe, expect, it } from 'vitest'

import type { FeedItem, FeedPresentation, FeedSnapshot } from '../../api/types'
import {
  cardLabelForViewer,
  cleanLegacyModeSearch,
  mergeDeepLinkedItem,
  selectWorkbenchSourceItems,
  toWorkbenchCardModel,
  workbenchSourceLabels,
} from './workbenchModel'

const item = (id: string, publishedAt?: string, summary = `摘要 ${id}`): FeedItem => ({
  id,
  title: `标题 ${id}`,
  url: `https://example.com/${id}`,
  published_at: publishedAt,
  source: '测试来源',
  summary_zh: summary,
  channel: 'AI',
  topics: ['Codex'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
})

describe('live workbench model', () => {
  it('uses source-first labels for social media and titles for articles', () => {
    const article = toWorkbenchCardModel(item('article'))
    const social = {
      ...article,
      displayKind: 'social' as const,
      sourceLabel: 'Alice',
      primaryText: 'hello',
    }

    expect(cardLabelForViewer(article)).toBe('标题 article')
    expect(cardLabelForViewer(social)).toBe('Alice: hello')
  })

  it('reads only snapshot.items for Feed and maps the shared card contract', () => {
    const all = item('all', '2026-07-13T08:00:00Z')
    const snapshot: FeedSnapshot = {
      schema_version: 2,
      items: [all],
      featured_items: [item('featured')],
      daily_push_items: [item('daily')],
    }

    expect(selectWorkbenchSourceItems('feed', { snapshot })).toEqual([all])
    expect(toWorkbenchCardModel(all)).toMatchObject({
      id: 'all',
      title: '标题 all',
      summary: '摘要 all',
      source: '测试来源',
      channel: 'AI',
      topics: ['Codex'],
    })
  })

  it('omits summaries that only repeat the title and keeps distinct summaries', () => {
    expect(toWorkbenchCardModel(item('same', '2026-07-13T08:00:00Z', '  标题 SAME。 ')).summary).toBeUndefined()
    expect(toWorkbenchCardModel(item('distinct', '2026-07-13T08:00:00Z', '这是独立概括')).summary).toBe('这是独立概括')
    expect(toWorkbenchCardModel({ ...item('missing'), summary_zh: undefined }).summary).toBeUndefined()
  })

  it('maps X posts to a source-first social card without repeating the generated title', () => {
    const social: FeedItem = {
      ...item('x-post'),
      title: '@thsottiaux: Oops... I did it again. Enjoy reset usage limits for all paid users fo...',
      summary_zh: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.',
      source_type: 'apify_social',
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
    }

    expect(toWorkbenchCardModel(social)).toMatchObject({
      displayKind: 'social',
      format: 'social_post',
      formatLabel: '社交动态',
      platformLabel: 'X',
      sourceLabel: '@thsottiaux',
      authorLabel: 'Tibo',
      primaryText: 'Oops... I did it again. Enjoy reset usage limits for all paid users.',
      detailBody: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.',
      summary: undefined,
      hasDistinctDetail: true,
    })
  })

  it('omits a URL-shaped social author while preserving the readable source account', () => {
    const social = socialItemWithMedia()
    if (!social.presentation) throw new Error('presentation fixture missing')
    social.presentation.source.name = 'X · @朋友动态'
    social.presentation.source.platform = 'x'
    social.presentation.author.name = 'https://x.com/thsottiaux/status/2093573991965557198'
    social.presentation.links.canonical_url = 'https://x.com/thsottiaux/status/2093573991965557198'
    social.presentation.links.source_url = 'https://x.com/thsottiaux'

    const card = toWorkbenchCardModel(social)

    expect(card).toMatchObject({
      source: 'X · @朋友动态',
      platformLabel: 'X',
      sourceLabel: '@朋友动态',
      authorLabel: undefined,
    })
    expect(workbenchSourceLabels(card)).toEqual(['X', '@朋友动态'])
  })

  it('hides a social source label duplicated by the channel while preserving the followed account', () => {
    const social = socialItemWithMedia()
    if (!social.presentation) throw new Error('presentation fixture missing')
    social.presentation.source.name = 'X · @朋友动态'
    social.presentation.source.platform = 'x'
    social.presentation.author.name = 'thsottiaux'
    social.presentation.taxonomy.channel = '朋友动态'

    const card = toWorkbenchCardModel(social)

    expect(card).toMatchObject({
      platformLabel: 'X',
      sourceLabel: '@朋友动态',
      authorLabel: 'thsottiaux',
      channel: '朋友动态',
    })
    expect(workbenchSourceLabels(card)).toEqual(['X', 'thsottiaux'])
  })

  it('derives an X handle when both source fields contain only the post URL', () => {
    const social = socialItemWithMedia()
    if (!social.presentation) throw new Error('presentation fixture missing')
    const postUrl = 'https://x.com/thsottiaux/status/2093573991965557198'
    social.source = postUrl
    social.presentation.source.name = postUrl
    social.presentation.source.platform = 'x'
    social.presentation.author.name = 'Tibo'
    social.presentation.links.canonical_url = postUrl
    social.presentation.links.source_url = 'https://x.com/thsottiaux'

    const card = toWorkbenchCardModel(social)

    expect(card).toMatchObject({
      source: 'X · @thsottiaux',
      platformLabel: 'X',
      sourceLabel: '@thsottiaux',
      authorLabel: 'Tibo',
    })
    expect(workbenchSourceLabels(card)).toEqual(['X', 'Tibo', '@thsottiaux'])
  })

  it('maps explicit gallery metadata and keeps only local cached images', () => {
    const gallery = socialItemWithMedia()
    const card = toWorkbenchCardModel(gallery)

    expect(card).toMatchObject({
      format: 'gallery',
      formatOrigin: 'upstream',
      formatLabel: '图集',
      displayImageCount: 2,
      totalImageCount: 8,
      mediaTruncated: true,
    })
    expect(card.mediaImages.map((image) => image.url)).toEqual(['/api/media/one', '/api/media/two'])
  })

  it.each([
    ['article', '文章'],
    ['video', '视频'],
    ['image', '图片'],
    ['gallery', '图集'],
    ['audio', '音频'],
    ['social_post', '社交动态'],
    ['discussion', '讨论'],
    ['release', '版本发布'],
    ['other', '其他'],
  ] as const)('maps the %s format to its shared Chinese label', (format, label) => {
    const formatted = socialItemWithMedia()
    if (formatted.presentation) formatted.presentation.content.format = format

    expect(toWorkbenchCardModel(formatted)).toMatchObject({ format, formatLabel: label })
  })

  it('recognizes a legacy Instagram snapshot by platform and removes duplicate author metadata', () => {
    const legacyPresentation = {
      version: 1,
      source: { id: 'instagram-source', catalog_type: 'apify_social', platform: 'instagram', name: 'tsucha_ri' },
      author: { name: 'tsucha_ri', kind: 'account' },
      timing: { published_at: '2026-05-05T08:00:00Z', fetched_at: '2026-05-05T08:05:00Z' },
      links: { canonical_url: 'https://instagram.com/p/example', source_url: 'https://instagram.com/tsucha_ri' },
      content: { title: '8thオフショ #シャニマス', title_origin: 'generated', excerpt: '8thオフショ #シャニマス', excerpt_truncated: false },
      taxonomy: { channel: '其他', configured_topics: [], inferred_topics: [], topics: [], entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'fallback', score: 0, signal_strength: 'unknown', signal_type: 'unknown', summary_zh: '8thオフショ #シャニマス' },
    } as unknown as FeedPresentation
    const legacy: FeedItem = { ...item('instagram-post'), source_type: 'apify_social', presentation: legacyPresentation }

    expect(toWorkbenchCardModel(legacy)).toMatchObject({
      displayKind: 'social',
      platformLabel: 'Instagram',
      sourceLabel: 'tsucha_ri',
      authorLabel: undefined,
      primaryText: '8thオフショ #シャニマス',
      summary: undefined,
    })
  })

  it('infers the readable platform from a legacy social source name', () => {
    const legacy = {
      ...item('legacy-x'),
      source: 'X · @legacy_account',
      source_type: 'apify_social',
      title: '@legacy_account: legacy post body',
      summary_zh: 'legacy post body',
    }

    expect(toWorkbenchCardModel(legacy)).toMatchObject({
      displayKind: 'social',
      platformLabel: 'X',
      sourceLabel: '@legacy_account',
      primaryText: 'legacy post body',
    })
  })

  it('suppresses a substantially repeated truncated article summary without fuzzy matching', () => {
    const repeated = item(
      'prefix-repeat',
      '2026-07-13T08:00:00Z',
      'AI 原生产品的交互范式演进：从功能堆叠转向结果交付与可信任的完整闭环。',
    )
    repeated.title = 'AI 原生产品的交互范式演进：从功能堆叠转向结果交付与可信任…'
    expect(toWorkbenchCardModel(repeated).summary).toBeUndefined()
  })

  it('inserts a deep-linked item chronologically without duplicating an existing item', () => {
    const older = item('older', '2026-07-13T08:00:00Z')
    const newest = item('newest', '2026-07-13T12:00:00Z')
    const middle = item('middle', '2026-07-13T10:00:00Z')

    expect(mergeDeepLinkedItem([older, newest], middle).map(({ id }) => id)).toEqual(['older', 'middle', 'newest'])
    expect(mergeDeepLinkedItem([older, middle], middle)).toHaveLength(2)
  })

  it('replaces a late snapshot copy with fetched v2 detail while preserving user state', () => {
    const snapshot = item('selected', '2026-07-13T10:00:00Z')
    snapshot.user_state = { is_read: false, is_saved: true, is_later: false, dismissed: false }
    const detail: FeedItem = {
      id: 'selected',
      title: '旧兼容标题',
      url: 'https://example.com/selected',
      presentation: {
        version: 2,
        source: { id: 'source-v2', catalog_type: 'rss', platform: 'rss', name: 'V2 来源' },
        author: { name: '作者', kind: 'person' },
        timing: { published_at: '2026-07-13T10:00:00Z', fetched_at: '2026-07-13T10:01:00Z' },
        links: { canonical_url: 'https://example.com/selected', source_url: 'https://example.com/selected' },
        content: { title: '详情标题', title_origin: 'native', excerpt: '详情摘录', body_text: '完整详情正文', content_kind: 'feed_summary', excerpt_truncated: false, body_truncated: false },
        taxonomy: { channel: '详情频道', configured_topics: [], inferred_topics: [], topics: ['详情主题'], entities: [] },
        engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
        analysis: { status: 'ai', score: 9, signal_strength: 'strong', signal_type: 'update', summary_zh: '详情概括' },
      },
    }

    const [merged] = mergeDeepLinkedItem([snapshot], detail)
    expect(merged.user_state?.is_saved).toBe(true)
    expect(toWorkbenchCardModel(merged)).toMatchObject({
      title: '详情标题',
      body: '完整详情正文',
      summary: '详情概括',
      source: 'V2 来源',
    })
  })

  it('cleans retired mode parameters while preserving item deep links', () => {
    expect(cleanLegacyModeSearch('?mode=daily&item=article-1&source=rss')).toBe('?item=article-1&source=rss')
  })

})

function socialItemWithMedia(): FeedItem {
  const base = item('gallery', '2026-07-18T08:00:00Z')
  return {
    ...base,
    source_type: 'apify_social',
    presentation: {
      version: 2,
      source: { id: 'instagram-source', catalog_type: 'apify_social', platform: 'instagram', name: 'Instagram · example' },
      author: { name: 'example', kind: 'account' },
      timing: { published_at: '2026-07-18T08:00:00Z', fetched_at: '2026-07-18T08:05:00Z' },
      links: { canonical_url: 'https://instagram.com/p/example', source_url: 'https://instagram.com/example' },
      content: {
        title: 'Gallery', title_origin: 'generated', excerpt: 'Gallery body', content_kind: 'caption',
        excerpt_truncated: false, format: 'gallery', format_origin: 'upstream',
      },
      media: {
        images: [
          { asset_id: 'one', url: '/api/media/one', alt: '图片一' },
          { asset_id: 'two', url: '/api/media/two', alt: '图片二' },
          { asset_id: 'remote', url: 'https://remote.example/three.jpg', alt: '远程图片' },
        ],
        count: 2,
        total_image_count: 8,
        truncated: true,
      },
      taxonomy: { channel: '其他', configured_topics: [], inferred_topics: [], topics: [], entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'fallback', score: 0, signal_strength: 'thin', signal_type: 'other', summary_zh: 'Gallery body' },
    },
  }
}
