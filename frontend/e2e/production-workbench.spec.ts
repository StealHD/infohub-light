import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'

const items = Array.from({ length: 200 }, (_, index) => ({
  id: `live-${index + 1}`,
  title: `实时条目 ${index + 1}`,
  url: `https://example.com/live-${index + 1}`,
  source: index % 2 ? 'OpenAI Blog' : 'GitHub',
  source_type: index % 2 ? 'rss' : 'github',
  summary_zh: `第 ${index + 1} 条真实 API 摘要`,
  media_urls: [`/api/media/live-${index + 1}`],
  published_at: new Date(Date.UTC(2026, 6, 1, 0, index)).toISOString(),
  channel: index % 2 ? 'AI' : '开发',
  topics: ['Codex'],
  user_state: { is_read: index % 3 === 0, is_saved: false, is_later: false, dismissed: false },
}))
const rollingItem = {
  ...items.at(-1)!,
  id: 'live-201',
  title: '实时条目 201',
  url: 'https://example.com/live-201',
  summary_zh: '固定长度窗口中的新内容',
  published_at: '2026-07-01T04:00:00.000Z',
}
const batchRollingItems = Array.from({ length: 80 }, (_, index) => ({
  ...items.at(-1)!,
  id: `live-${201 + index}`,
  title: `实时条目 ${201 + index}`,
  url: `https://example.com/live-${201 + index}`,
  source: index % 2 ? 'OpenAI Blog' : 'GitHub',
  published_at: new Date(Date.UTC(2026, 6, 1, 4, index)).toISOString(),
  user_state: { is_read: index % 3 === 0, is_saved: false, is_later: false, dismissed: false },
}))
const savedRouteItem = {
  ...items[0],
  id: 'saved-route-item',
  title: '生产收藏路由条目',
  url: 'https://example.com/saved-route-item',
  user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
}
const historyRouteItem = {
  ...items[0],
  id: 'history-route-item',
  title: '生产历史路由条目',
  url: 'https://example.com/history-route-item',
  presentation: {
    timing: { effective_at: '2026-06-01T08:00:00Z' },
  } as unknown as typeof items[number]['presentation'],
  user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false },
}
const tsuchaHistoryItems = [
  {
    ...historyRouteItem,
    id: 'tsucha-history-1',
    title: 'tsucha_ri 历史内容一',
    url: 'https://example.com/tsucha-history-1',
    source: 'tsucha_ri',
    source_id: 'source-tsucha',
  },
  {
    ...historyRouteItem,
    id: 'tsucha-history-2',
    title: 'tsucha_ri 历史内容二',
    url: 'https://example.com/tsucha-history-2',
    source: 'tsucha_ri',
    source_id: 'source-tsucha',
  },
]
const socialRouteItem = {
  id: 'social:x:1',
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
      format: 'gallery',
      format_origin: 'upstream',
    },
    media: {
      images: [
        { asset_id: 'social-one', url: '/api/media/social-one', alt: '社交图片一' },
        { asset_id: 'social-two', url: '/api/media/social-two', alt: '社交图片二' },
      ],
      count: 2,
      total_image_count: 4,
      truncated: true,
    },
    taxonomy: { channel: '其他', configured_topics: [], inferred_topics: ['行业动态'], topics: ['行业动态'], entities: [] },
    engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
    analysis: { status: 'ai', score: 7, signal_strength: 'medium', signal_type: 'update', summary_zh: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.' },
  },
}

async function topVisibleSnapshot(page: Page) {
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  return page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollElement) => {
    const bounds = (scrollElement as HTMLElement).getBoundingClientRect()
    const visible = cards
      .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
      .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)
    const top = visible[0]
    return {
      name: top?.getAttribute('aria-label') ?? '',
      offset: top ? top.getBoundingClientRect().top - bounds.top : 0,
    }
  }, await feedScroll.elementHandle())
}

async function expectLocatorInside(inner: Locator, outer: Locator) {
  const [innerBounds, outerBounds] = await Promise.all([inner.boundingBox(), outer.boundingBox()])
  expect(innerBounds).not.toBeNull()
  expect(outerBounds).not.toBeNull()
  expect(innerBounds!.x).toBeGreaterThanOrEqual(outerBounds!.x - 1)
  expect(innerBounds!.y).toBeGreaterThanOrEqual(outerBounds!.y - 1)
  expect(innerBounds!.x + innerBounds!.width).toBeLessThanOrEqual(outerBounds!.x + outerBounds!.width + 1)
  expect(innerBounds!.y + innerBounds!.height).toBeLessThanOrEqual(outerBounds!.y + outerBounds!.height + 1)
}

async function stableTopVisibleSnapshot(page: Page) {
  let previous = await topVisibleSnapshot(page)
  let stableFrames = 0
  for (let frame = 0; frame < 120 && stableFrames < 3; frame += 1) {
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
    const current = await topVisibleSnapshot(page)
    stableFrames = current.name === previous.name && Math.abs(current.offset - previous.offset) <= 0.5
      ? stableFrames + 1
      : 0
    previous = current
  }
  expect(stableFrames).toBe(3)
  return previous
}

async function alignVisibleCardToTop(page: Page) {
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  let stableFrames = 0
  let previous = await topVisibleSnapshot(page)
  for (let frame = 0; frame < 120 && stableFrames < 3; frame += 1) {
    expect(previous.name).not.toBe('')
    if (Math.abs(previous.offset) > 0.5) {
      stableFrames = 0
      await feedScroll.evaluate((element, correction) => {
        element.scrollTop += correction
        element.dispatchEvent(new Event('scroll'))
      }, previous.offset)
    }
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
    const current = await topVisibleSnapshot(page)
    if (current.name === previous.name && Math.abs(current.offset) <= 0.5 && Math.abs(current.offset - previous.offset) <= 0.5) {
      stableFrames += 1
    } else if (Math.abs(previous.offset) <= 0.5) {
      stableFrames = 0
    }
    previous = current
  }
  expect(stableFrames).toBe(3)
  expect(Math.abs(previous.offset)).toBeLessThanOrEqual(0.5)
  return previous
}

async function requestBackgroundRefresh(page: Page) {
  // The desktop Insights surface can overlap the ViewBar by this point in the
  // end-to-end flow, so invoke the already-rendered control without pointer scrolling.
  await page.getByRole('button', { name: '获取新内容' }).evaluate((element: HTMLElement) => element.click())
  await page.evaluate(() => (window as typeof window & {
    completeBackgroundRefresh: () => Promise<void>
  }).completeBackgroundRefresh())
}

