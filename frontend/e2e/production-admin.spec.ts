import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const owner = { id: 'owner-1', username: 'owner', display_name: '验收管理员', role: 'owner', enabled: true }

async function mockAdminApi(page: Page, authenticated = true) {
  let quotaRequests = 0
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url())
    let data: unknown

    if (url.pathname === '/api/auth/status') data = { authenticated, user: authenticated ? owner : null }
    else if (url.pathname === '/api/auth/login') data = { authenticated: true, user: owner }
    else if (url.pathname === '/api/catalog/sources') data = { sources: [
      { id: 'source-1', type: 'rss', display_name: 'OpenAI Blog', description: '官方产品与研究动态', scope: 'workspace', default_channel: 'AI', default_topics: ['Codex'], enabled: true },
      { id: 'source-2', type: 'rss', display_name: 'Product Notes', description: '产品机会观察', scope: 'public', default_channel: '产品机会', default_topics: ['产品'], enabled: true },
    ] }
    else if (url.pathname === '/api/catalog/source-types') data = { source_types: [
      { type: 'rss', label: 'RSS/Atom', fields: [{ name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '' }] },
    ] }
    else if (url.pathname === '/api/me/subscriptions') data = { subscriptions: [
      { id: 'subscription-1', user_id: owner.id, source_id: 'source-1', source_display_name: 'OpenAI Blog', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 80, schedule: { enabled: true, interval_minutes: 360, allowed_intervals: [60, 180, 360, 720, 1440] } },
    ] }
    else if (url.pathname === '/api/me/source-health') data = {
      schema_version: 1,
      scope: 'user',
      summary: { total: 1, healthy: 1, degraded: 0, failing: 0, unknown: 0 },
      items: [{ subscription_id: 'subscription-1', source_id: 'source-1', source_display_name: 'OpenAI Blog', source_type: 'rss', status: 'healthy', consecutive_failures: 0, last_fetched_count: 7 }],
    }
    else if (url.pathname === '/api/me/feed-schedule') data = { schema_version: 1, enabled: true, interval_minutes: 360, allowed_intervals: [60, 180, 360, 720, 1440], worker_status: 'ready', next_run_at: '2026-07-17T12:00:00Z' }
    else if (url.pathname === '/api/jobs') data = { jobs: [{ id: 'job-1', user_id: owner.id, job_type: 'source_fetch', source_id: 'source-1', subscription_id: 'subscription-1', status: 'succeeded', created_at: '2026-07-17T08:00:00Z', finished_at: '2026-07-17T08:00:02Z', result: { item_count: 7 } }] }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: 'https://example.test/mcp',
      subscription_writes_enabled: false,
      openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' },
      token_ttl_days: 90,
      max_active: 5,
      connections: [{ id: 'agent-1', name: '本机 OpenClaw', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'], token_prefix: 'ih_mcp_v1_demo', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname === '/api/config') data = {
      config: {
        ai: { enabled: true, provider: 'gemini', model: 'gemini-3.5-flash', api_key_env: 'GOOGLE_API_KEY', base_url: '', languages: 'zh', analysis_content_chars: 8000, analysis_comments_chars: 4000, summary_max_chars: 240, analysis_max_output_tokens: 800 },
        filtering: { ai_score_threshold: 6, homepage_min_score: 7, time_window_hours: 24, recent_item_limit: 200 },
        tags: ['AI Agent'],
      },
      taxonomy: { channels: ['AI', '产品机会', '其他'], topics: ['AI Agent', 'Codex'] },
    }
    else if (url.pathname === '/api/admin/secrets' && route.request().method() === 'POST') data = {
      id: 'secret-created',
      name: 'DeepSeek Primary',
      kind: 'ai',
      provider: 'deepseek',
      env_name: 'DEEPSEEK_API_KEY',
      is_set: true,
      used_by: [],
    }
    else if (url.pathname === '/api/admin/secrets') data = { secrets: [
      { id: 'secret-1', name: 'Gemini Primary', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', is_set: true, used_by: [{ type: 'ai', id: 'primary', name: 'AI 分析' }] },
      { id: 'secret-apify', name: 'Apify Primary', kind: 'apify', provider: 'apify', env_name: 'APIFY_PRIMARY_WORKSPACE_TOKEN', is_set: true, used_by: [] },
    ] }
    else if (url.pathname === '/api/admin/apify-key-pool') data = {
      schema_version: 1,
      enabled: false,
      generation: 1,
      status: 'ready',
      active_secret_id: 'secret-apify',
      draining_secret_id: null,
      blocked_reason: null,
      retry_at: null,
      members: [{
        secret_id: 'secret-apify',
        position: 0,
        status: 'active',
        blocked_until: null,
        cycle_end_at: '2026-07-31T23:59:59.999Z',
        last_checked_at: '2026-07-23T08:30:00+00:00',
        last_error_code: null,
        active_run_count: 0,
      }],
    }
    else if (url.pathname === '/api/admin/secrets/secret-apify/quota') {
      quotaRequests += 1
      data = {
        secret_id: 'secret-apify',
        provider: 'apify',
        currency: 'USD',
        cycle_start_at: '2026-07-01T00:00:00.000Z',
        cycle_end_at: '2026-07-31T23:59:59.999Z',
        checked_at: '2026-07-23T08:30:00+00:00',
        monthly_included_credits_usd: 49,
        monthly_usage_usd: 12.5,
        remaining_included_credits_usd: 36.5,
        max_monthly_usage_usd: 100,
        remaining_hard_limit_usd: 87.5,
      }
    }
    else if (url.pathname === '/api/users') data = { users: [owner] }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: url.pathname } }) })
      return
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  return { quotaRequests: () => quotaRequests }
}

