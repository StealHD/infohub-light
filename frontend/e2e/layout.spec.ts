import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const now = Date.parse('2026-07-14T12:00:00Z')
const firstPublishedAt = new Date(now - 18 * 60_000).toISOString()
const state = (overrides: Partial<{ is_read: boolean; is_saved: boolean; is_later: boolean; dismissed: boolean }> = {}) => ({
  is_read: false, is_saved: false, is_later: false, dismissed: false, ...overrides,
})

const feedItems = [
  {
    id: 'article-1', title: 'Codex 推出新的协作工作流', url: 'https://example.com/codex', source: 'OpenAI Blog', source_type: 'rss', source_id: 'src-1',
    subscription_ids: ['sub-1'], summary_zh: '更清晰的任务分解与上下文协作，让复杂开发流程更容易持续推进。',
    score: 9.2, channel: 'AI', signal_type: '产品更新', topics: ['Codex'],
    published_at: firstPublishedAt, user_state: state(),
    presentation: {
      version: 1,
      source: { id: 'src-1', catalog_type: 'rss', platform: 'rss', name: 'OpenAI Blog' },
      author: { name: 'OpenAI', kind: 'organization' },
      timing: { published_at: firstPublishedAt, fetched_at: new Date(now).toISOString() },
      links: { canonical_url: 'https://example.com/codex', source_url: 'https://community.example.com/codex' },
      content: { title: 'Codex 推出新的协作工作流', title_origin: 'native', excerpt: 'OpenAI 发布 Codex 协作工作流更新，重点改善复杂任务的分解、上下文衔接与持续执行。', content_kind: 'feed_summary', excerpt_truncated: false },
      taxonomy: { channel: 'AI', configured_topics: ['Codex'], inferred_topics: ['协作工作流'], topics: ['Codex', '协作工作流'], entities: ['OpenAI', 'Codex'] },
      engagement: { native_score: null, likes: 128, comments: 24, reposts: null, shares: 18, upvote_ratio: null },
      analysis: { status: 'ai', score: 9.2, signal_strength: 'strong', signal_type: '产品更新', summary_zh: '更清晰的任务分解与上下文协作，让复杂开发流程更容易持续推进。' },
    },
  },
  {
    id: 'article-2', title: '模型上下文协议进入企业协作工具链', url: 'https://example.com/mcp', source: 'Protocol Watch', source_type: 'rss', source_id: 'src-2',
    subscription_ids: ['sub-2'], score: 8.7,
    channel: '工程', signal_type: '标准演进', topics: ['MCP'], published_at: new Date(now - 42 * 60_000).toISOString(), user_state: state({ is_read: true }),
  },
  {
    id: 'article-3', title: '一个没有评分与分类的来源条目', url: '', source: 'Field Notes', source_type: 'manual', source_id: 'src-3',
    subscription_ids: ['sub-3'], summary_zh: '保留原始事实，但当前没有完整的分类和评分。', published_at: new Date(now - 75 * 60_000).toISOString(), user_state: state(),
  },
  {
    id: 'article-4', title: '欧洲企业软件采购正在重新评估 AI 代理', url: 'https://example.com/market', source: 'Market Radar', source_id: 'src-4',
    subscription_ids: ['sub-4'], summary_zh: '采购团队把可审计性和权限隔离放到评估清单前列。',
    score: 8.3, channel: '市场', signal_type: '需求变化', topics: ['企业软件'],
    published_at: new Date(now - 2 * 60 * 60_000).toISOString(), user_state: state({ is_saved: true }),
  },
  {
    id: 'article-5', title: '数据库团队开始为代理工作流设计最小权限接口', url: 'https://example.com/database', source: 'Infra Brief', source_id: 'src-5',
    subscription_ids: ['sub-5'], summary_zh: '新的接口把读、写和审批能力拆分为独立授权。', score: 7.9,
    channel: '基础设施', signal_type: '架构实践', topics: ['数据库'], published_at: new Date(now - 3 * 60 * 60_000).toISOString(), user_state: state(),
  },
  {
    id: 'article-6', title: '团队周报：本周值得继续跟进的三个产品信号', url: 'https://example.com/weekly', source: 'Internal Digest', source_id: 'src-6',
    subscription_ids: ['sub-6'], summary_zh: '聚焦代理协作、企业治理和本地推理三条主线。',
    score: 7.5, channel: '内部', signal_type: '日报', topics: ['周报'], published_at: new Date(now - 5 * 60 * 60_000).toISOString(), user_state: state({ is_later: true }),
  },
  {
    id: 'article-7', title: '未启用评分的个人订阅更新', url: 'https://example.com/personal', source: 'Personal Stream', source_id: 'src-7',
    subscription_ids: ['sub-7'], summary_zh: '该来源按无评分模式保留，供用户自主判断。', scoring_disabled: true, channel: '个人', signal_type: '订阅更新',
    topics: ['个人订阅'], published_at: new Date(now - 7 * 60 * 60_000).toISOString(), user_state: state({ is_read: true }),
  },
  {
    id: 'article-8', title: '一条用于验证桌面阅读密度和长中文标题换行行为的超长情报标题：从产品策略到交付节奏的连续变化', url: 'https://example.com/long',
    source: 'Longform Intelligence', source_id: 'src-8', subscription_ids: ['sub-8'], summary_zh: '长标题必须保持可扫描性，同时不能挤压信号强度与来源信息。',
    score: 6.8, channel: '设计', signal_type: '回归样本',
    topics: ['UI'], published_at: new Date(now - 10 * 60 * 60_000).toISOString(), user_state: state(),
  },
]