test.beforeEach(async ({ page }) => {
  let backgroundRefreshComplete = false
  let manualReloadComplete = false
  let manualReloadGate: Promise<void> | null = null
  let releaseManualReload = () => undefined
  let feedbackRefreshRequested = false
  let feedbackRetryRequests = 0
  let latestFeedRequests = 0
  let feedUpdateRequests = 0
  const backgroundRefreshCreatedAt = new Date().toISOString()
  await page.exposeFunction('completeBackgroundRefresh', () => {
    backgroundRefreshComplete = true
  })
  await page.exposeFunction('completeManualFeedReload', () => {
    manualReloadComplete = true
    releaseManualReload()
  })
  await page.exposeFunction('pauseManualFeedReload', () => {
    manualReloadComplete = true
    manualReloadGate = new Promise<void>((resolve) => {
      releaseManualReload = () => {
        manualReloadGate = null
        releaseManualReload = () => undefined
        resolve()
      }
    })
  })
  await page.exposeFunction('feedRequestCounts', () => ({
    latest: latestFeedRequests,
    updates: feedUpdateRequests,
  }))
  await page.exposeFunction('feedbackRetryCount', () => feedbackRetryRequests)
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    const feedbackMode = new URL(page.url()).searchParams.has('toast-feedback')
    let data: unknown
    if (url.pathname.startsWith('/api/media/')) {
      const portrait = url.pathname.endsWith('/social-one')
      const landscape = url.pathname.endsWith('/social-two')
      const width = portrait ? 2046 : landscape ? 1600 : 640
      const height = portrait ? 2728 : landscape ? 900 : 480
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#29272f"/></svg>`,
      })
      return
    }
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } }
    else if (url.pathname === '/api/feed/latest') {
      latestFeedRequests += 1
      const pendingManualReload = manualReloadGate
      if (pendingManualReload) await pendingManualReload
      const batchMode = new URL(page.url()).searchParams.has('batch')
      const socialMode = new URL(page.url()).searchParams.has('social')
      data = { schema_version: 2, items: socialMode ? [socialRouteItem] : backgroundRefreshComplete || manualReloadComplete
        ? batchMode ? [...items.slice(80), ...batchRollingItems] : [...items.slice(1), rollingItem]
        : items }
    }
    else if (url.pathname === '/api/feed/saved') data = { items: [savedRouteItem] }
    else if (url.pathname === '/api/feed/history') {
      const sourceId = url.searchParams.get('source_id')
      const offset = Number(url.searchParams.get('offset') || '0')
      if (sourceId === 'source-tsucha') {
        const pageItems = offset === 0 ? [tsuchaHistoryItems[0]] : [tsuchaHistoryItems[1]]
        data = {
          items: pageItems,
          item_count: pageItems.length,
          total_count: 2,
          limit: 50,
          offset,
          has_more: offset === 0,
          snapshots: [],
          featured_items: [],
        }
      } else {
        data = {
          items: [historyRouteItem],
          item_count: 1,
          total_count: 1,
          limit: 50,
          offset: 0,
          has_more: false,
          snapshots: [],
          featured_items: [],
        }
      }
    }
    else if (url.pathname === '/api/catalog/sources') data = {
      sources: [
        { id: 'source-tsucha', type: 'apify_social', display_name: 'tsucha_ri', scope: 'public', enabled: true },
      ],
    }
    else if (url.pathname === '/api/jobs/user-feed-refresh' && route.request().method() === 'POST') {
      feedUpdateRequests += 1
      feedbackRefreshRequested = true
      data = {
        id: 'refresh-1',
        user_id: 'e2e-user',
        job_type: 'user_feed_refresh',
        status: 'queued',
        created_at: backgroundRefreshCreatedAt,
      }
    }
    else if (url.pathname === '/api/jobs/refresh-1/retry' && route.request().method() === 'POST') {
      feedbackRetryRequests += 1
      data = {
        id: 'refresh-1',
        user_id: 'e2e-user',
        job_type: 'user_feed_refresh',
        status: 'queued',
        created_at: backgroundRefreshCreatedAt,
      }
    }
    else if (url.pathname === '/api/jobs') data = {
      jobs: !feedbackRefreshRequested
        ? []
        : [{
            id: 'refresh-1',
            user_id: 'e2e-user',
            job_type: 'user_feed_refresh',
            status: backgroundRefreshComplete ? (feedbackMode ? 'failed' : 'succeeded') : 'queued',
            created_at: backgroundRefreshCreatedAt,
            finished_at: backgroundRefreshComplete ? new Date().toISOString() : null,
            retryable: feedbackMode && backgroundRefreshComplete,
            error_message: feedbackMode && backgroundRefreshComplete ? '模拟信息流更新失败' : undefined,
            result: {},
          }],
    }
    else if (url.pathname === '/api/me/feed-schedule') data = { enabled: true, interval_minutes: 60, worker_status: 'ready' }
    else if (url.pathname === '/api/me/source-health') data = {
      summary: { total: 2, healthy: 1, attention: 1, failing: 0, untested: 0 },
      items: [
        { source_id: 'source-healthy', status: 'healthy' },
        { source_id: 'source-degraded', status: 'degraded' },
      ],
    }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: '/mcp',
      subscription_writes_enabled: false,
      openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' },
      token_ttl_days: 90,
      max_active: 5,
      connections: [{ id: 'agent-1', name: 'OpenClaw', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'], token_prefix: 'abc', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname.startsWith('/api/feed/items/')) {
      const item = [...items, rollingItem, savedRouteItem, historyRouteItem, ...tsuchaHistoryItems, socialRouteItem].find((candidate) => candidate.id === decodeURIComponent(url.pathname.split('/').at(-1) || ''))
      if (!item) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
        return
      }
      data = item
    }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
      return
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
})

test.afterEach(async ({ page }) => {
  if (page.isClosed()) return
  await page.evaluate(() => (window as typeof window & {
    completeManualFeedReload: () => Promise<void>
  }).completeManualFeedReload())
  await page.unrouteAll({ behavior: 'wait' })
})