async function expectHeroAdminPage(page: Page, heading: string, { agentAvailable = false } = {}) {
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  await expect(page.locator('h1')).toHaveCount(1)
  await expect(page.locator('[data-page-frame="admin"]')).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Agent 面板/ })).toHaveCount(agentAvailable ? 1 : 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
}

test('production administration routes use the adaptive Quiet Studio page pattern at every acceptance viewport', async ({ page }) => {
  await mockAdminApi(page)

  await page.goto('/subscriptions')
  await expectHeroAdminPage(page, '订阅与来源', { agentAvailable: true })
  await expect(page.getByRole('tab')).toHaveCount(3)

  await page.goto('/agents')
  await expectHeroAdminPage(page, '助手连接')
  await expect(page.getByText('本机 OpenClaw')).toBeVisible()

  await page.goto('/settings')
  await expectHeroAdminPage(page, '设置')
  await expect(page.getByRole('heading', { name: '助手与 AI' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '获取与主题' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '密钥' })).toBeVisible()

  await page.goto('/users')
  await expectHeroAdminPage(page, '账户与成员')
  await expect(page.getByRole('heading', { name: '账户安全' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '成员管理' })).toBeVisible()

  await page.goto('/manual')
  await expectHeroAdminPage(page, '操作手册')
  await expect(page.getByRole('heading', { name: '快速开始' })).toBeVisible()
  await expect(page.getByText(/每次产品代码合并都由 Test Gate 检查/)).toBeVisible()
})

