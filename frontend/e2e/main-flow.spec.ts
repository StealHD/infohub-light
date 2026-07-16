import { expect, test, type Page } from '@playwright/test'

const owner = { id: 'user-1', username: 'owner', display_name: 'Owner', role: 'owner', enabled: true }
const item = {
  id: 'article-1', title: 'Codex 推出新的协作工作流', url: 'https://example.com/codex', source: 'OpenAI Blog', source_id: 'src-1', source_type: 'rss',
  subscription_ids: ['sub-1'], summary_zh: '更清晰的任务分解与上下文协作，让复杂开发流程更容易持续推进。',
  score: 9.2, channel: 'AI', topics: ['Codex'],
  published_at: '2026-07-13T08:00:00Z', user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
}

const presentation = {
  version: 2,
  source: { id: 'src-1', catalog_type: 'rss', platform: 'rss', name: 'OpenAI Blog', avatar_url: '' },
  author: { name: 'OpenAI', kind: 'organization' },
  timing: { published_at: item.published_at, fetched_at: item.published_at },
  links: { canonical_url: item.url, source_url: item.url },
  content: {
    title: item.title,
    title_origin: 'native',
    excerpt: item.summary_zh,
    content_kind: 'feed_summary',
    excerpt_truncated: false,
    body_text: '这是 Worker 已抓取并清理后的正文内容。',
    body_truncated: false,
    body_completeness: 'captured',
  },
  media: { images: [], count: 0 },
  taxonomy: { channel: 'AI', configured_topics: ['Codex'], inferred_topics: [], topics: ['Codex'], entities: ['OpenAI'] },
  engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
  analysis: { status: 'ai', score: 9.2, signal_strength: 'strong', signal_type: '产品更新', summary_zh: item.summary_zh },
}