test('a retryable refresh failure uses a top Toast without moving the Feed viewport', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/feed?toast-feedback=1')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  const before = await feedScroll.boundingBox()

  await page.getByRole('button', { name: '获取新内容' }).click()
  await page.evaluate(() => (window as typeof window & {
    completeBackgroundRefresh: () => Promise<void>
  }).completeBackgroundRefresh())

  const failure = page.getByText('模拟信息流更新失败', { exact: true })
  await expect(failure).toBeVisible({ timeout: 10_000 })
  const after = await feedScroll.boundingBox()
  expect(before).not.toBeNull()
  expect(after).not.toBeNull()
  expect(Math.abs(after!.x - before!.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(after!.y - before!.y)).toBeLessThanOrEqual(1)
  expect(Math.abs(after!.width - before!.width)).toBeLessThanOrEqual(1)
  expect(Math.abs(after!.height - before!.height)).toBeLessThanOrEqual(1)
  await expect(page.locator('main').getByText('模拟信息流更新失败', { exact: true })).toHaveCount(0)

  const toastBounds = await failure.boundingBox()
  const viewport = page.viewportSize()!
  expect(toastBounds).not.toBeNull()
  expect(toastBounds!.x).toBeGreaterThanOrEqual(0)
  expect(toastBounds!.x + toastBounds!.width).toBeLessThanOrEqual(viewport.width)
  const retryRequest = page.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith('/api/jobs/refresh-1/retry'))
  await page.getByRole('button', { name: '重试' }).click()
  await retryRequest
  await expect.poll(() => page.evaluate(() => (window as typeof window & {
    feedbackRetryCount: () => Promise<number>
  }).feedbackRetryCount())).toBe(1)
  await expect(failure).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('manual Feed data reload reads the latest snapshot without creating an update job', async ({ page }) => {
  await page.goto('/feed')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  const before = await page.evaluate(() => (window as typeof window & {
    feedRequestCounts: () => Promise<{ latest: number; updates: number }>
  }).feedRequestCounts())
  await page.evaluate(() => (window as typeof window & {
    completeManualFeedReload: () => Promise<void>
  }).completeManualFeedReload())

  await page.getByRole('button', { name: '重新载入信息流数据' }).click()

  await expect(page.getByRole('article', { name: '实时条目 201' })).toBeVisible()
  const after = await page.evaluate(() => (window as typeof window & {
    feedRequestCounts: () => Promise<{ latest: number; updates: number }>
  }).feedRequestCounts())
  expect(after.latest).toBeGreaterThan(before.latest)
  expect(after.updates).toBe(before.updates)
  await expect(page.getByRole('button', { name: '重新载入信息流数据' })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('manual Feed reload keeps ViewBar geometry stable while pending at 675px', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The exact feedback viewport is covered once.')
  await page.setViewportSize({ width: 675, height: 762 })
  await page.goto('/feed')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await page.evaluate(async () => { await document.fonts.ready })
  const reload = page.getByRole('button', { name: '重新载入信息流数据' })
  const update = page.getByRole('button', { name: '获取新内容' })
  const filter = page.getByRole('button', { name: '筛选信息流' })
  const viewBar = page.getByTestId('feed-view-bar')
  const controls = [viewBar, reload, update, filter]
  const geometry = async () => Promise.all(controls.map(async (control) => {
    const box = await control.boundingBox()
    expect(box).not.toBeNull()
    return box!
  }))
  const expectStableGeometry = (current: Awaited<ReturnType<typeof geometry>>, baseline: Awaited<ReturnType<typeof geometry>>) => {
    current.forEach((box, index) => {
      expect(Math.abs(box.x - baseline[index].x)).toBeLessThanOrEqual(1)
      expect(Math.abs(box.y - baseline[index].y)).toBeLessThanOrEqual(1)
      expect(Math.abs(box.width - baseline[index].width)).toBeLessThanOrEqual(1)
      expect(Math.abs(box.height - baseline[index].height)).toBeLessThanOrEqual(1)
    })
  }
  const before = await geometry()
  const anchorBefore = await stableTopVisibleSnapshot(page)
  await page.evaluate(() => (window as typeof window & {
    pauseManualFeedReload: () => Promise<void>
  }).pauseManualFeedReload())

  await reload.click()

  await expect(reload).toBeDisabled()
  await expect(reload).toHaveAttribute('aria-busy', 'true')
  await expect(reload.locator('svg')).toHaveCount(1)
  expectStableGeometry(await geometry(), before)
  const anchorPending = await topVisibleSnapshot(page)
  expect(anchorPending.name).toBe(anchorBefore.name)
  expect(Math.abs(anchorPending.offset - anchorBefore.offset)).toBeLessThanOrEqual(1)

  await page.evaluate(() => (window as typeof window & {
    completeManualFeedReload: () => Promise<void>
  }).completeManualFeedReload())
  await expect(page.getByRole('article', { name: '实时条目 201' })).toBeVisible()
  await expect(reload).toBeEnabled()
  await expect(reload).not.toHaveAttribute('aria-busy')
  await expect(reload.locator('svg')).toHaveCount(1)
  expectStableGeometry(await geometry(), before)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

for (const viewport of [
  { width: 320, height: 700 },
  { width: 390, height: 844 },
  { width: 645, height: 762 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
]) {
  test(`header order and card action tooltips stay correct at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'One browser project exercises the three explicit acceptance widths.')
    await page.setViewportSize(viewport)
    await page.goto('/feed?social=1')
    const card = page.getByRole('article', { name: /@thsottiaux: Oops/ })
    await expect(card).toBeVisible()

    const theme = page.getByRole('button', { name: '切换到白天模式' })
    const insights = page.getByRole('button', { name: '展开信息概览' })
    const agent = page.getByRole('button', { name: '展开 Agent 面板' })
    const [themeBox, insightsBox, agentBox] = await Promise.all([
      theme.boundingBox(),
      insights.boundingBox(),
      agent.boundingBox(),
    ])
    expect(themeBox).not.toBeNull()
    expect(insightsBox).not.toBeNull()
    expect(agentBox).not.toBeNull()
    expect(themeBox!.x).toBeLessThan(insightsBox!.x)
    expect(insightsBox!.x).toBeLessThan(agentBox!.x)

    const viewBarTooltipCases: Array<{ trigger: Locator; text: string }> = [
      { trigger: page.getByRole('button', { name: '排序依据：发布时间' }), text: '当前按发布时间；点击改为入库时间' },
      { trigger: page.getByRole('button', { name: '排序顺序：最新优先' }), text: '当前最新优先；点击改为最旧优先' },
      { trigger: page.getByRole('button', { name: '重新载入信息流数据' }), text: '重新载入本地信息流数据' },
      { trigger: page.getByRole('button', { name: '获取新内容' }), text: '触发所有已启用订阅获取新内容' },
    ]
    if (viewport.width < 640) {
      viewBarTooltipCases.unshift({ trigger: page.getByRole('button', { name: '搜索信息流' }), text: '搜索信息流' })
    }
    for (const { trigger, text } of viewBarTooltipCases) {
      await trigger.hover()
      const tooltip = page.getByRole('tooltip').filter({ hasText: text })
      await expect(tooltip).toBeVisible()
      const [triggerBounds, tooltipBounds] = await Promise.all([
        trigger.boundingBox(),
        tooltip.boundingBox(),
      ])
      expect(triggerBounds).not.toBeNull()
      expect(tooltipBounds).not.toBeNull()
      expect(tooltipBounds!.y - (triggerBounds!.y + triggerBounds!.height)).toBeGreaterThanOrEqual(2)
      expect(tooltipBounds!.x).toBeGreaterThanOrEqual(7)
      expect(tooltipBounds!.x + tooltipBounds!.width).toBeLessThanOrEqual(viewport.width - 7)
      await page.mouse.move(1, 1)
      await expect(tooltip).toBeHidden()
    }

    const tooltipCases: Array<{ trigger: Locator; text: string }> = [
      { trigger: card.locator('[data-expand-trigger]'), text: '展开内容' },
      { trigger: card.getByRole('link', { name: /打开 .* 原文/ }), text: '在新窗口打开原文' },
      { trigger: card.getByRole('button', { name: /收藏 / }), text: '加入收藏' },
    ]
    for (const { trigger, text } of tooltipCases) {
      await trigger.scrollIntoViewIfNeeded()
      await trigger.hover()
      const tooltip = page.getByRole('tooltip').filter({ hasText: text })
      await expect(tooltip).toBeVisible()
      const [triggerBounds, tooltipBounds] = await Promise.all([
        trigger.boundingBox(),
        tooltip.boundingBox(),
      ])
      expect(triggerBounds).not.toBeNull()
      expect(tooltipBounds).not.toBeNull()
      expect(triggerBounds!.y - (tooltipBounds!.y + tooltipBounds!.height)).toBeGreaterThanOrEqual(2)
      expect(tooltipBounds!.x).toBeGreaterThanOrEqual(7)
      expect(tooltipBounds!.x + tooltipBounds!.width).toBeLessThanOrEqual(viewport.width - 7)
      await page.mouse.move(1, 1)
      await expect(tooltip).toBeHidden()
    }
    await expect(card.getByRole('button', { name: /加入 Agent 上下文/ })).toHaveText('问 Agent')
    await expect(card.getByRole('button', { name: /更多操作/ })).toHaveAttribute('title', '复制摘要或忽略这条内容')

    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    const accessibility = await new AxeBuilder({ page }).analyze()
    expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  })
}

for (const viewport of [
  { width: 390, height: 844 },
  { width: 768, height: 900 },
  { width: 1440, height: 900 },
]) {
  test(`Feed data refresh preserves the reading anchor at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'One browser project exercises the three explicit acceptance widths.')
    await page.setViewportSize(viewport)
    await page.goto('/feed')
    await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
    const reload = page.getByRole('button', { name: '重新载入信息流数据' })
    const update = page.getByRole('button', { name: '获取新内容' })
    await expect(reload).toBeVisible()
    await expect(update).toBeVisible()
    await reload.focus()
    await expect(reload).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(update).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(reload).toBeFocused()

    const feedScroll = page.getByTestId('workbench-feed-scroll')
    await feedScroll.evaluate((element) => {
      element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
      element.dispatchEvent(new Event('scroll'))
    })
    const anchorBefore = await alignVisibleCardToTop(page)
    await page.evaluate(() => (window as typeof window & {
      completeManualFeedReload: () => Promise<void>
    }).completeManualFeedReload())
    await page.keyboard.press('Enter')

    await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeVisible()
    const anchorAfter = await topVisibleSnapshot(page)
    expect(anchorAfter.name).toBe(anchorBefore.name)
    expect(Math.abs(anchorAfter.offset - anchorBefore.offset)).toBeLessThanOrEqual(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    const accessibility = await new AxeBuilder({ page }).analyze()
    expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  })
}

test('a hard refresh preserves shell geometry and reveals only loaded content', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The persisted docked rail is a desktop refresh contract.')

  let releaseAuth = () => undefined
  let releaseFeed = () => undefined
  let releaseAgent = () => undefined
  const authGate = new Promise<void>((resolve) => { releaseAuth = resolve })
  const feedGate = new Promise<void>((resolve) => { releaseFeed = resolve })
  const agentGate = new Promise<void>((resolve) => { releaseAgent = resolve })

  await page.addInitScript(() => {
    window.localStorage.setItem('inteliscope.ui.bootstrap-shell.v1', JSON.stringify({
      userId: 'e2e-user',
      sidebar: 'collapsed',
      rightRail: 'agent',
      rightRailWidth: 420,
    }))
  })
  await page.route('**/api/auth/status', async (route) => {
    await authGate
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } } }),
    })
  })
  await page.route('**/api/feed/latest', async (route) => {
    await feedGate
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { schema_version: 2, items: [items[0]] } }) })
  })
  await page.route('**/api/me/agent-delegations', async (route) => {
    await agentGate
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: {
        enabled: true,
        mcp_url: '/mcp',
        subscription_writes_enabled: false,
        openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' },
        token_ttl_days: 90,
        max_active: 5,
        connections: [],
      } }),
    })
  })

  await page.goto('/feed', { waitUntil: 'domcontentloaded' })

  const bootShell = page.locator('#inteliscope-bootstrap-shell')
  const bootFeed = page.locator('[data-bootstrap-region="feed"]')
  const bootAgent = page.locator('[data-bootstrap-region="agent"]')
  await expect(bootShell).toBeVisible()
  await expect(page.locator('[data-bootstrap-region="navigation"]')).toBeVisible()
  await expect(page.locator('[data-bootstrap-region="header"]')).toBeVisible()
  await expect(bootFeed).toBeVisible()
  await expect(bootAgent).toBeVisible()
  await expect(page.locator('.app-loading')).toHaveCount(0)
  expect(await bootShell.evaluate((element) => getComputedStyle(element).opacity)).toBe('1')
  expect(await bootShell.evaluate((element) => element.getAnimations({ subtree: false }).length)).toBe(0)
  expect(await page.locator('body').evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
  const bootFeedBounds = await bootFeed.boundingBox()
  const bootAgentBounds = await bootAgent.boundingBox()
  expect(bootFeedBounds).not.toBeNull()
  expect(Math.round(bootAgentBounds?.width ?? 0)).toBe(420)

  releaseAuth()
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(bootShell).toHaveCount(0)
  await expect(page.getByRole('status', { name: '正在读取信息流' })).toBeVisible()
  await expect(page.getByRole('status', { name: '正在读取 Agent 面板' })).toBeVisible()
  await expect(page.locator('[data-workbench-feed-skeleton-row]')).toHaveCount(5)
  await expect(page.locator('[data-agent-skeleton-block]')).toHaveCount(3)

  const feedReveal = page.locator('[data-loading-reveal="feed"]')
  const feedSkeletonRow = page.locator('[data-workbench-feed-skeleton-row]').first()
  const liveAgent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
  const feedSkeletonBounds = await feedSkeletonRow.boundingBox()
  const liveAgentBounds = await liveAgent.boundingBox()
  expect(Math.abs((feedSkeletonBounds?.width ?? 0) - (bootFeedBounds?.width ?? 0))).toBeLessThanOrEqual(1)
  expect(Math.abs((liveAgentBounds?.width ?? 0) - (bootAgentBounds?.width ?? 0))).toBeLessThanOrEqual(1)
  const calmMotion = await page.locator('.inteliscope-skeleton-calm').first().evaluate((element) => {
    const style = getComputedStyle(element)
    const before = getComputedStyle(element, '::before')
    return { duration: style.animationDuration, name: style.animationName, beforeContent: before.content, beforeAnimation: before.animationName }
  })
  expect(calmMotion).toEqual({ duration: '1.4s', name: 'inteliscope-skeleton-breathe', beforeContent: 'none', beforeAnimation: 'none' })
  expect(await page.getByTestId('live-workbench-shell').evaluate((element) => element.getAnimations({ subtree: false }).length)).toBe(0)

  await feedReveal.evaluate((element) => {
    const browserWindow = window as typeof window & { refreshTransition?: Promise<Record<string, string>> }
    browserWindow.refreshTransition = new Promise((resolve) => {
      const observer = new MutationObserver(() => {
        if ((element as HTMLElement).dataset.loadingState !== 'revealing') return
        const skeleton = element.querySelector<HTMLElement>('[data-loading-layer]')
        const content = element.querySelector<HTMLElement>('[data-content-layer]')
        if (!skeleton || !content) return
        observer.disconnect()
        const skeletonStyle = getComputedStyle(skeleton)
        const contentStyle = getComputedStyle(content)
        resolve({
          skeletonDuration: skeletonStyle.animationDuration,
          skeletonName: skeletonStyle.animationName,
          contentDuration: contentStyle.animationDuration,
          contentName: contentStyle.animationName,
        })
      })
      observer.observe(element, { attributes: true, childList: true, subtree: true })
    })
  })
  releaseFeed()
  releaseAgent()
  const transition = await page.evaluate(() => (window as typeof window & { refreshTransition?: Promise<Record<string, string>> }).refreshTransition)
  expect(transition).toEqual({
    skeletonDuration: '0.12s',
    skeletonName: 'inteliscope-skeleton-exit',
    contentDuration: '0.2s',
    contentName: 'inteliscope-content-reveal',
  })

  const card = page.getByRole('article', { name: '实时条目 1' })
  await expect(card).toBeVisible()
  await expect(feedReveal).toHaveAttribute('data-loading-state', 'ready')
  await expect(feedReveal.locator('[data-loading-layer]')).toHaveCount(0)
  const cardBounds = await card.boundingBox()
  expect(Math.abs((cardBounds?.width ?? 0) - (feedSkeletonBounds?.width ?? 0))).toBeLessThanOrEqual(1)
  expect(cardBounds?.height ?? 0).toBeGreaterThanOrEqual(120)
  expect(cardBounds?.height ?? 0).toBeLessThanOrEqual(190)
  expect(Math.abs(((await liveAgent.boundingBox())?.width ?? 0) - (liveAgentBounds?.width ?? 0))).toBeLessThanOrEqual(1)
  await expect(page.locator('.app-loading')).toHaveCount(0)
})

