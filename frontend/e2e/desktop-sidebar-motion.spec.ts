import { expect, test, type Page } from '@playwright/test'

import { installProductionWorkbenchApiMocks, suppressAutomaticWorkbenchInsights } from './productionWorkbenchApiMocks'

const sidebarFixtures = {
  items: [],
  rollingItem: { id: 'sidebar-item', user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false } },
  batchRollingItems: [],
  savedRouteItem: { id: 'saved-item', user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false } },
  historyRouteItem: { id: 'history-item', user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false } },
  tsuchaHistoryItems: [],
  socialRouteItem: { id: 'social-item', user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false } },
}

async function openCollapsedDesktopSidebar(page: Page) {
  await installProductionWorkbenchApiMocks(page, sidebarFixtures)
  await suppressAutomaticWorkbenchInsights(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('inteliscope.ui.sidebar.v1:e2e-user', 'collapsed')
  })
  await page.goto('/feed')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(page.getByRole('complementary', { name: '桌面导航' })).toHaveAttribute('data-sidebar-state', 'collapsed')
}

test('desktop sidebar expands with fixed canvases and a stable account anchor', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The fixed-canvas motion is a wide-desktop contract.')
  await openCollapsedDesktopSidebar(page)

  const sidebar = page.getByRole('complementary', { name: '桌面导航' })
  const shell = page.getByTestId('live-workbench-shell')
  const toggle = page.getByRole('button', { name: '展开侧栏' })
  const accountStrip = sidebar.locator('[data-sidebar-account-strip]')
  const expandedLayer = sidebar.locator('[data-sidebar-layer="expanded"]')
  const expandedLabel = expandedLayer.getByRole('link', { name: '信息流' }).locator('span')

  const samplesPromise = page.evaluate(() => new Promise<Array<{ accountY: number; canvasWidth: number; labelHeight: number; sidebarWidth: number }>>((resolve) => {
    const sidebar = document.querySelector<HTMLElement>('[data-desktop-sidebar]')
    const layer = document.querySelector<HTMLElement>('[data-sidebar-layer="expanded"]')
    const label = layer?.querySelector<HTMLElement>('[data-sidebar-nav-item="expanded"] span')
    const account = document.querySelector<HTMLElement>('[data-sidebar-account-strip]')
    const samples: Array<{ accountY: number; canvasWidth: number; labelHeight: number; sidebarWidth: number }> = []
    const startedAt = performance.now()
    const sample = () => {
      if (!sidebar || !layer || !label || !account) return resolve(samples)
      samples.push({
        accountY: account.getBoundingClientRect().y,
        canvasWidth: Number.parseFloat(getComputedStyle(layer).width),
        labelHeight: label.getBoundingClientRect().height,
        sidebarWidth: sidebar.getBoundingClientRect().width,
      })
      if (performance.now() - startedAt < 320) requestAnimationFrame(sample)
      else resolve(samples)
    }
    requestAnimationFrame(sample)
  }))

  await toggle.click()
  const samples = await samplesPromise
  await expect(sidebar).toHaveAttribute('data-sidebar-state', 'expanded')
  await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width ?? 0)).toBe(232)
  expect(await accountStrip.evaluate((element) => element.classList.contains('h-[var(--inteliscope-size-sidebar-footer)]') && element.classList.contains('shrink-0'))).toBe(true)
  await expect(expandedLayer).not.toHaveAttribute('aria-hidden')
  await expect(expandedLabel).toBeVisible()
  expect(samples.length).toBeGreaterThan(3)
  expect(samples.every((sample) => Math.round(sample.canvasWidth) === 232)).toBe(true)
  expect(samples.every((sample) => sample.labelHeight <= 24)).toBe(true)
  expect(Math.max(...samples.map((sample) => sample.accountY)) - Math.min(...samples.map((sample) => sample.accountY))).toBeLessThanOrEqual(1)
  expect(samples.every((sample, index) => index === 0 || sample.sidebarWidth >= samples[index - 1].sidebarWidth - 1)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect(await shell.evaluate((element) => !element.querySelector('.quiet-surface-enter'))).toBe(true)
})

test('desktop sidebar reverses cleanly and preserves reduced-motion, breakpoint, and overflow behavior', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The desktop rail owns this interaction.')
  await openCollapsedDesktopSidebar(page)

  const sidebar = page.getByRole('complementary', { name: '桌面导航' })
  await page.getByRole('button', { name: '展开侧栏' }).click()
  await page.waitForTimeout(70)
  await page.getByRole('button', { name: '收起侧栏' }).click()
  await expect(sidebar).toHaveAttribute('data-sidebar-state', 'collapsed')
  await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width ?? 0)).toBe(72)
  await expect(sidebar.locator('[data-sidebar-layer="expanded"]')).toHaveAttribute('aria-hidden', 'true')
  await expect(sidebar.locator('[data-sidebar-layer="expanded"]')).toHaveAttribute('inert', '')

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: '展开侧栏' }).click()
  expect(await page.getByTestId('live-workbench-shell').evaluate((element) => Number.parseFloat(getComputedStyle(element).transitionDuration))).toBeLessThanOrEqual(0.0001)
  await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width ?? 0)).toBe(232)

  await page.setViewportSize({ width: 1359, height: 900 })
  await expect(page.getByRole('button', { name: '展开导航' })).toBeVisible()
  await expect(page.getByRole('button', { name: /侧栏/ })).toHaveCount(0)

  await page.setViewportSize({ width: 1440, height: 360 })
  const navigation = page.getByRole('complementary', { name: '桌面导航' }).locator('[data-sidebar-layer="expanded"] nav')
  await expect.poll(async () => navigation.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true)
  await navigation.evaluate((element) => { element.scrollTop = element.scrollHeight })
  expect(await navigation.evaluate((element) => element.scrollTop > 0)).toBe(true)
})
