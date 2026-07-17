import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const items = Array.from({ length: 200 }, (_, index) => ({
  id: `live-${index + 1}`,
  title: `实时条目 ${index + 1}`,
  url: `https://example.com/live-${index + 1}`,
  source: index % 2 ? 'OpenAI Blog' : 'GitHub',
  summary_zh: `第 ${index + 1} 条真实 API 摘要`,
  published_at: new Date(Date.UTC(2026, 6, 1, 0, index)).toISOString(),
  channel: index % 2 ? 'AI' : '开发',
  topics: ['Codex'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
}))

test.beforeEach(async ({ page }) => {
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } }
    else if (url.pathname === '/api/feed/latest') data = { schema_version: 2, items }
    else if (url.pathname === '/api/jobs') data = { jobs: [] }
    else if (url.pathname === '/api/me/feed-schedule') data = { enabled: true, interval_minutes: 60, worker_status: 'ready' }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: '/mcp',
      token_ttl_days: 90,
      max_active: 5,
      connections: [{ id: 'agent-1', name: 'OpenClaw', client_type: 'openclaw', scopes: ['inteliscope:read'], token_prefix: 'abc', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname.startsWith('/api/feed/items/')) data = items.find((item) => item.id === decodeURIComponent(url.pathname.split('/').at(-1) || ''))
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
      return
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
})

test('live HeroUI workbench preserves responsive shell, virtualization and Agent handoff', async ({ context, page }, testInfo) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/__preview/workbench-live')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByText('稍后读')).toHaveCount(0)
  await expect(page.locator('[data-testid="workbench-card"]')).toHaveCount(await page.locator('[data-testid="workbench-card"]').count())
  expect(await page.locator('[data-testid="workbench-card"]').count()).toBeLessThanOrEqual(40)
  await expect(page.getByRole('navigation', { name: '信息流进度' }).getByRole('button')).toHaveCount(12)

  const shell = page.getByTestId('live-workbench-shell')
  const desktopNavigation = page.getByRole('complementary', { name: '桌面导航' })
  const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
  const agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })

  if (testInfo.project.name === 'desktop') {
    await expect(desktopNavigation).toBeVisible()
    await expect(mobileNavigation).toBeHidden()
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(232)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect(agent.getByText('已配置')).toBeVisible()

    await page.setViewportSize({ width: 1280, height: 800 })
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
  } else {
    const closedBounds = await agent.boundingBox()
    const toggle = page.getByRole('button', { name: '展开 Agent 面板' })
    if (testInfo.project.name === 'mobile') {
      await expect(desktopNavigation).toBeHidden()
      await expect(mobileNavigation).toBeVisible()
      expect(closedBounds?.y).toBeGreaterThanOrEqual(844)
      expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(1)
    } else {
      await expect(desktopNavigation).toBeVisible()
      await expect(mobileNavigation).toBeHidden()
      expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
      expect(closedBounds?.x).toBeGreaterThanOrEqual(1024)
      expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    }
    await toggle.click()
    await expect(agent.getByText('已配置')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(toggle).toBeFocused()
  }

  const card = page.getByRole('article', { name: '实时条目 200' })
  await card.getByRole('button', { name: '展开 实时条目 200' }).click()
  await expect(page).toHaveURL(/item=live-200/)
  await card.getByRole('button', { name: '将 实时条目 200 加入 Agent 上下文' }).click()
  const openAgent = page.getByRole('button', { name: '展开 Agent 面板' })
  if (await openAgent.isVisible()) await openAgent.click()
  await expect(agent.getByText('1 / 8')).toBeVisible()
  await agent.getByRole('textbox', { name: '交给 OpenClaw 的问题' }).fill('提炼机会')
  await agent.getByRole('button', { name: '复制并交给 OpenClaw' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('调用 get_item')

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
