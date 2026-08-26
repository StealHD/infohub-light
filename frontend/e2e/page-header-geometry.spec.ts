import { expect, test, type Locator, type Page } from '@playwright/test'

import { installProductionWorkbenchApiMocks } from './productionWorkbenchApiMocks'

const scrollingItems = Array.from({ length: 12 }, (_, index) => ({
  id: `header-scroll-${index}`,
  title: `标题穿透验收条目 ${index + 1}`,
  url: `https://example.com/header-scroll-${index}`,
  source: 'Header fixture',
  source_type: 'rss',
  summary_zh: `用于验证内容真实滚到玻璃标题背后的固定摘要 ${index + 1}`,
  published_at: new Date(Date.UTC(2026, 7, 26, 0, index)).toISOString(),
  channel: '测试',
  topics: ['标题穿透'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
}))
const scrollingFixtures = {
  items: scrollingItems,
  rollingItem: { ...scrollingItems[0], id: 'header-scroll-rolling' },
  batchRollingItems: [],
  savedRouteItem: { ...scrollingItems[0], id: 'header-scroll-saved', user_state: { ...scrollingItems[0].user_state, is_saved: true } },
  historyRouteItem: { ...scrollingItems[0], id: 'header-scroll-history' },
  tsuchaHistoryItems: [{ ...scrollingItems[0], id: 'header-scroll-tsucha' }],
  socialRouteItem: { ...scrollingItems[0], id: 'header-scroll-social' },
}

type HeaderGeometry = {
  height: number
  marginBlockStart: string
  marginInlineStart: string
  borderRadius: string
  borderTopWidth: string
  borderBottomWidth: string
  boxShadow: string
}

type CanvasGeometry = {
  top: number
  paddingTop: string
}

async function headerGeometry(header: Locator): Promise<HeaderGeometry> {
  return header.evaluate((element) => {
    const style = getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return {
      height: Math.round(rect.height),
      marginBlockStart: style.marginBlockStart,
      marginInlineStart: style.marginInlineStart,
      borderRadius: style.borderTopLeftRadius,
      borderTopWidth: style.borderTopWidth,
      borderBottomWidth: style.borderBottomWidth,
      boxShadow: style.boxShadow,
    }
  })
}

async function canvasGeometry(canvas: Locator): Promise<CanvasGeometry> {
  return canvas.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      top: Math.round(element.getBoundingClientRect().top),
      paddingTop: style.paddingTop,
    }
  })
}

async function installHeaderGeometryApi(page: Page, waitForAuthentication: Promise<void>, waitForFeed: Promise<void>, waitForAgent: Promise<void>, feedItems: unknown[] = []) {
  await installProductionWorkbenchApiMocks(page, scrollingFixtures)
  await page.route('**/api/auth/status', async (route) => {
    await waitForAuthentication
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } } }),
    })
  })
  await page.route('**/api/feed/latest*', async (route) => {
    await waitForFeed
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { schema_version: 2, items: feedItems } }) })
  })
  await page.route('**/api/me/agent-delegations', async (route) => {
    await waitForAgent
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { enabled: true, mcp_url: '/mcp', subscription_writes_enabled: false, openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5, connections: [] } }),
    })
  })
}