async function mockApi(page: Page) {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url())
    let data: unknown = {}
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'user-1', username: 'owner', display_name: 'Owner', role: 'owner', enabled: true } }
    else if (url.pathname === '/api/feed/latest') data = { schema_version: 2, items: feedItems, featured_items: feedItems, daily_push_items: feedItems.slice(0, 4), generated_at: '2026-07-14T08:10:00Z' }
    else if (url.pathname === '/api/me/source-health') data = {
      schema_version: 1, scope: 'user', summary: { total: 8, healthy: 4, degraded: 1, failing: 1, unknown: 2 },
      items: [
        { subscription_id: 'sub-1', source_id: 'src-1', status: 'healthy', consecutive_failures: 0 },
        { subscription_id: 'sub-2', source_id: 'src-2', status: 'degraded', consecutive_failures: 1 },
        { subscription_id: 'sub-3', source_id: 'src-3', status: 'failing', consecutive_failures: 4 },
      ],
    }
    else if (url.pathname === '/api/feed/history') data = { schema_version: 2, scope: 'user', items: feedItems, featured_items: feedItems, item_count: feedItems.length, snapshots: [] }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: 'https://rb.jiefs.top/mcp',
      token_ttl_days: 90,
      max_active: 5,
      connections: [{
        id: 'agent-1', name: 'Local OpenClaw', client_type: 'openclaw', scopes: ['inteliscope:read'],
        token_prefix: 'ih_mcp_v1_example', created_at: '2026-07-16T00:00:00Z',
        expires_at: '2026-10-14T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active',
      }],
    }
    else if (url.pathname === '/api/jobs') data = { jobs: [] }
    else if (/^\/api\/me\/items\/[^/]+\/state$/.test(url.pathname)) data = state({ is_saved: true })
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
}

async function waitForStableUi(page: Page) {
  await expect(page.getByText('Inteliscope')).toBeVisible()
  await expect(page.getByRole('heading', { name: '今日信息流' })).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(now))
  page.on('pageerror', (error) => { throw error })
  await mockApi(page)
})

test('responsive feed has no overflow and no serious accessibility violations', async ({ page }, testInfo) => {
  await page.goto('/feed?mode=featured')
  await waitForStableUi(page)

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  if (testInfo.project.name !== 'mobile') {
    const toggleBounds = await page.getByRole('button', { name: '展开侧栏' }).boundingBox()
    expect(toggleBounds?.height).toBeLessThanOrEqual(56)
  }

  if (testInfo.project.name === 'desktop') {
    const storyScroller = page.getByTestId('feed-story-scroll')
    const fullyVisibleStories = await page.getByTestId('feed-story').evaluateAll((stories, scroller) => {
      const bounds = (scroller as HTMLElement).getBoundingClientRect()
      return stories.filter((story) => {
        const rect = story.getBoundingClientRect()
        return rect.top >= bounds.top && rect.bottom <= bounds.bottom
      }).length
    }, await storyScroller.elementHandle())
    expect(fullyVisibleStories).toBeGreaterThanOrEqual(6)
    const reader = page.getByRole('region', { name: '阅读详情' })
    await expect(reader.getByText(feedItems[0].summary_zh, { exact: true })).toHaveCount(1)
    await expect(page).toHaveScreenshot('feed-1440-collapsed.png', { animations: 'disabled' })
  } else if (testInfo.project.name === 'tablet') {
    await page.getByRole('button', { name: '展开侧栏' }).click()
    await expect(page.locator('.sidebar-overlay')).toBeVisible()
    await expect(page).toHaveScreenshot('feed-1024-overlay.png', { animations: 'disabled' })
  } else {
    const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
    await expect(mobileNavigation).toBeVisible()
    await expect(mobileNavigation.getByRole('link', { name: '收藏' })).toBeVisible()
    await expect(mobileNavigation.getByRole('link', { name: '设置' })).toBeVisible()
    expect(await mobileNavigation.getByRole('link').evaluateAll((links) => links.every((link) => {
      const bounds = link.getBoundingClientRect()
      return bounds.width >= 44 && bounds.height >= 44
    }))).toBe(true)
    await expect(page).toHaveScreenshot('feed-390-mobile.png', { animations: 'disabled' })
  }
})

