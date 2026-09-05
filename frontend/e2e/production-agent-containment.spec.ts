import { expect, test, type Page } from '@playwright/test'
import { installAgentApi, installGatewayFixture } from './agentWorkspaceFixtures'

const longSession = 'agent:main:dashboard:2e8065c0-d037-4b1f-8453-29ba1cfb4ade-没有空格的完整会话标识'.repeat(3)
async function connect(page: Page, directory = false) {
  await installAgentApi(page, true)
  await installGatewayFixture(page, directory)
  await page.goto('/agent')
  await page.getByLabel(/Gateway token 或 dashboard 地址/u).fill('fixture-token')
  await page.getByRole('button', { name: '连接并授权' }).click()
  await expect(page.getByTestId('openclaw-composer-textarea')).toBeVisible()
}
async function sidebar(page: Page) {
  if (page.viewportSize()!.width < 1024) await page.getByRole('button', { name: '打开 OpenClaw 会话' }).click()
  return page.locator('[data-agent-workspace-sidebar]')
}

for (const theme of ['dark', 'light'] as const) test(`long Session values stay inside the inspector with separate arrow space in ${theme}`, async ({ page }, testInfo) => {
  await page.addInitScript(({ theme, longSession }) => {
    localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({ themeName: 'graphite-purple', colorMode: theme }))
    ;(window as unknown as { __sessionLabel: string }).__sessionLabel = longSession
  }, { theme, longSession })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await connect(page)
  if (page.viewportSize()!.width < 768) {
    await page.getByRole('button', { name: '打开更多操作' }).click()
    await page.getByRole('button', { name: 'Artifacts', exact: true }).click()
  } else await page.getByRole('button', { name: '打开Artifacts', exact: true }).click()
  const view = page.locator('[data-agent-artifacts-view]')
  const trigger = view.locator('.form-select-trigger')
  await expect(trigger).toBeVisible()
  const geometry = await trigger.evaluate((node) => {
    const rect = (element: Element) => { const b = element.getBoundingClientRect(); return { x: b.x, right: b.right, y: b.y, bottom: b.bottom } }
    const value = node.querySelector('.select__value')!
    return { control: rect(node), value: rect(value), arrow: rect(node.querySelector('.select__indicator')!), clipping: getComputedStyle(value).overflowX, view: rect(node.closest('[data-agent-artifacts-view]')!) }
  })
  expect(geometry.control.x).toBeGreaterThanOrEqual(geometry.view.x)
  expect(geometry.control.right).toBeLessThanOrEqual(geometry.view.right)
  expect(geometry.value.right + 4).toBeLessThanOrEqual(geometry.arrow.x)
  expect(geometry.value.bottom).toBeLessThanOrEqual(geometry.control.bottom)
  expect(geometry.clipping).toBe('hidden')
  await trigger.click()
  const option = page.getByRole('option', { name: longSession, exact: true })
  await expect(option).toBeVisible()
  expect(await option.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true)
  const optionBounds = await option.boundingBox()
  expect(optionBounds!.x + optionBounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  await page.keyboard.press('Escape'); await expect(trigger).toBeFocused()
  expect(await view.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath(`artifact-long-${theme}.png`) })
})

test('expanded workspaces share one sidebar width and a compact contained switcher', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'expanded Feed sidebar is a desktop role')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await connect(page)
  const agentRail = await page.getByRole('complementary', { name: 'OpenClaw 会话', exact: true }).boundingBox()
  await page.getByRole('button', { name: '切换工作区，当前为 OpenClaw' }).click()
  const menu = page.getByRole('dialog', { name: '切换工作区', exact: true })
  const bounds = await menu.boundingBox()
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(agentRail!.x + agentRail!.width)
  await expect(menu.getByRole('button').first().locator('.type-control')).toHaveCSS('font-size', '13px')
  await page.screenshot({ path: testInfo.outputPath('workspace-switcher.png') })
  await menu.getByRole('button', { name: /Inscope.*订阅、阅读与追踪/u }).click()
  const feedRail = page.locator('[data-desktop-sidebar]')
  if (await feedRail.getAttribute('data-sidebar-state') !== 'expanded') await page.getByRole('button', { name: '展开侧栏', exact: true }).click()
  await expect(feedRail).toHaveCSS('width', `${agentRail!.width}px`)
  const brand = page.getByRole('button', { name: '切换工作区，当前为 Inscope' })
  const mark = brand.locator('svg').first()
  await expect(mark).toBeVisible()
  await expect(mark).toHaveClass(/text-accent/u)
  expect((await mark.boundingBox())!.width).toBe(18)
  expect(await brand.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('workspace-brand-accent.png') })
})

test('current and historical sessions return from Skills, while failed switches retain the page', async ({ page }) => {
  await connect(page, true)
  const input = page.getByTestId('openclaw-composer-textarea')
  await input.fill('保留 Skills 返回前的草稿')
  let rail = await sidebar(page)
  await expect(rail.getByRole('button', { name: '打开会话：历史记录 000', exact: true })).toBeVisible()
  const originalSession = await rail.locator('[data-agent-session-row] button[aria-current="true"]').getAttribute('aria-label')
  await rail.getByRole('link', { name: 'Skills', exact: true }).click()
  await expect(page).toHaveURL(/\/agent\/skills$/u)
  rail = await sidebar(page)
  await rail.locator('[data-agent-session-row] button[aria-current="true"]').click()
  await expect(page).toHaveURL(/\/agent$/u)
  await expect(input).toHaveValue('保留 Skills 返回前的草稿')
  rail = await sidebar(page)
  await rail.getByRole('link', { name: 'Skills', exact: true }).click()
  rail = await sidebar(page)
  await page.evaluate(() => { (window as unknown as { __failHistory: boolean }).__failHistory = true })
  await rail.getByRole('button', { name: '打开会话：历史记录 000', exact: true }).click()
  await expect(page.getByText('无法切换会话', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/agent\/skills$/u)
  await expect(rail.locator('[data-agent-session-row] button[aria-current="true"]')).toHaveAttribute('aria-label', originalSession!)
  await page.evaluate(() => { (window as unknown as { __failHistory: boolean }).__failHistory = false })
  await rail.getByRole('button', { name: '打开会话：历史记录 000', exact: true }).click()
  await expect(page).toHaveURL(/\/agent$/u)
  rail = await sidebar(page)
  await expect(rail.getByRole('button', { name: '打开会话：历史记录 000', exact: true })).toHaveAttribute('aria-current', 'true')
})
