import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const items = Array.from({ length: 200 }, (_, index) => ({
  id: `live-${index + 1}`,
  title: `实时条目 ${index + 1}`,
  url: `https://example.com/live-${index + 1}`,
  source: index % 2 ? 'OpenAI Blog' : 'GitHub',
  summary_zh: `第 ${index + 1} 条真实 API 摘要`,
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
  user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false },
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
  const targetName = await page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollElement) => {
    const bounds = (scrollElement as HTMLElement).getBoundingClientRect()
    return cards
      .filter((card) => card.getBoundingClientRect().top >= bounds.top)
      .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
      ?.getAttribute('aria-label') ?? ''
  }, await feedScroll.elementHandle())
  expect(targetName).not.toBe('')

  let stableFrames = 0
  for (let frame = 0; frame < 120 && stableFrames < 3; frame += 1) {
    const delta = await page.getByRole('article', { name: targetName }).evaluate((card, scrollElement) => (
      card.getBoundingClientRect().top - (scrollElement as HTMLElement).getBoundingClientRect().top
    ), await feedScroll.elementHandle())
    if (Math.abs(delta) <= 0.5) stableFrames += 1
    else {
      stableFrames = 0
      await feedScroll.evaluate((element, correction) => {
        element.scrollTop += correction
        element.dispatchEvent(new Event('scroll'))
      }, delta)
    }
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
  }
  expect(stableFrames).toBe(3)
  const anchor = await topVisibleSnapshot(page)
  expect(anchor.name).toBe(targetName)
  return anchor
}

test.beforeEach(async ({ page }) => {
  let refreshCreated = false
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } }
    else if (url.pathname === '/api/feed/latest') {
      const batchMode = new URL(page.url()).searchParams.has('batch')
      data = { schema_version: 2, items: refreshCreated ? batchMode ? [...items.slice(80), ...batchRollingItems] : [...items.slice(1), rollingItem] : items }
    }
    else if (url.pathname === '/api/feed/saved') data = { items: [savedRouteItem] }
    else if (url.pathname === '/api/feed/history') data = { items: [historyRouteItem] }
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
    else if (url.pathname.startsWith('/api/feed/items/')) {
      const item = [...items, rollingItem, savedRouteItem, historyRouteItem].find((candidate) => candidate.id === decodeURIComponent(url.pathname.split('/').at(-1) || ''))
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

test('production HeroUI workbench preserves responsive shell, virtualization and Agent handoff', async ({ context, page }, testInfo) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/feed')
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
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect(agent.getByText('已配置')).toBeVisible()
    await page.getByRole('button', { name: '展开侧栏' }).click()
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(232)
    expect(await page.evaluate(() => window.localStorage.getItem('inteliscope.ui.sidebar.v1:e2e-user'))).toBe('expanded')

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
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    await expect(page.getByRole('button', { name: /侧栏/ })).toHaveCount(0)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)

    const desktopFeed = page.getByTestId('workbench-feed-scroll')
    const bottomDistance = () => desktopFeed.evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight)
    await desktopFeed.evaluate((element) => {
      element.scrollTop = element.scrollHeight - element.clientHeight
      element.dispatchEvent(new Event('scroll'))
    })
    expect(await bottomDistance()).toBeLessThanOrEqual(2)
    await page.getByRole('button', { name: '收起 Agent 面板' }).click()
    await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toHaveCount(0)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
    await expect(page.getByRole('button', { name: '关闭 Agent 面板' })).toHaveCount(0)
    expect(await bottomDistance()).toBeLessThanOrEqual(96)
    await page.getByRole('button', { name: '展开 Agent 面板' }).click()
    await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeVisible()
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
  if (testInfo.project.name === 'mobile') {
    await expect(mobileNavigation.getByRole('link')).toHaveCount(6)
    await expect(mobileNavigation.getByRole('link', { name: '助手连接' })).toBeVisible()
  }

  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  const anchorName = (await stableTopVisibleSnapshot(page)).name
  await feedScroll.dispatchEvent('scroll')
  const card = page.getByRole('article', { name: anchorName })
  const anchorScrollTop = await feedScroll.evaluate((element) => element.scrollTop)
  // Invoke the already-visible control directly: Playwright's actionability helper otherwise
  // scrolls a partially visible first card before dispatching the click, unlike a pointer click.
  await card.getByRole('button', { name: `展开 ${anchorName}` }).evaluate((element: HTMLElement) => element.click())
  await expect(page).toHaveURL(/item=live-/)
  await expect(card.getByRole('button', { name: `收起 ${anchorName}` })).toBeVisible()
  expect(await feedScroll.evaluate((element) => element.scrollTop)).toBe(anchorScrollTop)
  const topVisibleAfter = (await stableTopVisibleSnapshot(page)).name
  expect(topVisibleAfter).toBe(anchorName)
  await card.getByRole('button', { name: `将 ${anchorName} 加入 Agent 上下文` }).click()

  const rollingAnchorBefore = await alignVisibleCardToTop(page)
  await page.getByRole('button', { name: '更新信息流' }).evaluate((element: HTMLElement) => element.click())
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeVisible({ timeout: 7000 })
  const rollingAnchorAfter = await topVisibleSnapshot(page)
  expect(rollingAnchorAfter.name).toBe(rollingAnchorBefore.name)
  expect(Math.abs(rollingAnchorAfter.offset - rollingAnchorBefore.offset)).toBeLessThanOrEqual(2)
  await page.getByRole('button', { name: '查看 1 条新内容' }).click()
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeHidden()
  await expect.poll(() => feedScroll.evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight)).toBeLessThanOrEqual(96)

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