test('production HeroUI workbench preserves responsive shell, virtualization and Agent handoff', async ({ context, page }, testInfo) => {
  test.setTimeout(60_000)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/feed')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByText('稍后读')).toHaveCount(0)
  expect(await page.locator('[data-testid="workbench-card"]').count()).toBeLessThanOrEqual(40)
  await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
  const itemCount = page.getByText('近7天 · 200 条', { exact: true })
  await expect(itemCount).toBeVisible()
  expect(await itemCount.evaluate((element) => getComputedStyle(element).whiteSpace)).toBe('nowrap')
  await expect(page.getByRole('button', { name: '排序顺序：最新优先' })).toBeVisible()
  if (testInfo.project.name === 'mobile') {
    await expect(page.getByRole('button', { name: '搜索信息流' })).toBeVisible()
    await expect(page.getByRole('searchbox', { name: '移动端搜索全部内容' })).toHaveCount(0)
  } else {
    await expect(page.getByRole('searchbox', { name: '搜索全部内容' })).toBeVisible()
  }
  await expect(page.getByText('全部', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重新载入信息流数据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '获取新内容' })).toBeVisible()
  const agentToggle = page.getByRole('banner').getByRole('button', { name: /^(收起|展开) Agent 面板$/ })
  await expect(agentToggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
  await expect(agentToggle.locator('[data-split-panel-icon]')).toHaveCount(1)
  await expect(page.getByRole('banner')).toHaveAttribute('data-header-visual', 'quiet-studio')
  await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
  await page.evaluate(() => document.fonts.ready)

  const contextTrigger = page.getByRole('article', { name: '实时条目 200' }).getByRole('button', { name: '将 实时条目 200 加入 Agent 上下文' })
  await expect(contextTrigger).toContainText('问 Agent')

  const shell = page.getByTestId('live-workbench-shell')
  expect(await page.locator('body').evaluate((element) => getComputedStyle(element).color)).toBe(
    await shell.evaluate((element) => getComputedStyle(element).color),
  )
  const desktopNavigation = page.getByRole('complementary', { name: '桌面导航' })
  const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
  let agent: Locator

  if (testInfo.project.name === 'desktop') {
    await page.getByRole('button', { name: '展开信息概览' }).click()
    const insights = page.getByRole('complementary', { name: '信息概览' })
    await expect(insights).toBeVisible()
    await expect(insights.getByText('今日内容', { exact: true })).toBeVisible()
    await expect(insights.getByText('异常来源', { exact: true })).toBeVisible()
    await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toHaveCount(0)
    await page.getByRole('button', { name: '展开 Agent 面板' }).click()
    agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    await expect(insights).toBeVisible()
    const railSeparator = page.getByRole('separator', { name: '调整信息流和 Agent 面板宽度' })
    await expect(railSeparator).toHaveAttribute('aria-valuenow', '400')
    await railSeparator.focus()
    await page.keyboard.press('ArrowLeft')
    await expect(railSeparator).toHaveAttribute('aria-valuenow', '424')
    expect(await page.evaluate(() => window.localStorage.getItem('inteliscope.ui.right-rail.v1:e2e-user'))).toBe(JSON.stringify({ width: 424 }))
    const quietCard = page.locator('[data-card-visual="quiet-studio"]').first()
    expect(await quietCard.evaluate((element) => getComputedStyle(element).borderRadius)).toBe('18px')
    expect(Math.round((await quietCard.boundingBox())?.width ?? 0)).toBeLessThanOrEqual(820)
    await expect(desktopNavigation).toBeVisible()
    await expect(mobileNavigation).toBeHidden()
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect(agent.getByText('未配置', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '展开侧栏' }).click()
    await expect.poll(async () => Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(232)
    expect(await page.evaluate(() => window.localStorage.getItem('inteliscope.ui.sidebar.v1:e2e-user'))).toBe('expanded')
    await expect(desktopNavigation.getByText('浏览', { exact: true })).toBeVisible()
    await expect(desktopNavigation.getByText('常用视图', { exact: true })).toBeVisible()
    await expect(desktopNavigation.getByRole('button', { name: '当天' })).toBeVisible()
    await expect(desktopNavigation.getByText('管理', { exact: true })).toBeVisible()
    const accountTrigger = desktopNavigation.getByRole('button', { name: '打开账户菜单' })
    await accountTrigger.click()
    const accountMenu = page.getByRole('dialog', { name: '账户菜单' })
    await expect(accountMenu.getByRole('button', { name: '退出登录' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(accountTrigger).toBeFocused()

    const fullyVisibleCards = await page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollSelector) => {
      const viewport = document.querySelector(scrollSelector as string)?.getBoundingClientRect()
      if (!viewport) return 0
      return cards.filter((card) => {
        const bounds = card.getBoundingClientRect()
        return bounds.top >= viewport.top && bounds.bottom <= viewport.bottom
      }).length
    }, '[data-testid="workbench-feed-scroll"]')
    expect(fullyVisibleCards).toBeGreaterThanOrEqual(4)
    expect(fullyVisibleCards).toBeLessThanOrEqual(5)

    await page.setViewportSize({ width: 1280, height: 800 })
    await expect.poll(async () => Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    await expect(page.getByRole('button', { name: /侧栏/ })).toHaveCount(0)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()

    const desktopFeed = page.getByTestId('workbench-feed-scroll')
    await desktopFeed.evaluate((element) => {
      element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
      element.dispatchEvent(new Event('scroll'))
    })
    const panelAnchor = await alignVisibleCardToTop(page)
    await agent.getByRole('button', { name: '关闭 Agent 面板' }).click()
    await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeHidden()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect.poll(() => shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').at(-1))).toBe('0px')
    await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
    await expect(page.getByRole('button', { name: '关闭 Agent 面板' })).toHaveCount(0)
    await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(panelAnchor.name)
    await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - panelAnchor.offset)).toBeLessThanOrEqual(2)
    await page.getByRole('button', { name: '展开 Agent 面板' }).click()
    await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeVisible()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await page.setViewportSize({ width: 1024, height: 768 })
    await expect(page.getByRole('dialog', { name: 'OpenClaw 上下文' })).toBeVisible()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    await page.setViewportSize({ width: 1440, height: 900 })
    agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(panelAnchor.name)
    await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - panelAnchor.offset)).toBeLessThanOrEqual(2)
  } else {
    const toggle = page.getByRole('button', { name: '展开 Agent 面板' })
    const feedScroll = page.getByTestId('workbench-feed-scroll')
    const feedReveal = page.locator('[data-loading-reveal="feed"]')
    await expect(feedReveal).toHaveAttribute('data-loading-state', 'ready')
    await feedReveal.evaluate(async (element) => Promise.all(
      element.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => undefined)),
    ))
    const feedBounds = await feedScroll.boundingBox()
    const feedScrollTop = await feedScroll.evaluate((element) => element.scrollTop)
    if (testInfo.project.name === 'mobile') {
      await expect(desktopNavigation).toBeHidden()
      await expect(mobileNavigation).toBeVisible()
      expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(1)
    } else {
      await expect(desktopNavigation).toBeVisible()
      await expect(mobileNavigation).toBeHidden()
      expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
      expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    }
    await toggle.click()
    agent = page.getByRole('dialog', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    await expect(page.getByTestId('right-rail-drawer-backdrop')).toBeVisible()
    await expect(agent.getByText('未配置', { exact: true })).toBeVisible()
    await agent.evaluate(async (element) => Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined))))
    const openFeedBounds = await feedScroll.boundingBox()
    expect(feedBounds).not.toBeNull()
    expect(openFeedBounds).not.toBeNull()
    for (const dimension of ['x', 'y', 'width', 'height'] as const) {
      expect(Math.abs(openFeedBounds![dimension] - feedBounds![dimension])).toBeLessThanOrEqual(1)
    }
    expect(await feedScroll.evaluate((element) => element.scrollTop)).toBe(feedScrollTop)
    expect(await shell.evaluate((element) => {
      let current: HTMLElement | null = element
      while (current && current !== document.body) {
        if (current.inert || current.getAttribute('aria-hidden') === 'true') return true
        current = current.parentElement
      }
      return false
    })).toBe(true)
    await page.keyboard.press('Tab')
    expect(await agent.evaluate((element) => element.contains(document.activeElement))).toBe(true)
    const agentBounds = await agent.boundingBox()
    if (testInfo.project.name === 'mobile') {
      expect(Math.round(agentBounds?.width ?? 0)).toBe(390)
      expect(Math.round((agentBounds?.y ?? 0) + (agentBounds?.height ?? 0))).toBe(844)
    } else {
      expect(Math.abs((agentBounds?.width ?? 0) - 400)).toBeLessThanOrEqual(1)
      expect(Math.round((agentBounds?.x ?? 0) + (agentBounds?.width ?? 0))).toBe(1024)
    }
    // The focused icon-only status owns a Tooltip, so Escape dismisses the
    // innermost overlay before the containing Agent Drawer.
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')
    await expect(agent).toBeHidden()
    await expect(toggle).toBeFocused()
  }
  if (testInfo.project.name === 'mobile') {
    await expect(mobileNavigation.getByRole('link')).toHaveCount(4)
    await expect(mobileNavigation.getByRole('link', { name: '助手连接' })).toBeVisible()
    await expect(mobileNavigation.getByRole('button', { name: '更多与账户' })).toBeVisible()
  }

  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  const expansionAnchorBefore = await stableTopVisibleSnapshot(page)
  const anchorName = expansionAnchorBefore.name
  await feedScroll.dispatchEvent('scroll')
  const card = page.getByRole('article', { name: anchorName })
  // Invoke the already-visible control directly: Playwright's actionability helper otherwise
  // scrolls a partially visible first card before dispatching the click, unlike a pointer click.
  await card.getByRole('button', { name: `展开 ${anchorName}` }).evaluate((element: HTMLElement) => element.click())
  await expect(page).toHaveURL(/item=live-/)
  await expect(card.getByRole('button', { name: `收起 ${anchorName}` })).toBeVisible()
  await expect(card).toHaveAttribute('data-card-expanded', 'true')
  const expandedId = await card.locator('xpath=..').getAttribute('data-item-id')
  expect(expandedId).not.toBeNull()
  await expect(page.getByTestId(`card-details-${expandedId}`)).toHaveAttribute('data-state', 'expanded')
  const expansionAnchorAfter = await stableTopVisibleSnapshot(page)
  expect(expansionAnchorAfter.name).toBe(anchorName)
  expect(Math.abs(expansionAnchorAfter.offset - expansionAnchorBefore.offset)).toBeLessThanOrEqual(2)
  await card.getByRole('button', { name: `将 ${anchorName} 加入 Agent 上下文` }).click()
  if (testInfo.project.name !== 'desktop') {
    agent = page.getByRole('dialog', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(agent).toBeHidden()
  }

  const rollingAnchorBefore = await alignVisibleCardToTop(page)
  await requestBackgroundRefresh(page)
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeVisible({ timeout: 7000 })
  const rollingAnchorAfter = await topVisibleSnapshot(page)
  expect(rollingAnchorAfter.name).toBe(rollingAnchorBefore.name)
  expect(Math.abs(rollingAnchorAfter.offset - rollingAnchorBefore.offset)).toBeLessThanOrEqual(2)
  await page.getByRole('button', { name: '查看 1 条新内容' }).click()
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeHidden()
  await expect.poll(() => feedScroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(96)

  const openAgent = page.getByRole('button', { name: '展开 Agent 面板' })
  if (await openAgent.isVisible()) await openAgent.click()
  agent = testInfo.project.name === 'desktop'
    ? page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    : page.getByRole('dialog', { name: 'OpenClaw 上下文' })
  await expect(agent.getByText('1 / 8', { exact: true })).toBeVisible()
  await agent.getByRole('textbox', { name: '交给 OpenClaw 的问题' }).fill('提炼机会')
  await expect(agent.getByText('使用 OpenClaw 当前设置', { exact: true })).toBeVisible()
  await expect(agent.getByRole('button', { name: /模型偏好/ })).toHaveCount(0)
  await agent.getByRole('button', { name: '复制交接提示词' }).click()
  const handoff = await page.evaluate(() => navigator.clipboard.readText())
  expect(handoff).toContain('[INTELISCOPE_HANDOFF_V6]')
  expect(handoff).toContain('调用 get_item')
  expect(handoff).not.toContain('模型偏好：')

  const horizontalOverflow = await agent.evaluate((element) => {
    const regions = [element, ...element.querySelectorAll<HTMLElement>('*')]
    return regions.flatMap((region) => !region.classList.contains('sr-only') && region.scrollWidth > region.clientWidth ? [{
      testId: region.getAttribute('data-testid') || 'agent-panel',
      tag: region.tagName.toLowerCase(),
      className: region.className,
      clientWidth: region.clientWidth,
      scrollWidth: region.scrollWidth,
    }] : []).slice(0, 20)
  })
  expect(horizontalOverflow).toEqual([])

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('a proven-stale initial deep link returns the real Feed viewport to the newest edge', async ({ page }) => {
  await page.goto('/feed?item=missing')
  await expect(page.getByText(/这条信息已不可用/)).toBeVisible()
  await expect(page).toHaveURL('/feed')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  const offset = await page.getByTestId('workbench-feed-scroll').evaluate((element) => element.scrollTop)
  expect(offset).toBeLessThanOrEqual(96)
})

test('Feed sort changes reset to the top', async ({ page }) => {
  await page.goto('/feed')
  const scroll = page.getByTestId('workbench-feed-scroll')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await scroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })

  await page.getByRole('button', { name: '排序顺序：最新优先' }).click()
  await expect(page.getByRole('button', { name: '排序顺序：最旧优先' })).toBeVisible()
  await expect.poll(() => scroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(96)

  await scroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  await page.getByRole('button', { name: /排序依据：(发布时间|入库时间)/ }).click()
  await expect.poll(() => scroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(96)

  await page.getByRole('button', { name: '排序顺序：最旧优先' }).click()
  await expect(page.getByRole('button', { name: '排序顺序：最新优先' })).toBeVisible()
  await expect.poll(() => scroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(96)
})

test('Changelog entry points expose the responsive month navigation', async ({ page }, testInfo) => {
  if (testInfo.project.name === 'desktop') {
    await page.goto('/feed')
    await page.getByRole('button', { name: '展开侧栏' }).click()
    await page.getByRole('button', { name: '打开文档与发布菜单' }).click()
    await page.getByRole('dialog', { name: '文档与发布菜单' }).getByRole('button', { name: '更新日志' }).click()
  } else if (testInfo.project.name === 'tablet') {
    await page.goto('/feed')
    await page.getByRole('button', { name: '打开账户菜单' }).click()
    await page.getByRole('dialog', { name: '账户菜单' }).getByRole('button', { name: '更新日志' }).click()
  } else {
    await page.goto('/changelog#month-2026-07')
  }

  await expect(page).toHaveURL(/\/changelog(?:#month-2026-07)?$/)
  await expect(page.getByRole('heading', { name: '更新日志', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '2026 年 7 月', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '更清晰的交互反馈' })).toBeVisible()
  if (testInfo.project.name === 'desktop') {
    await expect(page.getByRole('navigation', { name: '更新月份时间线', exact: true })).toBeVisible()
    await expect(page.getByRole('navigation', { name: '更新月份', exact: true })).toBeHidden()
  } else {
    await expect(page.getByRole('navigation', { name: '更新月份', exact: true })).toBeVisible()
    await expect(page.getByRole('navigation', { name: '更新月份时间线', exact: true })).toBeHidden()
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('the production theme defaults to night and persists explicit day and night choices', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'A single desktop browser covers the shared theme root.')
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/changelog')
  const root = page.locator('html')
  const app = page.locator('[data-ui-system="heroui"]')
  await expect(root).toHaveAttribute('data-theme', 'dark')
  await expect(app).toHaveAttribute('data-theme', 'dark')
  const darkBackground = await app.evaluate((element) => getComputedStyle(element).backgroundColor)

  await page.getByRole('button', { name: '切换到白天模式' }).click()
  await expect(root).toHaveAttribute('data-theme', 'light')
  await expect(app).toHaveAttribute('data-theme', 'light')
  expect(await app.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(darkBackground)
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(root).toHaveAttribute('data-theme', 'light')
  await expect(app).toHaveAttribute('data-theme', 'light')

  await page.reload()
  await expect(root).toHaveAttribute('data-theme', 'light')
  await expect(app).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: '切换到黑夜模式' }).click()
  await expect(root).toHaveAttribute('data-theme', 'dark')
  await expect(app).toHaveAttribute('data-theme', 'dark')
})

test('Insights shifts the reading column before overlap and only obstructing layouts softly exit', async ({ page }, testInfo) => {
  test.setTimeout(60_000)
  test.skip(testInfo.project.name !== 'desktop', 'The floating surface geometry is exercised from the desktop project.')
  await page.goto('/feed')
  const shell = page.getByTestId('live-workbench-shell')
  const main = page.locator('main[data-feed-reading-layout="true"]')
  const reading = main.locator('[data-page-frame="reading"]')
  const scroll = page.getByTestId('workbench-feed-scroll')
  const centeredReading = await reading.boundingBox()
  await scroll.evaluate((element) => {
    element.scrollTop = 480
    element.dispatchEvent(new Event('scroll'))
  })
  const scrollTop = await scroll.evaluate((element) => element.scrollTop)

  await page.getByRole('button', { name: '展开信息概览' }).click()
  const insights = page.locator('#feed-insights-surface')
  await expect(insights).toBeVisible()
  await expect(shell).toHaveAttribute('data-insights-obstructs-feed', 'false')
  await reading.evaluate(async (element) => Promise.all(
    element.getAnimations().map((animation) => animation.finished.catch(() => undefined)),
  ))
  await insights.evaluate(async (element) => Promise.all(
    element.getAnimations().map((animation) => animation.finished.catch(() => undefined)),
  ))
  const mainBounds = await main.boundingBox()
  const shiftedReading = await reading.boundingBox()
  const insightsBounds = await insights.boundingBox()
  expect(centeredReading).not.toBeNull()
  expect(mainBounds).not.toBeNull()
  expect(shiftedReading).not.toBeNull()
  expect(insightsBounds).not.toBeNull()
  expect(shiftedReading!.x).toBeLessThan(centeredReading!.x)
  expect(shiftedReading!.x).toBeGreaterThanOrEqual(mainBounds!.x + 11)
  expect(insightsBounds!.x - (shiftedReading!.x + shiftedReading!.width)).toBeGreaterThanOrEqual(11)
  expect(Math.abs((insightsBounds!.x + insightsBounds!.width) - (mainBounds!.x + mainBounds!.width - 12))).toBeLessThanOrEqual(1)
  expect(await scroll.evaluate((element) => element.scrollTop)).toBe(scrollTop)

  await page.getByRole('heading', { name: '信息流' }).click()
  await expect(insights).toBeVisible()
  await page.getByRole('button', { name: '关闭信息概览' }).click()
  await expect(insights).toHaveCount(0)

  await page.setViewportSize({ width: 1280, height: 800 })
  await page.getByRole('button', { name: '展开 Agent 面板' }).click()
  const dockedAgent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
  await expect(dockedAgent).toBeVisible()
  await page.getByRole('button', { name: '展开信息概览' }).click()
  const manualInsights = page.locator('#feed-insights-surface')
  await expect(manualInsights).toBeVisible()
  await expect(shell).toHaveAttribute('data-insights-obstructs-feed', 'true')
  await page.getByRole('button', { name: /切换到(白天|黑夜)模式/ }).click()
  await expect(manualInsights).toBeVisible()
  await page.getByRole('heading', { name: '信息流' }).click()
  await expect(manualInsights).toHaveAttribute('aria-hidden', 'true')
  await expect(manualInsights).toHaveCount(0)
  await page.getByRole('button', { name: '收起 Agent 面板' }).click()
  await expect(dockedAgent).toHaveCount(0)

  await page.setViewportSize({ width: 1024, height: 768 })
  await page.getByRole('button', { name: '展开信息概览' }).click()
  const narrowInsights = page.locator('#feed-insights-surface')
  await expect(narrowInsights).toBeVisible()
  await expect(shell).toHaveAttribute('data-insights-obstructs-feed', 'true')
  await reading.evaluate(async (element) => Promise.all(
    element.getAnimations().map((animation) => animation.finished.catch(() => undefined)),
  ))
  await narrowInsights.evaluate(async (element) => Promise.all(
    element.getAnimations().map((animation) => animation.finished.catch(() => undefined)),
  ))
  const narrowMainBounds = await main.boundingBox()
  const narrowReadingBounds = await reading.boundingBox()
  const narrowInsightsBounds = await narrowInsights.boundingBox()
  expect(narrowMainBounds).not.toBeNull()
  expect(narrowReadingBounds).not.toBeNull()
  expect(narrowInsightsBounds).not.toBeNull()
  expect(Math.abs(narrowReadingBounds!.x - (narrowMainBounds!.x + 12))).toBeLessThanOrEqual(1)
  expect(narrowReadingBounds!.x + narrowReadingBounds!.width).toBeGreaterThan(narrowInsightsBounds!.x)
  expect(Math.abs((narrowInsightsBounds!.x + narrowInsightsBounds!.width) - (narrowMainBounds!.x + narrowMainBounds!.width - 12))).toBeLessThanOrEqual(1)

  await page.getByRole('button', { name: /切换到(白天|黑夜)模式/ }).click()
  await expect(narrowInsights).toBeVisible()
  await page.getByRole('button', { name: '展开 Agent 面板' }).click()
  await expect(narrowInsights).toHaveCount(0)
  const agent = page.getByRole('dialog', { name: 'OpenClaw 上下文' })
  await expect(agent).toBeVisible()
  await agent.getByRole('button', { name: '关闭 Agent 面板' }).click()
  await expect(agent).toBeHidden()

  await page.getByRole('button', { name: '展开信息概览' }).click()
  const closingInsights = page.locator('#feed-insights-surface')
  await expect(closingInsights).toBeVisible()
  await page.getByRole('heading', { name: '信息流' }).click()
  await expect(closingInsights).toHaveAttribute('aria-hidden', 'true')
  expect(await closingInsights.evaluate((element) => element.inert)).toBe(true)
  await expect(closingInsights).toHaveCount(0)

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: '展开信息概览' }).click()
  const reducedMotionInsights = page.locator('#feed-insights-surface')
  await expect(reducedMotionInsights).toBeVisible()
  await page.getByRole('heading', { name: '信息流' }).click()
  await expect(reducedMotionInsights).toHaveCount(0)
})

test('social cards and Agent context show source information once without exposing item IDs', async ({ page }, testInfo) => {
  await page.goto('/feed?social=1')
  const card = page.getByTestId('workbench-card')
  const source = card.getByLabel('来源信息')

  await expect(card).toBeVisible()
  await expect(source.getByText('Tibo', { exact: true })).toBeVisible()
  await expect(source.getByText('@thsottiaux', { exact: true })).toBeVisible()
  await expect(page.getByText('Oops... I did it again. Enjoy reset usage limits for all paid users.', { exact: true })).toHaveCount(1)
  await expect(page.getByText(socialRouteItem.title, { exact: true })).toHaveCount(0)
  await expect(card.getByText('图集', { exact: true })).toBeVisible()
  await expect(card.getByText('图片 2/4', { exact: true })).toBeVisible()
  const expand = card.getByRole('button', { name: /展开 / })
  await expand.hover()
  await expect(page.getByText('展开内容', { exact: true })).toBeVisible()
  await page.mouse.move(4, 4)
  await card.locator('[data-card-expand-zone="true"]').click()
  await expect(card.getByRole('button', { name: /收起 / })).toHaveAttribute('aria-expanded', 'true')
  const mediaPreview = card.getByLabel('图片预览，共 2 张可查看图片')
  const firstImage = mediaPreview.getByRole('button', { name: '打开图片预览，从第 1 张开始，可查看 2 张，共 4 张' })
  await expect(mediaPreview.getByRole('img')).toHaveCount(1)
  await expect(firstImage).toBeVisible()
  expect(await mediaPreview.getByRole('img').evaluate((image) => getComputedStyle(image).objectFit)).toBe('contain')
  const thumbnailBounds = await firstImage.boundingBox()
  expect(thumbnailBounds).not.toBeNull()
  expect(thumbnailBounds!.width).toBeLessThanOrEqual(513)
  expect(Math.abs((thumbnailBounds!.width / thumbnailBounds!.height) - (4 / 3))).toBeLessThan(0.02)
  await expect(card.getByText('仅获取到内容片段，打开原文查看完整内容。', { exact: true })).toBeVisible()

  const routeBeforePreview = page.url()
  await firstImage.click()
  const preview = page.getByRole('dialog', { name: /图片预览$/ })
  await expect(preview).toBeVisible()
  await expect(preview.getByRole('status')).toHaveText('1 / 2')
  const stage = preview.getByTestId('media-viewer-stage')
  const previewImage = preview.getByTestId('media-viewer-image')
  await expect(stage).toBeVisible()
  await expect(previewImage).toBeVisible()
  expect(await previewImage.evaluate((image) => ({
    naturalWidth: (image as HTMLImageElement).naturalWidth,
    naturalHeight: (image as HTMLImageElement).naturalHeight,
    objectFit: getComputedStyle(image).objectFit,
  }))).toEqual({ naturalWidth: 2046, naturalHeight: 2728, objectFit: 'contain' })
  await expectLocatorInside(previewImage, stage)
  await expectLocatorInside(stage, preview)
  const previewBounds = await preview.boundingBox()
  const viewport = page.viewportSize()
  expect(previewBounds).not.toBeNull()
  expect(viewport).not.toBeNull()
  expect(previewBounds!.x).toBeGreaterThanOrEqual(0)
  expect(previewBounds!.y).toBeGreaterThanOrEqual(0)
  expect(previewBounds!.x + previewBounds!.width).toBeLessThanOrEqual(viewport!.width)
  expect(previewBounds!.y + previewBounds!.height).toBeLessThanOrEqual(viewport!.height)
  for (const name of ['关闭图片预览', '上一张图片', '下一张图片']) {
    const bounds = await preview.getByRole('button', { name }).boundingBox()
    expect(bounds?.width ?? 0).toBeGreaterThanOrEqual(44)
    expect(bounds?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  const thumbnailGroup = preview.getByRole('group', { name: '图片缩略图' })
  await expect(thumbnailGroup.getByRole('button')).toHaveCount(2)
  await thumbnailGroup.getByRole('button', { name: '切换到第 2 张图片' }).click()
  await expect(preview.getByRole('status')).toHaveText('2 / 2')
  await expect(preview.getByRole('img', { name: '社交图片二' })).toBeVisible()
  expect(await previewImage.evaluate((image) => ({
    naturalWidth: (image as HTMLImageElement).naturalWidth,
    naturalHeight: (image as HTMLImageElement).naturalHeight,
  }))).toEqual({ naturalWidth: 1600, naturalHeight: 900 })
  await expectLocatorInside(previewImage, stage)
  await preview.press('ArrowLeft')
  await expect(preview.getByRole('status')).toHaveText('1 / 2')
  await preview.press('ArrowRight')
  await expect(preview.getByRole('status')).toHaveText('2 / 2')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  await preview.press('Escape')
  await expect(preview).toHaveCount(0)
  await expect(firstImage).toBeFocused()
  expect(page.url()).toBe(routeBeforePreview)

  await card.getByRole('button', { name: /加入 Agent 上下文/ }).click()
  await expect(card.getByRole('button', { name: /收起 / })).toHaveAttribute('aria-expanded', 'true')
  const agent = testInfo.project.name === 'desktop'
    ? page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    : page.getByRole('dialog', { name: 'OpenClaw 上下文' })
  await expect(agent).toBeVisible()
  await expect(agent.getByText('Tibo', { exact: true })).toBeVisible()
  await expect(agent.getByText('@thsottiaux', { exact: true })).toBeVisible()
  await expect(agent.getByText('Oops... I did it again. Enjoy reset usage limits for all paid users.', { exact: true })).toBeVisible()
  await expect(page.getByText(socialRouteItem.id, { exact: true })).toHaveCount(0)
})

test('a filtered unread-first Feed restores an unmounted anchor with the rendered card index', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('inteliscope.ui.feed.v2:e2e-user', JSON.stringify({
    unreadFirst: true,
    source: 'GitHub',
    channel: '',
    topic: '',
  })))
  await page.goto('/feed?batch=1')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await expect(page.getByRole('button', { name: '筛选信息流，已启用 2 项' })).toBeVisible()
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) * 0.1)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)

  // Sample and start the background task in one browser task so a later Virtualizer measurement cannot make
  // the expected anchor older than the request-time geometry captured by the application.
  const anchorBefore = await feedScroll.evaluate((scroll) => {
    const bounds = scroll.getBoundingClientRect()
    const top = Array.from(scroll.querySelectorAll<HTMLElement>('[data-testid="workbench-card"]'))
      .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
      .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
    const anchor = {
      name: top?.getAttribute('aria-label') ?? '',
      offset: top ? top.getBoundingClientRect().top - bounds.top : 0,
    }
    document.querySelector<HTMLButtonElement>('button[aria-label="获取新内容"]')?.click()
    return anchor
  })
  expect(anchorBefore.name).not.toBe('')
  await expect(page.getByRole('button', { name: '获取新内容' })).toBeDisabled()
  await page.evaluate(() => (window as typeof window & {
    completeBackgroundRefresh: () => Promise<void>
  }).completeBackgroundRefresh())
  await expect(page.getByRole('button', { name: '查看 80 条新内容' })).toBeVisible({ timeout: 7000 })
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorBefore.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorBefore.offset)).toBeLessThanOrEqual(2)

})

