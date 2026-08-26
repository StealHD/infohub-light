import { expect, test, type Locator, type Page } from '@playwright/test'

type HeaderGeometry = {
  height: number
  marginBlockStart: string
  marginInlineStart: string
  borderRadius: string
  borderTopWidth: string
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
    }
  })
}

async function installHeaderGeometryApi(page: Page, waitForAuthentication: Promise<void>, waitForFeed: Promise<void>, waitForAgent: Promise<void>) {
  await page.route('**/api/auth/status', async (route) => {
    await waitForAuthentication
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } } }),
    })
  })
  await page.route('**/api/feed/latest*', async (route) => {
    await waitForFeed
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { schema_version: 2, items: [] } }) })
  })
  await page.route('**/api/me/agent-delegations', async (route) => {
    await waitForAgent
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { enabled: true, mcp_url: '/mcp', subscription_writes_enabled: false, openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' }, token_ttl_days: 90, max_active: 5, connections: [] } }),
    })
  })
}

test('the shared page header keeps the same lightly inset capsule geometry through bootstrap takeover', async ({ page }) => {
  let releaseAuthentication = () => undefined
  let releaseFeed = () => undefined
  let releaseAgent = () => undefined
  const authenticationGate = new Promise<void>((resolve) => { releaseAuthentication = resolve })
  const feedGate = new Promise<void>((resolve) => { releaseFeed = resolve })
  const agentGate = new Promise<void>((resolve) => { releaseAgent = resolve })
  await page.addInitScript(() => {
    window.localStorage.setItem('inteliscope.ui.bootstrap-shell.v1', JSON.stringify({ userId: 'e2e-user', sidebar: 'collapsed', rightRail: 'agent', rightRailWidth: 420 }))
  })
  await installHeaderGeometryApi(page, authenticationGate, feedGate, agentGate)
  await page.goto('/feed', { waitUntil: 'domcontentloaded' })

  const bootstrapHeader = page.locator('[data-bootstrap-region="header"]')
  await expect(bootstrapHeader).toBeVisible()
  const expectedGeometry: HeaderGeometry = {
    height: 44,
    marginBlockStart: '4px',
    marginInlineStart: '8px',
    borderRadius: '999px',
    borderTopWidth: '1px',
  }
  expect(await headerGeometry(bootstrapHeader)).toEqual(expectedGeometry)

  releaseAuthentication()
  const bootstrapShell = page.locator('#inteliscope-bootstrap-shell')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(bootstrapShell).toHaveCount(0)
  const pageHeader = page.locator('header[data-header-visual="quiet-studio"]')
  await expect(pageHeader).toBeVisible()
  expect(await headerGeometry(pageHeader)).toEqual(expectedGeometry)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  releaseFeed()
  releaseAgent()
})