async function mockMainFlow(page: Page) {
  let authenticated = false
  let refreshCreated = false
  let jobReads = 0
  let statePatchCalls = 0
  const state = { ...item.user_state }

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    let data: unknown = {}
    if (url.pathname === '/api/auth/status') data = { authenticated, user: authenticated ? owner : null }
    else if (url.pathname === '/api/auth/login') { authenticated = true; data = { authenticated: true, user: owner } }
    else if (url.pathname === '/api/feed/latest') data = { schema_version: 2, items: [{ ...item, user_state: state }], featured_items: [{ ...item, user_state: state }], daily_push_items: [], generated_at: '2026-07-13T08:10:00Z' }
    else if (url.pathname === '/api/feed/saved') data = { schema_version: 1, scope: 'user', items: state.is_saved ? [{ ...item, user_state: state }] : [], item_count: state.is_saved ? 1 : 0, limit: 200, offset: 0 }
    else if (url.pathname === '/api/feed/items/article-1') data = { ...item, user_state: state, presentation }
    else if (url.pathname === '/api/feed/history') data = { schema_version: 2, scope: 'user', items: [{ ...item, id: 'history-1', title: '历史中的模型更新', user_state: state }], featured_items: [], item_count: 1, snapshots: [] }
    else if (url.pathname === '/api/me/source-health') data = { schema_version: 1, scope: 'user', summary: { total: 1, healthy: 1, degraded: 0, failing: 0, unknown: 0 }, items: [{ subscription_id: 'sub-1', source_id: 'src-1', source_display_name: 'OpenAI Blog', source_type: 'rss', status: 'healthy', consecutive_failures: 0 }] }
    else if (url.pathname === '/api/me/feed-schedule') data = { schema_version: 1, enabled: true, interval_minutes: 360, allowed_intervals: [60, 180, 360, 720, 1440], worker_status: 'ready' }
    else if (url.pathname === '/api/jobs/user-feed-refresh') {
      refreshCreated = true
      data = { id: 'job-1', user_id: owner.id, job_type: 'user_feed_refresh', status: 'queued', created_at: new Date().toISOString() }
    } else if (url.pathname === '/api/jobs') {
      if (!refreshCreated) data = { jobs: [] }
      else {
        jobReads += 1
        const status = jobReads > 1 ? 'partial' : 'running'
        data = { jobs: [{ id: 'job-1', user_id: owner.id, job_type: 'user_feed_refresh', status, created_at: new Date().toISOString(), result: status === 'partial' ? { item_count: 1, snapshot_created: true, source_outcomes: [{ status: 'succeeded' }, { status: 'failed' }] } : undefined }] }
      }
    } else if (url.pathname === '/api/me/items/article-1/state') {
      statePatchCalls += 1
      Object.assign(state, request.postDataJSON())
      data = state
    } else if (url.pathname === '/api/catalog/sources') data = { sources: [
      { id: 'src-public', type: 'rss', display_name: '公共产品动态', scope: 'public', default_channel: '产品机会', enabled: true },
      { id: 'src-1', type: 'rss', display_name: 'OpenAI Blog', scope: 'workspace', default_channel: 'AI', enabled: true },
      { id: 'src-private', type: 'rss', display_name: 'Owner 私有观察', scope: 'private', owner_user_id: owner.id, default_channel: '朋友动态', enabled: true },
    ] }
    else if (url.pathname === '/api/catalog/source-types') data = { source_types: [{ type: 'rss', label: 'RSS/Atom', fields: [{ name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '' }] }] }
    else if (url.pathname === '/api/me/subscriptions') data = { subscriptions: [
      { id: 'sub-public', user_id: owner.id, source_id: 'src-public', source_display_name: '公共产品动态', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 70, schedule: { enabled: false, interval_minutes: 360, allowed_intervals: [30, 60, 180, 360, 720, 1440] } },
      { id: 'sub-1', user_id: owner.id, source_id: 'src-1', source_display_name: 'OpenAI Blog', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 80, schedule: { enabled: false, interval_minutes: 360, allowed_intervals: [30, 60, 180, 360, 720, 1440] } },
      { id: 'sub-private', user_id: owner.id, source_id: 'src-private', source_display_name: 'Owner 私有观察', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 60, schedule: { enabled: false, interval_minutes: 360, allowed_intervals: [30, 60, 180, 360, 720, 1440] } },
    ] }
    else if (url.pathname === '/api/admin/secrets') data = { secrets: [{ id: 'secret-1', name: 'Gemini Primary', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', is_set: true, used_by: ['ai'] }] }
    else if (url.pathname === '/api/config') data = {
      config: { ai: { enabled: true, provider: 'gemini', model: 'gemini-3.5-flash', api_key_env: 'GOOGLE_API_KEY', summary_max_chars: 200, analysis_max_output_tokens: 800 }, filtering: { time_window_hours: 24 }, tags: ['AI Agent'] },
      taxonomy: { channels: ['AI', '产品机会', '朋友动态', '其他'], topics: ['AI Agent'] },
    }
    else if (url.pathname === '/api/users') data = { users: [owner] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })

  return { getStatePatchCalls: () => statePatchCalls }
}

test('login and complete the acquisition, reading, retention and administration loop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop end-to-end flow')
  page.on('pageerror', (error) => { throw error })
  const flow = await mockMainFlow(page)

  await page.goto('/login')
  await page.getByLabel('用户名').fill('owner')
  await page.getByLabel('密码').fill('test-password')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '今日信息流' })).toBeVisible()

  expect(flow.getStatePatchCalls()).toBe(0)
  const firstStory = page.getByTestId('feed-story').first()
  await expect(firstStory.locator('.MuiBadge-badge')).not.toHaveClass(/MuiBadge-invisible/)
  await firstStory.click()
  await expect(page.getByText('这是 Worker 已抓取并清理后的正文内容。')).toBeVisible()
  await expect.poll(flow.getStatePatchCalls).toBe(0)
  await page.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '标记已读' }).click()
  await expect.poll(flow.getStatePatchCalls).toBe(1)
  await expect(firstStory.locator('.MuiBadge-badge')).toHaveClass(/MuiBadge-invisible/)

  await page.getByRole('button', { name: '更新信息流' }).click()
  await expect(page.getByRole('button', { name: '更新已排队' })).toBeVisible()
  await expect(page.getByText('已更新 1 条可用内容，1 个来源失败。')).toBeVisible({ timeout: 8_000 })

  await page.getByRole('button', { name: '收藏' }).click()
  await page.getByRole('button', { name: '稍后读' }).click()
  const sidebar = page.getByRole('navigation', { name: '主导航' })
  await sidebar.getByRole('link', { name: '收藏' }).click()
  await expect(page.getByRole('heading', { name: 'Codex 推出新的协作工作流' })).toBeVisible()
  await sidebar.getByRole('link', { name: '稍后读' }).click()
  await expect(page.getByRole('heading', { name: 'Codex 推出新的协作工作流' })).toBeVisible()
  await sidebar.getByRole('link', { name: '历史' }).click()
  await expect(page.getByRole('heading', { name: '历史中的模型更新' })).toBeVisible()
  await sidebar.getByRole('link', { name: '信息流' }).click()
  await page.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '忽略' }).click()
  await expect(page.getByText('没有匹配的信息')).toBeVisible()

  await sidebar.getByRole('link', { name: '订阅' }).click()
  await expect(page.getByRole('heading', { name: 'AI', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '产品机会' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '朋友动态' })).toBeVisible()
  await page.getByRole('tab', { name: '运行记录' }).click()
  await expect(page.getByRole('heading', { name: '更新整个信息流' })).toBeVisible()
  await expect(page.getByText('部分完成', { exact: true })).toBeVisible()
  await expect(page.getByText('user_feed_refresh', { exact: true })).toBeHidden()
  await page.getByRole('link', { name: '设置' }).click()
  await expect(page.getByRole('heading', { name: '密钥管理' })).toBeVisible()
  await expect(page.getByText('Gemini Primary', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('test-password')
})