test('live unread-first and source filters preserve the surviving rendered-card anchor', async ({ page }) => {
  await page.goto('/feed')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)

  await page.getByRole('button', { name: '筛选信息流' }).click()
  const filterDialog = page.getByRole('dialog', { name: '信息流筛选' })
  await expect(filterDialog).toBeVisible()
  await expect(filterDialog.getByRole('button', { name: /来源/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(filterDialog).toBeHidden()
  await expect(page.getByRole('button', { name: '筛选信息流' })).toBeFocused()
  await page.getByRole('button', { name: '筛选信息流' }).click()
  await expect(filterDialog).toBeVisible()
  await page.mouse.click(4, 100)
  await expect(filterDialog).toBeHidden()
  await expect(page.getByRole('button', { name: '筛选信息流' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(filterDialog).toBeVisible()
  const anchorAtTransition = await alignVisibleCardToTop(page)
  const itemNumber = Number(anchorAtTransition.name.match(/\d+/)?.[0])
  const survivingSource = itemNumber % 2 === 1 ? 'GitHub' : 'OpenAI Blog'
  await filterDialog.getByText('未读优先', { exact: true }).click()
  await expect(page.getByText('未读优先', { exact: true }).first()).toBeVisible()
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorAtTransition.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorAtTransition.offset)).toBeLessThanOrEqual(2)

  const sourceSelect = filterDialog.getByRole('button', { name: /来源/ })
  await sourceSelect.click()
  await page.getByRole('option', { name: survivingSource }).click()
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorAtTransition.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorAtTransition.offset)).toBeLessThanOrEqual(2)
})

test('Quiet Studio honors Reduced Motion without losing state', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/feed')
  const card = page.getByRole('article', { name: '实时条目 200' })
  await card.getByRole('button', { name: '展开 实时条目 200' }).click()
  const id = await card.locator('xpath=..').getAttribute('data-item-id')
  expect(id).not.toBeNull()
  const details = page.getByTestId(`card-details-${id}`)
  await expect(details).toHaveAttribute('data-state', 'expanded')
  const durations = await details.evaluate((element) => getComputedStyle(element).transitionDuration
    .split(',')
    .map((value) => Number.parseFloat(value)))
  expect(durations.every((seconds) => seconds <= 0.001)).toBe(true)
})

