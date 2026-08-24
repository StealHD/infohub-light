import { expect, test, type Page } from '@playwright/test'

type ManagementSource = 'secret_store' | 'environment' | 'none'

const owner = { id: 'owner-rsshub', username: 'owner', role: 'owner', enabled: true }
const config = {
  config: {
    rsshub: { base_url: 'https://rsshub.example.test/prefix' },
    filtering: { time_window_hours: 24, feed_window_days: 7, rss_initial_fetch_window_hours: 168, recent_item_limit: 20 },
    tags: ['AI'],
  },
  taxonomy: { topics: ['AI'] },
}

async function mockRsshubSettings(page: Page, initialSource: ManagementSource = 'none') {
  let source = initialSource
  const writes: Array<{ method: string; payload: unknown }> = []
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: owner }
    else if (url.pathname === '/api/config') data = config
    else if (url.pathname === '/api/admin/rsshub-access-key') {
      if (request.method() === 'PUT') {
        writes.push({ method: 'PUT', payload: request.postDataJSON() })
        source = 'secret_store'
      } else if (request.method() === 'DELETE') {
        writes.push({ method: 'DELETE', payload: null })
        source = 'none'
      }
      data = { configured: source !== 'none', management_source: source }
    } else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found' } }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  return { writes: () => writes }
}

test('RSSHub service card stays aligned and keeps its key write-only at supported widths', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'This test sets the three supported viewport widths directly.')
  const state = await mockRsshubSettings(page)
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/settings/fetching')
    await expect(page.getByRole('heading', { name: 'RSSHub 服务' })).toBeVisible()
    await expect(page.getByText('未配置', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '配置访问密钥' })).toBeVisible()
    await expect(page.getByRole('button', { name: '保存 RSSHub 地址' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }

  const secret = 'rsshub-write-only-value'
  await page.getByRole('button', { name: '配置访问密钥' }).click()
  const dialog = page.getByRole('dialog', { name: '配置 RSSHub 访问密钥' })
  await dialog.getByLabel('访问密钥').fill(secret)
  await dialog.getByRole('button', { name: '保存访问密钥' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: '更新访问密钥' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText(secret)
  expect(state.writes()).toEqual([{ method: 'PUT', payload: { value: secret } }])

  await page.getByRole('button', { name: '更新访问密钥' }).click()
  await page.getByRole('button', { name: '移除访问密钥' }).click()
  const removeDialog = page.getByRole('dialog', { name: '移除 RSSHub 访问密钥？' })
  await expect(removeDialog.getByText('RSSHub 地址和现有订阅不会被删除。')).toBeVisible()
  await removeDialog.getByRole('button', { name: '确认移除' }).click()
  await expect(page.getByRole('button', { name: '配置访问密钥' })).toBeFocused()
  expect(state.writes()).toEqual([
    { method: 'PUT', payload: { value: secret } },
    { method: 'DELETE', payload: null },
  ])
})

test('environment-managed RSSHub access keys are status-only in the browser', async ({ page }) => {
  await mockRsshubSettings(page, 'environment')
  await page.goto('/settings/fetching')

  await expect(page.getByText('环境托管', { exact: true })).toBeVisible()
  await expect(page.getByText('由部署环境管理', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '配置访问密钥' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '更新访问密钥' })).toHaveCount(0)
})
