import { expect, test } from '@playwright/test'
import { installShortcutFixture } from './fixtures/agent-shortcuts'

for (const theme of ['dark', 'light'] as const) test(`populated conversation meets roomy composer in ${theme}`, async ({ page }, testInfo) => {
  await installShortcutFixture(page, true, true)
  await page.addInitScript((colorMode) => localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({ themeName: 'graphite-purple', colorMode })), theme)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/agent')
  await page.getByLabel(/Gateway token 或 dashboard 地址/u).fill('fixture-token')
  await page.getByRole('button', { name: '连接并授权' }).click()
  await expect(page.getByTestId('openclaw-timeline')).toContainText('第 50 段')
  const scroll = page.getByTestId('agent-scroll-region')
  const composer = page.getByTestId('openclaw-composer')
  const input = page.getByTestId('openclaw-composer-textarea')
  await input.fill('保留草稿，检查聚焦状态')
  await input.focus()
  await scroll.evaluate((node) => { node.scrollTop = node.scrollHeight / 2 })
  const region = (await scroll.boundingBox())!
  const surface = (await composer.boundingBox())!
  await page.screenshot({ path: testInfo.outputPath(`populated-composer-${theme}.png`) })
  expect(Math.abs(surface.y - region.y - region.height)).toBeLessThanOrEqual(1)
  expect(surface.height).toBeGreaterThanOrEqual(120)
  expect(surface.height).toBeLessThanOrEqual(140)
  const textarea = (await input.boundingBox())!
  expect(textarea.y - surface.y).toBeGreaterThanOrEqual(16)
  await expect(composer).toHaveCSS('outline-style', 'none')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const savedScroll = await scroll.evaluate((node) => node.scrollTop)
  await input.fill(Array.from({ length: 25 }, () => '长草稿在输入区内部滚动').join('\n'))
  expect(await input.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true)
  expect(await scroll.evaluate((node) => node.scrollTop)).toBe(savedScroll)
})