test('assistant connection deep link is accessible and never probes a local agent', async ({ page }, testInfo) => {
  const forbiddenRequests: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.port === '18789' || url.pathname === '/mcp' || url.protocol === 'ws:' || url.protocol === 'wss:') {
      forbiddenRequests.push(request.url())
    }
  })

  await page.goto('/agents')
  await expect(page.getByRole('heading', { name: '助手连接' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Local OpenClaw' })).toBeVisible()
  await expect(page.getByText(/^从未使用/)).toBeVisible()
  await expect(page.getByTestId('openclaw-config-page')).toContainText('${INTELISCOPE_MCP_TOKEN}')
  await expect(page.locator('body')).not.toContainText('ih_mcp_v1_one_time')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  expect(forbiddenRequests).toEqual([])

  if (testInfo.project.name === 'mobile') {
    await expect(page.getByRole('navigation', { name: '移动端主导航' }).getByRole('link')).toHaveCount(6)
  }
})

test('desktop expansion preserves route, selection and list scroll', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop-only interaction')
  await page.goto('/feed?mode=featured&item=article-1')
  await waitForStableUi(page)
  const scroller = page.getByTestId('feed-story-scroll')
  await scroller.evaluate((element) => { element.scrollTop = 80 })
  const scrollBefore = await scroller.evaluate((element) => element.scrollTop)

  await page.getByRole('button', { name: '展开侧栏' }).click()
  await expect(page.getByRole('button', { name: '收起侧栏' })).toBeVisible()
  expect(await scroller.evaluate((element) => element.scrollTop)).toBe(scrollBefore)
  await expect(page).toHaveURL(/mode=featured&item=article-1/)
  expect(await page.evaluate(() => localStorage.getItem('inteliscope.ui.sidebar.v1:user-1'))).toBe('expanded')

  await page.reload()
  await waitForStableUi(page)
  await expect(page.getByRole('button', { name: '收起侧栏' })).toBeVisible()
  await expect(page).toHaveURL(/item=article-1/)
  await expect.poll(() => page.locator('.sidebar-permanent').evaluate((element) => element.getBoundingClientRect().width)).toBe(240)
  await expect(page).toHaveScreenshot('feed-1440-expanded.png', { animations: 'disabled' })
})

test('filter popover is keyboard operable and restores focus', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'desktop and tablet filter behavior')
  await page.goto('/feed?mode=featured')
  await waitForStableUi(page)

  await page.getByRole('tab', { name: '全部' }).click()
  await expect(page).toHaveURL(/mode=all/)

  const trigger = page.getByRole('button', { name: '更多筛选' })
  await trigger.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: '筛选信息流' })).toBeVisible()
  await page.getByRole('combobox', { name: '频道筛选' }).click()
  await page.getByRole('option', { name: 'AI' }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '筛选信息流' })).toBeHidden()
  await expect(trigger).toBeFocused()
  await expect(page.getByRole('button', { name: '频道：AI' })).toBeVisible()
})

test('mobile opens detail and returns without losing navigation', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'mobile-only interaction')
  await page.goto('/feed?mode=featured')
  await waitForStableUi(page)
  await page.getByTestId('feed-story').first().click()
  await expect(page.getByRole('heading', { name: 'Codex 推出新的协作工作流' })).toBeVisible()
  await page.getByRole('button', { name: '返回列表' }).click()
  await expect(page.getByRole('heading', { name: '今日信息流' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '移动端主导航' })).toBeVisible()
})

test('reduced motion removes long animations and transitions', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/feed?mode=featured')
  await waitForStableUi(page)
  const target = testInfo.project.name === 'mobile' ? page.getByTestId('feed-story').first() : page.getByRole('button', { name: '展开侧栏' })
  const duration = await target.evaluate((element) => getComputedStyle(element).transitionDuration)
  expect(duration).toMatch(/1e-05s|0(?:\.0+)?1ms|0s/)
})