test('Quiet Studio keeps keyboard expansion and mobile action targets accessible', async ({ page }, testInfo) => {
  await page.goto('/feed')
  const card = page.getByRole('article', { name: '实时条目 200' })
  const expand = card.getByRole('button', { name: '展开 实时条目 200' })
  await expand.focus()
  await page.keyboard.press('Enter')
  await expect(card.getByRole('button', { name: '收起 实时条目 200' })).toHaveAttribute('aria-expanded', 'true')

  if (testInfo.project.name === 'mobile') {
    const openOriginal = card.getByRole('link', { name: '打开 实时条目 200 原文' })
    const box = await openOriginal.boundingBox()
    expect(Math.round(box?.width ?? 0)).toBeGreaterThanOrEqual(44)
    expect(Math.round(box?.height ?? 0)).toBeGreaterThanOrEqual(44)
  }
})

test('saved, history and legacy later are accepted by the production workbench routes', async ({ page }) => {
  await page.goto('/saved')
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: savedRouteItem.title })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
  await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
  await expect(page.locator('[data-card-visual="quiet-studio"]')).toHaveCount(1)
  await expect(page.getByRole('banner')).toHaveAttribute('data-header-visual', 'quiet-studio')
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '排序顺序：最新优先' })).toBeVisible()
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '重新载入信息流数据' })).toHaveCount(0)
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '获取新内容' })).toHaveCount(0)
  await expect(page.getByRole('article', { name: savedRouteItem.title }).getByText('文章', { exact: true })).toBeVisible()
  await expect(page.locator('[data-loading-reveal="feed"]')).toHaveAttribute('data-loading-state', 'ready')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  await page.goto('/history')
  await expect(page.getByRole('heading', { name: '历史', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: historyRouteItem.title })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
  await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
  await expect(page.locator('[data-card-visual="quiet-studio"]')).toHaveCount(1)
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '排序顺序：最新优先' })).toBeVisible()
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '重新载入信息流数据' })).toHaveCount(0)
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '获取新内容' })).toHaveCount(0)
  await expect(page.getByRole('article', { name: historyRouteItem.title }).getByText('文章', { exact: true })).toBeVisible()
  await expect(page.locator('[data-loading-reveal="feed"]')).toHaveAttribute('data-loading-state', 'ready')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  await page.goto('/later?mode=featured&item=saved-route-item')
  await expect(page).toHaveURL('/saved?item=saved-route-item')
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: savedRouteItem.title })).toBeVisible()
})

