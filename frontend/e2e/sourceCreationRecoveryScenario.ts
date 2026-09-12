import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

type RecoveryApiState = {
  youtubeCreatePayloads: () => Array<Record<string, unknown>>
}

type MockAdminApi = (page: Page, authenticated: boolean, options: {
  youtubeSubscribeFailures: number
}) => Promise<RecoveryApiState>

export function registerSourceCreationRecoveryTest(mockAdminApi: MockAdminApi) {
  test('source creation keeps its draft and retries only subscription after a partial failure', async ({ page }) => {
    let subscribeRequests = 0
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/catalog/sources/source-youtube/subscribe') subscribeRequests += 1
    })
    const apiState = await mockAdminApi(page, true, { youtubeSubscribeFailures: 1 })
    await page.goto('/subscriptions')
    await page.getByRole('button', { name: '新增来源' }).click()
    const dialog = page.getByRole('dialog', { name: '新增来源' })
    await dialog.getByRole('button', { name: '来源类型' }).click()
    await page.getByRole('option', { name: 'YouTube 频道' }).click()
    const name = dialog.getByRole('textbox', { name: '来源名称' })
    const target = dialog.getByRole('textbox', { name: 'YouTube 频道地址或 @handle' })
    await name.fill('保留的频道名称')
    await target.fill('@GoogleDevelopers')
    await dialog.getByRole('button', { name: '创建并订阅' }).click()

    await expect(dialog.getByText('来源身份升级尚未完成')).toBeVisible()
    await expect(dialog.getByText('来源已保存，等待订阅')).toBeVisible()
    await expect(dialog.getByText(/来源设置已保留，重试只会恢复订阅/)).toBeVisible()
    await expect(dialog.getByText(/unsafe database identity detail/)).toHaveCount(0)
    await expect(name).toHaveValue('保留的频道名称')
    await expect(target).toHaveValue('@GoogleDevelopers')
    await expect(name).toBeDisabled()
    await expect(target).toBeDisabled()
    await expect(dialog.getByRole('button', { name: '来源类型' })).toBeDisabled()
    expect(apiState.youtubeCreatePayloads()).toHaveLength(1)
    expect(subscribeRequests).toBe(1)
    const accessibility = await new AxeBuilder({ page }).analyze()
    expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

    await dialog.getByRole('button', { name: '重试订阅' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByText('来源与订阅已就绪', { exact: true })).toBeVisible()
    expect(apiState.youtubeCreatePayloads()).toHaveLength(1)
    expect(subscribeRequests).toBe(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  })
}

export function youtubeSubscriptionResult(userId: string) {
  return {
        subscription: {
          id: 'subscription-youtube',
          user_id: userId,
          source_id: 'source-youtube',
          source_display_name: 'Google Developers',
          source_type: 'rss',
          enabled: true,
          analysis_mode: 'full',
          priority: 0,
        },
      }
}
