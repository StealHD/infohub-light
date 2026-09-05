import { expect, test } from '@playwright/test'
import { installShortcutFixture, shortcutRequests } from './fixtures/agent-shortcuts'

test('an unpaired browser explains first connection without claiming token rejection', async ({ page }) => {
  await installShortcutFixture(page)
  await page.goto('/agent')
  await page.getByRole('button', { name: '使用已配对设备重连' }).click()
  await expect(page.getByText('当前地址尚未配对。请填写 OpenClaw Gateway token，完成首次连接。')).toBeVisible()
  await expect(page.getByText('OpenClaw Gateway token 无效或已轮换。')).not.toBeVisible()
  expect((await shortcutRequests(page)).filter((request) => request.method === 'connect')).toHaveLength(0)
  await expect(page.getByLabel(/Gateway token 或 dashboard 地址/u)).toBeEditable()
})