test('stale worker blocks an update before a job is created', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop worker preflight flow')
  let createCalls = 0
  await mockMainFlow(page)
  await page.route('**/api/auth/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, data: { authenticated: true, user: owner } }),
  }))
  await page.route('**/api/me/feed-schedule', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, data: { schema_version: 1, enabled: true, interval_minutes: 360, allowed_intervals: [60, 180, 360], worker_status: 'stale' } }),
  }))
  await page.route('**/api/jobs/user-feed-refresh', (route) => {
    createCalls += 1
    return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ ok: false }) })
  })

  await page.goto('/feed')
  await expect(page.getByRole('heading', { name: '今日信息流' })).toBeVisible()
  await page.getByRole('button', { name: '更新信息流' }).click()
  await expect(page.getByText('后台获取服务当前不可用，未创建更新任务。请启动 Worker 后重试。')).toBeVisible()
  expect(createCalls).toBe(0)
})

test('members can subscribe but cannot edit shared or other users private sources', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop permission presentation flow')
  const member = { ...owner, id: 'user-member', username: 'member', display_name: 'Member', role: 'member' }
  await mockMainFlow(page)
  await page.route('**/api/auth/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, data: { authenticated: true, user: member } }),
  }))

  await page.goto('/subscriptions')
  await expect(page.getByRole('heading', { name: 'AI', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /编辑 .* 来源/ })).toHaveCount(0)

  await page.getByRole('button', { name: '新增来源' }).click()
  await page.getByRole('combobox', { name: '来源类型' }).click()
  await page.getByRole('option', { name: 'RSS/Atom' }).click()
  await page.getByRole('combobox', { name: '可见范围' }).click()
  await expect(page.getByRole('option', { name: '我的私有来源' })).toBeVisible()
  await expect(page.getByRole('option', { name: '公共来源' })).toHaveCount(0)
  await expect(page.getByRole('option', { name: '团队来源' })).toHaveCount(0)
})
