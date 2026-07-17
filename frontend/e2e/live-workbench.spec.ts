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
const rollingItem = {
  ...items.at(-1)!,
  id: 'live-201',
  title: '实时条目 201',
  url: 'https://example.com/live-201',
  summary_zh: '固定长度窗口中的新内容',
  published_at: '2026-07-01T04:00:00.000Z',
}

test.beforeEach(async ({ page }) => {
  let refreshCreated = false
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } }
    else if (url.pathname === '/api/feed/latest') data = { schema_version: 2, items: refreshCreated ? [...items.slice(1), rollingItem] : items }
    else if (url.pathname === '/api/jobs/user-feed-refresh' && route.request().method() === 'POST') {
      refreshCreated = true
      data = { id: 'refresh-1', user_id: 'e2e-user', job_type: 'user_feed_refresh', status: 'queued', created_at: '2026-07-17T04:00:00Z' }
    }
    else if (url.pathname === '/api/jobs') data = { jobs: refreshCreated ? [{ id: 'refresh-1', user_id: 'e2e-user', job_type: 'user_feed_refresh', status: 'succeeded', created_at: '2026-07-17T04:00:00Z', finished_at: '2026-07-17T04:00:02Z', result: {} }] : [] }
    else if (url.pathname === '/api/me/feed-schedule') data = { enabled: true, interval_minutes: 60, worker_status: 'ready' }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: '/mcp',
      token_ttl_days: 90,
      max_active: 5,
      connections: [{ id: 'agent-1', name: 'OpenClaw', client_type: 'openclaw', scopes: ['inteliscope:read'], token_prefix: 'abc', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname.startsWith('/api/feed/items/')) data = [...items, rollingItem].find((item) => item.id === decodeURIComponent(url.pathname.split('/').at(-1) || ''))
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
  expect(await page.locator('[data-testid="workbench-card"]').count()).toBeLessThanOrEqual(40)
  await expect(page.getByRole('navigation', { name: '信息流进度' }).getByRole('button')).toHaveCount(12)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(100)

  const shell = page.getByTestId('live-workbench-shell')
  expect(await page.locator('body').evaluate((element) => getComputedStyle(element).color)).toBe(
    await shell.evaluate((element) => getComputedStyle(element).color),
  )
  const desktopNavigation = page.getByRole('complementary', { name: '桌面导航' })
  const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
  let agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })

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
    const toggle = page.getByRole('button', { name: '展开 Agent 面板' })
    const feedScroll = page.getByTestId('workbench-feed-scroll')
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
    await expect(page.getByTestId('agent-drawer-backdrop')).toBeVisible()
    await expect(agent.getByText('已配置')).toBeVisible()
    await agent.evaluate(async (element) => Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined))))
    expect(await feedScroll.boundingBox()).toEqual(feedBounds)
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
      expect(Math.abs((agentBounds?.width ?? 0) - 360)).toBeLessThanOrEqual(1)
      expect(Math.round((agentBounds?.x ?? 0) + (agentBounds?.width ?? 0))).toBe(1024)
    }
    await page.keyboard.press('Escape')
    await expect(toggle).toBeFocused()
    await expect(agent).toBeHidden()
  }

  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  await page.waitForTimeout(100)
  const anchorName = await page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollElement) => {
    const bounds = (scrollElement as HTMLElement).getBoundingClientRect()
    const visible = cards.filter((card) => card.getBoundingClientRect().bottom > bounds.top).sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)
    return visible[0]?.getAttribute('aria-label') ?? ''
  }, await feedScroll.elementHandle())
  const card = page.getByRole('article', { name: anchorName })
  const anchorScrollTop = await feedScroll.evaluate((element) => element.scrollTop)
  // Invoke the already-visible control directly: Playwright's actionability helper otherwise
  // scrolls a partially visible first card before dispatching the click, unlike a pointer click.
  await card.getByRole('button', { name: `展开 ${anchorName}` }).evaluate((element: HTMLElement) => element.click())
  await expect(page).toHaveURL(/item=live-/)
  await page.waitForTimeout(100)
  expect(await feedScroll.evaluate((element) => element.scrollTop)).toBe(anchorScrollTop)
  const topVisibleAfter = await page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollElement) => {
    const bounds = (scrollElement as HTMLElement).getBoundingClientRect()
    const visible = cards.filter((candidate) => candidate.getBoundingClientRect().bottom > bounds.top).sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)
    return visible[0]?.getAttribute('aria-label') ?? ''
  }, await feedScroll.elementHandle())
  expect(topVisibleAfter).toBe(anchorName)
  await card.getByRole('button', { name: `将 ${anchorName} 加入 Agent 上下文` }).click()

  await page.getByRole('button', { name: '更新信息流' }).click()
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeVisible({ timeout: 7000 })
  await feedScroll.evaluate((element) => {
    element.scrollTop = element.scrollHeight - element.clientHeight
    element.dispatchEvent(new Event('scroll'))
  })
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeHidden()

  const openAgent = page.getByRole('button', { name: '展开 Agent 面板' })
  if (await openAgent.isVisible()) await openAgent.click()
  agent = testInfo.project.name === 'desktop'
    ? page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    : page.getByRole('dialog', { name: 'OpenClaw 上下文' })
  await expect(agent.getByText('1 / 8')).toBeVisible()
  await agent.getByRole('textbox', { name: '交给 OpenClaw 的问题' }).fill('提炼机会')
  await agent.getByRole('button', { name: '复制并交给 OpenClaw' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('调用 get_item')

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