test('a proven-stale initial deep link returns the real Feed viewport to the bottom', async ({ page }) => {
  await page.goto('/feed?item=missing')
  await expect(page.getByText(/这条信息已不可用/)).toBeVisible()
  await expect(page).toHaveURL('/feed')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  const remaining = await page.getByTestId('workbench-feed-scroll').evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight)
  expect(remaining).toBeLessThanOrEqual(96)
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
  await expect(page.getByText('未读优先')).toBeVisible()
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  const anchorBefore = await alignVisibleCardToTop(page)
  expect(anchorBefore.name).not.toBe('')

  // Preserve the geometry sampled above at the exact refresh boundary; actionability
  // waiting may span a later virtualizer measurement and create a different anchor.
  await page.getByRole('button', { name: '更新信息流' }).evaluate((element: HTMLElement) => element.click())
  await expect(page.getByRole('button', { name: '查看 80 条新内容' })).toBeVisible({ timeout: 7000 })
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorBefore.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorBefore.offset)).toBeLessThanOrEqual(2)

  const beforeJump = await feedScroll.evaluate((element) => element.scrollTop)
  await page.getByRole('button', { name: '跳转到第 1 条信息' }).click()
  await expect.poll(() => feedScroll.evaluate((element) => element.scrollTop)).toBeLessThan(beforeJump / 2)
  const afterJump = await feedScroll.evaluate((element) => element.scrollTop)
  await stableTopVisibleSnapshot(page)
  expect(Math.abs(await feedScroll.evaluate((element) => element.scrollTop) - afterJump)).toBeLessThanOrEqual(2)
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

test('a jump during an in-flight refresh releases the captured refresh anchor', async ({ page }) => {
  let refreshRequested = false
  let signalSecondRequest!: () => void
  let releaseSecondRequest!: () => void
  const secondRequestStarted = new Promise<void>((resolve) => { signalSecondRequest = resolve })
  const secondRequestReleased = new Promise<void>((resolve) => { releaseSecondRequest = resolve })
  await page.exposeFunction('releaseRefreshResponse', () => releaseSecondRequest())
  await page.route('**/api/jobs/user-feed-refresh', async (route) => {
    refreshRequested = true
    await route.fallback()
  })
  await page.route('**/api/feed/latest', async (route) => {
    if (refreshRequested) {
      signalSecondRequest()
      await secondRequestReleased
    }
    await route.fallback()
  })

  await page.goto('/feed')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) * 0.72)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)
  await page.getByRole('button', { name: '更新信息流' }).evaluate((element: HTMLElement) => element.click())
  await secondRequestStarted

  await page.getByRole('button', { name: '跳转到第 1 条信息' }).evaluate((element: HTMLElement) => {
    element.click()
    queueMicrotask(() => {
      void (window as typeof window & { releaseRefreshResponse: () => Promise<void> }).releaseRefreshResponse()
    })
  })
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeVisible({ timeout: 7000 })
  await stableTopVisibleSnapshot(page)
  expect(await feedScroll.evaluate((element) => element.scrollTop)).toBeLessThan(400)
})

test('a clamped rail jump releases ownership before a later external search update', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The navigation ownership regression uses the desktop progress rail.')

  let refreshRequested = false
  let signalShrinkingRefresh!: () => void
  let releaseShrinkingRefresh!: () => void
  const shrinkingRefreshStarted = new Promise<void>((resolve) => { signalShrinkingRefresh = resolve })
  const shrinkingRefreshReleased = new Promise<void>((resolve) => { releaseShrinkingRefresh = resolve })
  await page.exposeFunction('releaseShrinkingRefresh', () => releaseShrinkingRefresh())
  await page.route('**/api/jobs/user-feed-refresh', async (route) => {
    refreshRequested = true
    await route.fallback()
  })
  await page.route('**/api/feed/latest', async (route) => {
    if (!refreshRequested) return route.fallback()
    signalShrinkingRefresh()
    await shrinkingRefreshReleased
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { schema_version: 2, items: items.slice(0, 50) } }) })
  })

  await page.goto('/feed')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) * 0.7)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)

  await page.getByRole('button', { name: '更新信息流' }).evaluate((element: HTMLElement) => element.click())
  await shrinkingRefreshStarted
  await page.getByRole('button', { name: '跳转到第 182 条信息' }).evaluate((element: HTMLElement) => {
    element.click()
    queueMicrotask(() => {
      void (window as typeof window & { releaseShrinkingRefresh: () => Promise<void> }).releaseShrinkingRefresh()
    })
  })

  await expect(page.getByRole('article', { name: '实时条目 50' })).toBeVisible()

  // The 182nd rail destination is clamped to item 50. Once that target is visible,
  // its stale pre-shrink index must no longer own later list changes.
  await feedScroll.evaluate((element) => {
    element.scrollTop = 0
    element.dispatchEvent(new Event('scroll'))
  })
  await page.getByRole('searchbox', { name: '搜索信息流' }).fill('实时条目 1')
  await expect(page.getByText('旧内容在上，最新内容在下 · 11 条')).toBeVisible()
  await stableTopVisibleSnapshot(page)
  expect(await feedScroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(2)
})

