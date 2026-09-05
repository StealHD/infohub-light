import { expect, test, type Locator } from '@playwright/test'
import { installAgentApi, installGatewayFixture } from './agentWorkspaceFixtures'

async function positions(rail: Locator) {
  return rail.evaluate((node) => [...node.querySelectorAll('[data-agent-session-row], nav a')].map((element) => {
    const { x, y, width, height } = element.getBoundingClientRect()
    return { x, y, width, height, text: element.querySelector('button[aria-label^="打开会话"]')?.getAttribute('aria-label') ?? element.textContent }
  }))
}

for (const reducedMotion of ['no-preference', 'reduce'] as const) test(`sidebar stays stationary during session switching with ${reducedMotion}`, async ({ page }, testInfo) => {
  test.skip(page.viewportSize()!.width < 1024, 'persistent sidebar geometry')
  await page.emulateMedia({ reducedMotion })
  await installAgentApi(page, true)
  await installGatewayFixture(page, true)
  await page.goto('/agent')
  await page.getByLabel(/Gateway token 或 dashboard 地址/u).fill('fixture-token')
  await page.getByRole('button', { name: '连接并授权' }).click()
  const rail = page.locator('[data-agent-workspace-sidebar]')
  const target = rail.getByRole('button', { name: '打开会话：历史记录 000', exact: true })
  await expect(target).toBeVisible()
  const originalRail = await rail.elementHandle()
  await rail.getByRole('link', { name: 'Skills', exact: true }).click()
  await expect(page).toHaveURL(/\/agent\/skills$/u)
  expect(await originalRail!.evaluate((node) => node.isConnected)).toBe(true)
  await expect(target).toBeVisible()
  for (const name of ['Automations', '使用示例', 'Skills']) {
    const link = rail.getByRole('link', { name, exact: true })
    await link.focus(); await link.press('Enter')
    await expect(link).toHaveAttribute('aria-current', 'page')
    expect(await originalRail!.evaluate((node) => node.isConnected)).toBe(true)
  }
  await page.evaluate(() => { (window as unknown as { __holdHistory: boolean }).__holdHistory = true })
  const before = await positions(rail)
  await target.click()
  await expect.poll(() => page.evaluate(() => typeof (window as unknown as { __releaseHistory?: () => void }).__releaseHistory)).toBe('function')
  expect(await positions(rail)).toEqual(before)
  await page.screenshot({ path: testInfo.outputPath('sidebar-pending.png') })
  await page.evaluate(() => { (window as unknown as { __releaseHistory: () => void }).__releaseHistory() })
  await expect(target).toHaveAttribute('aria-current', 'true')
  expect(await positions(rail)).toEqual(before)
  await page.evaluate(() => {
    const fixture = window as unknown as { __holdHistory: boolean; __failHistory: boolean }
    fixture.__holdHistory = false; fixture.__failHistory = true
  })
  await rail.getByRole('button', { name: '打开会话：历史记录 001', exact: true }).click()
  await expect(page.getByText('无法切换会话', { exact: true })).toBeVisible()
  expect(await positions(rail)).toEqual(before)
  expect(await originalRail!.evaluate((node) => node.isConnected)).toBe(true)
})

test('sidebar action keeps its rectangle while pointer is held down', async ({ page }) => {
  test.skip(page.viewportSize()!.width < 1024, 'persistent sidebar pointer geometry')
  await installAgentApi(page, true)
  await installGatewayFixture(page, true)
  await page.goto('/agent')
  const button = page.getByRole('button', { name: '切换工作区，当前为 OpenClaw' })
  const before = await button.boundingBox()
  await button.hover()
  await page.mouse.down()
  const boxes = await button.evaluate(async (node) => {
    const result = []
    for (let frame = 0; frame < 24; frame++) {
      await new Promise(requestAnimationFrame)
      const { x, y, width, height } = node.getBoundingClientRect()
      result.push({ x, y, width, height })
    }
    return result
  })
  await page.mouse.up()
  for (const box of boxes) for (const axis of ['x', 'y', 'width', 'height'] as const) expect(Math.abs(box[axis] - before![axis])).toBeLessThanOrEqual(1)
})