test('the shared transparent rounded header keeps its geometry through bootstrap takeover', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let releaseAuthentication = () => undefined
  let releaseFeed = () => undefined
  let releaseAgent = () => undefined
  const authenticationGate = new Promise<void>((resolve) => { releaseAuthentication = resolve })
  const feedGate = new Promise<void>((resolve) => { releaseFeed = resolve })
  const agentGate = new Promise<void>((resolve) => { releaseAgent = resolve })
  await page.addInitScript(() => {
    window.localStorage.setItem('inteliscope.ui.bootstrap-shell.v1', JSON.stringify({ userId: 'e2e-user', sidebar: 'collapsed', rightRail: 'agent', rightRailWidth: 420 }))
  })
  await installHeaderGeometryApi(page, authenticationGate, feedGate, agentGate, scrollingItems)
  await page.goto('/feed', { waitUntil: 'domcontentloaded' })

  const bootstrapHeader = page.locator('[data-bootstrap-region="header"]')
  await expect(bootstrapHeader).toBeVisible()
  const expectedGeometry: HeaderGeometry = {
    height: 44,
    marginBlockStart: '4px',
    marginInlineStart: '8px',
    borderRadius: '999px',
    borderTopWidth: '1px',
    borderBottomWidth: '1px',
    boxShadow: 'none',
  }
  expect(await headerGeometry(bootstrapHeader)).toEqual(expectedGeometry)
  expect(await canvasGeometry(page.locator('.bootstrap-shell-main'))).toEqual({ top: 0, paddingTop: '0px' })

  releaseAuthentication()
  const bootstrapShell = page.locator('#inteliscope-bootstrap-shell')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(bootstrapShell).toHaveCount(0)
  const pageHeader = page.locator('header[data-header-visual="quiet-studio"]')
  await expect(pageHeader).toBeVisible()
  await expect.poll(() => headerGeometry(pageHeader)).toEqual(expectedGeometry)
  await expect.poll(() => canvasGeometry(page.locator('[data-page-canvas]'))).toEqual({ top: 0, paddingTop: '0px' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  releaseFeed()
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  const firstCard = page.getByTestId('workbench-card').first()
  await expect(firstCard).toBeVisible()
  await expect.poll(() => canvasGeometry(feedScroll)).toMatchObject({ top: 0 })
  expect(Number.parseFloat((await canvasGeometry(feedScroll)).paddingTop)).toBeGreaterThan(52)
  const initialHeader = await pageHeader.boundingBox()
  const initialCard = await firstCard.boundingBox()
  if (!initialHeader || !initialCard) throw new Error('header and first Feed card must have layout boxes')
  expect(initialCard.y).toBeGreaterThanOrEqual(initialHeader.y + initialHeader.height)
  await feedScroll.evaluate((element, scrollTop) => { element.scrollTop = scrollTop }, Math.max(1, Math.round(initialCard.y - initialHeader.y - 20)))
  await expect.poll(async () => {
    const [header, card] = await Promise.all([pageHeader.boundingBox(), firstCard.boundingBox()])
    return Boolean(header && card && card.y < header.y + header.height && card.y + card.height > header.y)
  }, { message: 'real Feed content must scroll behind the glass header' }).toBe(true)
  expect(await pageHeader.evaluate((element) => getComputedStyle(element).backdropFilter)).not.toBe('none')
  expect(await page.evaluate(() => document.elementFromPoint(innerWidth / 2, 24)?.closest('[data-page-header]') !== null)).toBe(true)
  await expect(page).toHaveScreenshot('page-header-scroll-through.png', {
    animations: 'disabled',
    clip: { x: 0, y: 0, width: page.viewportSize()!.width, height: 160 },
  })
  releaseAgent()
})

test('every authenticated route family boots with the same transparent rounded header geometry', async ({ page }) => {
  const authenticationGate = new Promise<void>(() => undefined)
  const agentGate = new Promise<void>(() => undefined)
  await installHeaderGeometryApi(page, authenticationGate, Promise.resolve(), agentGate)

  const expectedGeometry: HeaderGeometry = {
    height: 44,
    marginBlockStart: '4px',
    marginInlineStart: '8px',
    borderRadius: '999px',
    borderTopWidth: '1px',
    borderBottomWidth: '1px',
    boxShadow: 'none',
  }
  for (const route of ['/feed', '/history', '/subscriptions', '/agents', '/settings']) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    expect(await headerGeometry(page.locator('[data-bootstrap-region="header"]'))).toEqual(expectedGeometry)
    expect(await canvasGeometry(page.locator('.bootstrap-shell-main'))).toEqual({ top: 0, paddingTop: '0px' })
  }
})