test('a wheel release after cards commit cancels the pending navigation RAF', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The navigation-RAF regression uses the desktop progress rail.')

  let refreshRequested = false
  let signalShrinkingRefresh!: () => void
  let releaseShrinkingRefresh!: () => void
  const shrinkingRefreshStarted = new Promise<void>((resolve) => { signalShrinkingRefresh = resolve })
  const shrinkingRefreshReleased = new Promise<void>((resolve) => { releaseShrinkingRefresh = resolve })
  await page.exposeFunction('releaseRafGateRefresh', () => releaseShrinkingRefresh())
  await page.route('**/api/jobs/user-feed-refresh', async (route) => {
    refreshRequested = true
    await route.fallback()
  })
  await page.route('**/api/feed/latest', async (route) => {
    if (!refreshRequested) return route.fallback()
    signalShrinkingRefresh()
    await shrinkingRefreshReleased
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { schema_version: 2, items: items.slice(0, 50) } }) })
  })

  await page.goto('/feed')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) * 0.7)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)
  await page.getByRole('button', { name: '更新信息流' }).evaluate((element: HTMLElement) => element.click())
  await shrinkingRefreshStarted
  await page.getByRole('button', { name: '跳转到第 182 条信息' }).evaluate((element: HTMLElement) => element.click())
  await page.evaluate(() => {
    let nextFrameId = 1
    const scheduled = new Map<number, FrameRequestCallback>()
    const nativeRequest = window.requestAnimationFrame
    const nativeCancel = window.cancelAnimationFrame
    Object.assign(window, {
      requestAnimationFrame(callback: FrameRequestCallback) {
        const id = nextFrameId++
        scheduled.set(id, callback)
        return id
      },
      cancelAnimationFrame(id: number) {
        scheduled.delete(id)
      },
      __flushNavigationRafGate() {
        const callbacks = [...scheduled.values()]
        scheduled.clear()
        for (const callback of callbacks) callback(performance.now())
        window.requestAnimationFrame = nativeRequest
        window.cancelAnimationFrame = nativeCancel
      },
      __navigationRafGateSize() {
        return scheduled.size
      },
    })
    void (window as typeof window & { releaseRafGateRefresh: () => Promise<void> }).releaseRafGateRefresh()
  })
  await expect(page.getByText(/旧内容在上，最新内容在下 · 50 条/)).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __navigationRafGateSize: () => number }).__navigationRafGateSize())).toBeGreaterThan(0)
  await feedScroll.evaluate((element) => {
    element.scrollTop = 0
    element.dispatchEvent(new WheelEvent('wheel', { bubbles: true }))
  })
  await page.evaluate(() => (window as typeof window & { __flushNavigationRafGate: () => void }).__flushNavigationRafGate())
  await expect.poll(() => feedScroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(2)
})

test('an immediate rail jump after inline expansion is not reclaimed one second later', async ({ page }) => {
  await page.goto('/feed')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  const anchor = await alignVisibleCardToTop(page)
  const beforeJump = await feedScroll.evaluate((element) => element.scrollTop)

  await page.evaluate(({ expandLabel, jumpLabel }) => {
    const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('button'))
    buttons.find((button) => button.getAttribute('aria-label') === expandLabel)?.click()
    buttons.find((button) => button.getAttribute('aria-label') === jumpLabel)?.click()
  }, { expandLabel: `展开 ${anchor.name}`, jumpLabel: '跳转到第 1 条信息' })
  await page.waitForTimeout(1100)

  expect(await feedScroll.evaluate((element) => element.scrollTop)).toBeLessThan(beforeJump / 2)
})

test('saved, history and legacy later are accepted by the production workbench routes', async ({ page }) => {
  await page.goto('/saved')
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: savedRouteItem.title })).toBeVisible()

  await page.goto('/history')
  await expect(page.getByRole('heading', { name: '历史', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: historyRouteItem.title })).toBeVisible()

  await page.goto('/later?mode=featured&item=saved-route-item')
  await expect(page).toHaveURL('/saved?item=saved-route-item')
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: savedRouteItem.title })).toBeVisible()
})