test('account and documentation menus open upward and expose manual, changelog, and Release destinations', async ({ page }, testInfo) => {
  await mockAdminApi(page)

  if (testInfo.project.name === 'mobile') {
    await page.goto('/settings')
    await expect(page.getByRole('button', { name: '查看操作手册' })).toBeVisible()
    await expect(page.getByRole('button', { name: '查看更新日志' })).toBeVisible()
    await expect(page.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('href', 'https://github.com/StealHD/infohub-light/releases')
    return
  }

  await page.goto('/subscriptions')
  const accountTrigger = page.getByRole('button', { name: '打开账户菜单' })
  await accountTrigger.click()
  const accountMenu = page.getByRole('dialog', { name: '账户菜单' })
  await expect(accountMenu).toBeVisible()
  await expect(accountMenu.getByRole('button', { name: '操作手册' })).toBeVisible()
  await expect(accountMenu.getByRole('button', { name: '更新日志' })).toBeVisible()
  await expect(accountMenu.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('target', '_blank')
  const accountTriggerBounds = await accountTrigger.boundingBox()
  const accountSurfaceBounds = await page.locator('[data-account-menu-surface]').boundingBox()
  expect(accountTriggerBounds).not.toBeNull()
  expect(accountSurfaceBounds).not.toBeNull()
  expect(accountSurfaceBounds!.y + accountSurfaceBounds!.height).toBeLessThanOrEqual(accountTriggerBounds!.y)

  await accountMenu.getByRole('button', { name: '操作手册' }).click()
  await expect(page).toHaveURL(/\/manual$/)
  await expect(page.getByRole('heading', { name: '操作手册' })).toBeVisible()

  if (testInfo.project.name === 'desktop') {
    await page.goto('/subscriptions')
    await page.getByRole('button', { name: '展开侧栏' }).click()
    const documentationTrigger = page.getByRole('button', { name: '打开文档与发布菜单' })
    await documentationTrigger.click()
    const documentationMenu = page.getByRole('dialog', { name: '文档与发布菜单' })
    await expect(documentationMenu.getByRole('button', { name: '操作手册' })).toBeVisible()
    await expect(documentationMenu.getByRole('button', { name: '更新日志' })).toBeVisible()
    await expect(documentationMenu.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('rel', 'noopener noreferrer')
    const documentationTriggerBounds = await documentationTrigger.boundingBox()
    const documentationSurfaceBounds = await page.locator('[data-documentation-menu-surface]').boundingBox()
    expect(documentationTriggerBounds).not.toBeNull()
    expect(documentationSurfaceBounds).not.toBeNull()
    expect(documentationSurfaceBounds!.y + documentationSurfaceBounds!.height).toBeLessThanOrEqual(documentationTriggerBounds!.y)
  }
})

test('settings key tables contain scrolling, quota, refresh and accessible modal behavior', async ({ page }) => {
  const apiState = await mockAdminApi(page)
  await page.goto('/settings')

  await expect(page.getByRole('heading', { name: '密钥' })).toBeVisible()
  const apifyTable = page.getByRole('grid', { name: 'Apify Key 池' })
  const aiTable = page.getByRole('grid', { name: '已配置 AI Key' })
  await expect(apifyTable).toBeVisible()
  await expect(aiTable).toBeVisible()
  await expect(apifyTable.getByRole('columnheader')).toHaveText(['Key', '池状态', '额度', '操作'])
  await expect(aiTable.getByRole('columnheader')).toHaveText(['Key', '类型', '状态', '额度', '操作'])
  await expect(page.getByText('套餐剩余 $36.50')).toBeVisible()
  await expect(page.getByText('暂不支持查询')).toBeVisible()
  await expect.poll(apiState.quotaRequests).toBe(1)
  const tableScroll = page.getByTestId('secret-table-scroll')
  const apifyTableScroll = page.getByTestId('apify-key-pool-scroll')
  expect(await tableScroll.evaluate((element) => getComputedStyle(element).overflowX)).toMatch(/auto|scroll/)
  expect(await apifyTableScroll.evaluate((element) => getComputedStyle(element).overflowX)).toMatch(/auto|scroll/)
  if ((page.viewportSize()?.width ?? 0) <= 390) {
    expect(await tableScroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
  }
  const refreshQuota = page.getByRole('button', { name: '刷新 Apify Primary 额度' })
  await refreshQuota.click()
  await expect.poll(apiState.quotaRequests).toBe(2)
  const rotateTrigger = page.getByRole('button', { name: '轮换 Apify Primary' })
  await rotateTrigger.click()
  await expect(page.getByRole('dialog', { name: '轮换 Apify Primary' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '轮换 Apify Primary' })).toHaveCount(0)
  await expect(rotateTrigger).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('successful Key creation uses a top overlay without moving settings content', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockAdminApi(page)
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '密钥' })).toBeVisible()
  await page.evaluate(async () => {
    await document.fonts.ready
  })

  await page.getByRole('textbox', { name: 'Key 名称' }).fill('DeepSeek Primary')
  await page.getByRole('textbox', { name: 'Key provider' }).fill('deepseek')
  await page.getByRole('textbox', { name: '环境变量名' }).fill('DEEPSEEK_API_KEY')
  await page.getByLabel('Key 值').fill('write-only-e2e-value')
  const keyHeading = page.getByRole('heading', { name: '密钥' })
  const positionWithinPage = () => keyHeading.evaluate((element) => {
    const pageFrame = element.closest('[data-page-frame="admin"]')
    if (!pageFrame) throw new Error('Settings page frame is missing.')
    const headingBounds = element.getBoundingClientRect()
    const frameBounds = pageFrame.getBoundingClientRect()
    return {
      x: headingBounds.x - frameBounds.x,
      y: headingBounds.y - frameBounds.y,
    }
  })
  const before = await positionWithinPage()

  await page.getByRole('button', { name: '新增 Key' }).click()
  const toastTitle = page.getByText('Key 已安全保存', { exact: true })
  await expect(toastTitle).toBeVisible()
  const after = await positionWithinPage()
  expect(Math.abs(after.x - before.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(1)
  await expect(page.locator('[data-page-frame="admin"]').getByText('Key 已安全保存', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Key 已保存，页面不会回显真实值。')).toHaveCount(0)

  const toastBounds = await toastTitle.boundingBox()
  const viewport = page.viewportSize()!
  expect(toastBounds).not.toBeNull()
  expect(toastBounds!.x).toBeGreaterThanOrEqual(0)
  expect(toastBounds!.x + toastBounds!.width).toBeLessThanOrEqual(viewport.width)
  expect(toastBounds!.y).toBeGreaterThanOrEqual(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('subscription controls preserve the first source card on the mobile first screen', async ({ page }, testInfo) => {
  await mockAdminApi(page)
  await page.goto('/subscriptions')

  const viewportWidth = page.viewportSize()?.width ?? 0
  const tabWidths: number[] = []
  for (const tab of await page.getByRole('tab').all()) {
    const bounds = await tab.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewportWidth)
    tabWidths.push(bounds!.width)
  }

  if (testInfo.project.name === 'mobile') {
    expect(Math.max(...tabWidths) - Math.min(...tabWidths)).toBeLessThanOrEqual(1)
    const mobileSchedule = page.locator('[data-mobile-schedule]')
    await expect(mobileSchedule.getByRole('button', { name: '管理自动更新' })).toBeVisible()
    await expect(mobileSchedule.getByText('更新周期', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'OpenAI Blog', exact: true })).toBeInViewport()
    await mobileSchedule.getByRole('button', { name: '管理自动更新' }).click()
    await expect(mobileSchedule.getByText('更新周期', { exact: true })).toBeVisible()
    await expect(mobileSchedule.getByRole('button', { name: '关闭自动更新' })).toBeVisible()

    await expect(page.getByRole('searchbox', { name: '搜索来源' })).toBeVisible()
    await page.getByRole('button', { name: '筛选来源，已启用 0 项' }).click()
    const filterDialog = page.getByRole('dialog', { name: '筛选来源' })
    await expect(filterDialog).toBeVisible()
    await expect(filterDialog.getByText('来源类型', { exact: true })).toBeVisible()
    await expect(filterDialog.getByText('健康状态', { exact: true })).toBeVisible()
    await expect(filterDialog.getByText('可见范围', { exact: true })).toBeVisible()
    const clearFilters = filterDialog.getByRole('button', { name: '清除筛选' })
    await expect(clearFilters).toBeDisabled()
    await filterDialog.getByRole('button', { name: '来源类型' }).click()
    await page.getByRole('option', { name: 'RSS/Atom' }).click()
    await expect(clearFilters).toBeEnabled()
    await filterDialog.getByRole('button', { name: '关闭筛选' }).click()
    await expect(filterDialog).toHaveCount(0)
    await expect(page.getByRole('button', { name: '筛选来源，已启用 1 项' })).toBeVisible()
    await page.getByRole('button', { name: '筛选来源，已启用 1 项' }).click()
    await page.getByRole('dialog', { name: '筛选来源' }).getByRole('button', { name: '清除筛选' }).click()
    await expect(page.getByRole('button', { name: '筛选来源，已启用 0 项' })).toBeVisible()
    await page.getByRole('dialog', { name: '筛选来源' }).getByRole('button', { name: '关闭筛选' }).click()
    await expect(page.getByRole('dialog', { name: '筛选来源' })).toHaveCount(0)
  } else {
    const desktopSchedule = page.locator('[data-desktop-schedule]')
    const desktopFilters = page.locator('[data-desktop-source-filters]').first()
    await expect(page.getByRole('button', { name: '管理自动更新' })).toBeHidden()
    await expect(desktopSchedule.getByText('更新周期', { exact: true })).toBeVisible()
    await expect(desktopFilters.getByText('来源类型', { exact: true })).toBeVisible()
    await expect(desktopFilters.getByText('健康状态', { exact: true })).toBeVisible()
    await expect(desktopFilters.getByText('可见范围', { exact: true })).toBeVisible()
  }

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('production login is a standalone HeroUI page at every acceptance viewport', async ({ page }) => {
  await mockAdminApi(page, false)
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录私人信息雷达' })).toBeVisible()
  await expect(page.locator('h1')).toHaveCount(1)
  await expect(page.locator('[data-page-frame="auth"]')).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByRole('navigation')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})