test('durable source history paginates without mobile overflow at 645 and 320 pixels', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One browser project resizes through the two additional acceptance widths.')

  for (const width of [645, 320]) {
    await page.setViewportSize({ width, height: width === 645 ? 762 : 700 })
    const query = `tsucha-${width}`
    const firstRequest = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return url.pathname === '/api/feed/history' && url.searchParams.get('offset') === '0'
    })
    await page.goto(`/history?source_id=source-tsucha&q=${query}`)
    const requestUrl = new URL((await firstRequest).url())
    expect(requestUrl.searchParams.get('source_id')).toBe('source-tsucha')
    expect(requestUrl.searchParams.get('q')).toBe(query)
    expect(requestUrl.searchParams.get('limit')).toBe('50')

    await expect(page.getByText('2 条内容', { exact: true })).toBeVisible()
    await expect(page.getByText('来源：tsucha_ri', { exact: true })).toBeVisible()
    await expect(page.getByRole('article', { name: tsuchaHistoryItems[0].title })).toBeVisible()
    await expect(page.getByRole('article', { name: tsuchaHistoryItems[1].title })).toHaveCount(0)

    const nextRequest = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return url.pathname === '/api/feed/history' && url.searchParams.get('offset') === '1'
    })
    await page.getByRole('button', { name: /加载更多/ }).click()
    await nextRequest
    await expect(page.getByRole('article', { name: tsuchaHistoryItems[1].title })).toBeVisible()
    await expect(page.getByRole('button', { name: /加载更多/ })).toHaveCount(0)

    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    const accessibility = await new AxeBuilder({ page }).analyze()
    expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  }
})

