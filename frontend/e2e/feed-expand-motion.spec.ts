import { expect, test } from '@playwright/test'
import { installProductionWorkbenchApiMocks } from './productionWorkbenchApiMocks'

const feedItem = {
  id: 'motion-item',
  title: '展开运动测试条目',
  url: 'https://example.com/motion-item',
  source: 'OpenAI Blog',
  source_type: 'rss',
  summary_zh: '用于验证展开按钮按压期间保持固定尺寸。',
  media_urls: ['/api/media/motion-item'],
  published_at: '2026-09-01T00:00:00Z',
  channel: 'AI',
  topics: ['交互'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
}

test.beforeEach(async ({ page }) => {
  await installProductionWorkbenchApiMocks(page, {
    items: [feedItem],
    rollingItem: { ...feedItem, id: 'motion-item-next' },
    batchRollingItems: [],
    savedRouteItem: feedItem,
    historyRouteItem: feedItem,
    tsuchaHistoryItems: [feedItem, feedItem],
    socialRouteItem: feedItem,
  })
})

test.afterEach(async ({ page }) => {
  if (page.isClosed()) return
  await page.evaluate(() => (window as typeof window & {
    completeManualFeedReload: () => Promise<void>
  }).completeManualFeedReload())
  await page.unrouteAll({ behavior: 'wait' })
})

test('source overview article disclosure keeps fixed geometry through pointer press', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Pointer press geometry is covered once on desktop.')
  await page.goto('/feed')
  await expect(page.getByRole('article', { name: feedItem.title })).toBeVisible()
  await page.getByRole('tab', { name: '专题速览' }).click()
  await page.getByRole('button', { name: `展开专题 ${feedItem.source}` }).click()
  await page.getByTestId('workbench-feed-scroll').evaluate(async () => {
    for (let frame = 0; frame < 36; frame += 1) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    }
  })
  const card = page.getByRole('article', { name: feedItem.title })
  const trigger = card.getByRole('button', { name: `展开 ${feedItem.title}` })
  await trigger.scrollIntoViewIfNeeded()
  const before = await trigger.boundingBox()
  expect(before).not.toBeNull()

  await page.mouse.move(before!.x + before!.width / 2, before!.y + before!.height / 2)
  await page.mouse.down()
  const pressed = await trigger.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return {
      transform: getComputedStyle(element).transform,
      width: bounds.width,
      height: bounds.height,
    }
  })
  expect(pressed.transform).toBe('none')
  expect(Math.abs(pressed.width - before!.width)).toBeLessThanOrEqual(0.5)
  expect(Math.abs(pressed.height - before!.height)).toBeLessThanOrEqual(0.5)
  await page.mouse.up()
  await expect(card).toHaveAttribute('data-card-expanded', 'true')
  await expect(card.getByRole('button', { name: `收起 ${feedItem.title}` })).toBeVisible()
})

test('copy summary shows a check and anchored success feedback before resetting', async ({ context, page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Copy feedback geometry is covered once on desktop.')
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/feed')
  const card = page.getByRole('article', { name: feedItem.title })
  await expect(card).toBeVisible()
  await card.hover()
  const copy = card.getByRole('button', { name: `复制摘要 ${feedItem.title}` })
  await copy.click()

  await expect(copy).toHaveAttribute('data-copy-state', 'success')
  await expect(copy.locator('.lucide-check')).toBeVisible()
  const feedback = page.getByRole('tooltip').filter({ hasText: '已复制' })
  await expect(feedback).toBeVisible()
  const [copyBounds, feedbackBounds] = await Promise.all([copy.boundingBox(), feedback.boundingBox()])
  expect(copyBounds).not.toBeNull()
  expect(feedbackBounds).not.toBeNull()
  expect(copyBounds!.y - (feedbackBounds!.y + feedbackBounds!.height)).toBeGreaterThanOrEqual(2)

  await expect.poll(() => copy.getAttribute('data-copy-state'), { timeout: 3500 }).toBe('idle')
  await expect(copy.locator('.lucide-copy')).toBeVisible()
})
