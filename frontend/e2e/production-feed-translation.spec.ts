import { expect, test, type Page } from '@playwright/test'
import { installProductionWorkbenchApiMocks, suppressAutomaticWorkbenchInsights } from './productionWorkbenchApiMocks'

const original = 'Original paragraph with numbers 42 and https://example.test.\n\nSecond paragraph.'
const item = {
  id: 'translation-one', title: 'Translation example', url: 'https://example.test/one',
  source: 'Translation source', source_id: 'source-tsucha', source_type: 'rss',
  published_at: '2026-07-01T08:00:00Z', channel: 'AI', topics: ['Codex'],
  user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
  presentation: { version: 2, content: { title: 'Translation example', excerpt: 'Original paragraph',
    body_text: original, body_completeness: 'captured', body_truncated: false, content_kind: 'article' } },
}

async function fixture(page: Page, items = [item]) {
  await suppressAutomaticWorkbenchInsights(page)
  await installProductionWorkbenchApiMocks(page, {
    items, rollingItem: item, batchRollingItems: [item], savedRouteItem: item,
    historyRouteItem: item, tsuchaHistoryItems: [item], socialRouteItem: item,
  })
  let calls = 0
  let translated = false
  await page.route('**/api/feed/items/*/translation', async (route) => {
    if (route.request().method() === 'POST') { calls += 1; translated = true }
    await route.fulfill({ json: { ok: true, data: {
      status: translated ? 'succeeded' : 'idle', job_id: translated ? 'job-translation' : null,
      translation: translated ? '原文段落包含数字 42 和 https://example.test。\n\n第二段。' : null,
      scope: 'body', source_truncated: false, cached: translated, error: null,
      expires_at: '2099-01-01T00:00:00Z',
    } } })
  })
  return () => calls
}

for (const path of ['/feed', '/saved', '/history']) {
  test(`${path} translates below original and restores cache after reload`, async ({ page }) => {
    const calls = await fixture(page)
    await page.goto(path)
    const card = page.getByTestId('workbench-card').first()
    const button = card.getByRole('button', { name: '翻译正文', exact: true })
    await expect(button).toBeVisible()
    const before = await button.boundingBox()
    await button.click()
    const panel = card.getByRole('region', { name: '中文翻译' })
    await expect(panel).toContainText('第二段。')
    await expect(card.getByText(original, { exact: true })).toBeVisible()
    const after = await button.boundingBox()
    expect(Math.abs((after?.width ?? 0) - (before?.width ?? 0))).toBeLessThanOrEqual(1)
    expect(calls()).toBe(1)
    await button.click()
    await expect(panel).toHaveCount(0)
    await page.reload()
    await button.click()
    await expect(panel).toContainText('第二段。')
    expect(calls()).toBe(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

test('source overview supports translation in light theme with reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    localStorage.setItem('inteliscope.ui.feed-view.v1:e2e-user', JSON.stringify('source-overview'))
    localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({ themeName: 'graphite-purple', colorMode: 'light' }))
  })
  await fixture(page)
  await page.goto('/feed')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: /展开专题/ }).first().click()
  await page.getByRole('button', { name: '翻译正文', exact: true }).first().click()
  await expect(page.getByRole('region', { name: '中文翻译' })).toContainText('第二段。')
})

test('shows task failure locally and only retries on an explicit click', async ({ page }) => {
  await fixture(page)
  let calls = 0
  await page.route('**/api/feed/items/*/translation', async (route) => {
    if (route.request().method() === 'POST') calls += 1
    await route.fulfill({ json: { ok: true, data: {
      status: calls === 0 ? 'idle' : calls === 1 ? 'failed' : 'succeeded',
      translation: calls > 1 ? '重试译文' : null, scope: 'excerpt', cached: calls > 1,
      job_id: `job-${calls}`, source_truncated: false, expires_at: null,
      error: calls === 1 ? { code: 'translation_provider_failed', message: '模型调用失败，请重试。', retryable: true } : null,
    } } })
  })
  await page.goto('/feed')
  const card = page.getByTestId('workbench-card').first()
  await card.getByRole('button', { name: '翻译正文', exact: true }).click()
  await expect(card.getByRole('alert')).toContainText('模型调用失败')
  await expect(card.getByText(original, { exact: true })).toBeVisible()
  expect(calls).toBe(1)
  await card.getByRole('button', { name: '重试翻译' }).click()
  await expect(card.getByRole('region', { name: '中文翻译' })).toContainText('重试译文')
  await expect(card.getByText('仅翻译已抓取摘录')).toBeVisible()
  expect(calls).toBe(2)
})

test('translation completion and virtual remount preserve the reading position', async ({ page }) => {
  const items = Array.from({ length: 60 }, (_, index) => ({ ...item, id: `translation-${index}`,
    title: `Translation example ${index}`, published_at: new Date(Date.UTC(2026, 6, 1, 8, index)).toISOString() }))
  await fixture(page, items)
  let calls = 0
  let complete = false
  await page.route('**/api/feed/items/*/translation', async (route) => {
    if (route.request().method() === 'POST') calls += 1
    await route.fulfill({ json: { ok: true, data: {
      status: complete ? 'succeeded' : calls ? 'running' : 'idle', job_id: calls ? 'job-virtual' : null,
      translation: complete ? '虚拟列表译文。\n\n第二段。' : null, scope: 'body',
      cached: complete, source_truncated: false, error: null, expires_at: null,
    } } })
  })
  await page.goto('/feed')
  const feed = page.getByTestId('workbench-feed-scroll')
  await expect(page.getByTestId('workbench-card').first()).toBeVisible()
  await feed.evaluate((element) => { element.scrollTop = element.scrollHeight / 2 })
  await expect.poll(() => feed.evaluate((element) => element.scrollTop)).toBeGreaterThan(500)
  const selected = await feed.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    const minimum = bounds.top + Number(element.dataset.topInset || 0)
    return Array.from(element.querySelectorAll<HTMLElement>('[data-item-id]')).find((row) => {
      const button = row.querySelector('[aria-label="翻译正文"]')?.getBoundingClientRect()
      return button && button.top >= minimum && button.bottom < bounds.bottom
    })?.dataset.itemId
  })
  expect(selected).toBeTruthy()
  const card = page.locator(`[data-item-id="${selected}"]`).getByTestId('workbench-card')
  await card.getByRole('button', { name: '翻译正文', exact: true }).click()
  await expect(card.getByRole('region', { name: '中文翻译' }).getByRole('status')).toContainText('正在翻译')
  await expect(card.getByText(original, { exact: true })).toBeVisible()
  const top = (await card.boundingBox())!.y
  complete = true
  await expect(card.getByRole('region', { name: '中文翻译' })).toContainText('虚拟列表译文')
  expect(Math.abs((await card.boundingBox())!.y - top)).toBeLessThanOrEqual(2)
  const position = await feed.evaluate((element) => element.scrollTop)
  await feed.evaluate((element) => { element.scrollTop = 0 })
  await expect(card).toHaveCount(0)
  await feed.evaluate((element, offset) => { element.scrollTop = offset }, position)
  await expect(card.getByRole('region', { name: '中文翻译' })).toContainText('虚拟列表译文')
  expect(calls).toBe(1)
})