test('content-route navigation keeps the same shell and a closed Agent panel', async ({ page }, testInfo) => {
  await page.goto('/feed')
  const shell = page.getByTestId('live-workbench-shell')
  await shell.evaluate((element) => {
    ;(window as typeof window & { workbenchShellProbe?: Element }).workbenchShellProbe = element
    element.setAttribute('data-lifecycle-probe', 'persistent-shell')
  })

  const closeAgent = page.getByRole('button', { name: '收起 Agent 面板' })
  if (await closeAgent.isVisible()) await closeAgent.click()
  await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()

  await page.getByRole('link', { name: '收藏', exact: true }).click()
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
  expect(await page.evaluate(() => (window as typeof window & { workbenchShellProbe?: Element }).workbenchShellProbe === document.querySelector('[data-testid="live-workbench-shell"]'))).toBe(true)

  if (testInfo.project.name === 'mobile') {
    await page.getByRole('button', { name: '更多与账户' }).click()
    await page.getByRole('dialog', { name: '更多与账户' }).getByRole('button', { name: '历史', exact: true }).click()
  } else {
    await page.getByRole('link', { name: '历史', exact: true }).click()
  }
  await expect(page.getByRole('heading', { name: '历史', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
  await expect(shell).toHaveAttribute('data-lifecycle-probe', 'persistent-shell')
  expect(await page.evaluate(() => (window as typeof window & { workbenchShellProbe?: Element }).workbenchShellProbe === document.querySelector('[data-testid="live-workbench-shell"]'))).toBe(true)
})
