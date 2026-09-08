import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { emptyInformationRule } from '../src/features/information-automations/informationRuleModel'
import { installAgentApi } from './agentWorkspaceFixtures'

for (const colorMode of ['light', 'dark'] as const) test(`personal reminder draft, keyboard confirmation and test preview stay separate (${colorMode})`, async ({ page }, testInfo) => {
  await installAgentApi(page)
  await page.addInitScript((colorMode) => localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({ themeName: 'graphite-purple', colorMode })), colorMode)
  await page.emulateMedia({ colorScheme: colorMode, reducedMotion: 'reduce' })
  const rule = { id: 'iar_' + 'a'.repeat(32), version: 1, state: 'draft', issue: null,
    config: { ...emptyInformationRule(), name: '研究提醒', source_ids: ['source'], target_id: 'target', requirement: 'Find research', model: { id: 'test/model', thinking: null } }, created_at: '2026-09-08', updated_at: '2026-09-08', confirmed_at: null }
  let activations = 0
  let tests = 0
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path === '/api/me/information-automations') data = { items: [rule], has_more: false, next_offset: null }
    else if (path.endsWith('/models')) data = { status: 'ready', updated_at: '2026-09-08', models: [{ id: 'test/model', name: 'Test', thinking_levels: [] }] }
    else if (path.endsWith('/transition')) { activations += 1; rule.state = 'active'; data = rule }
    else if (path.endsWith('/test')) { tests += 1; data = { version: 1, results: [{ article_id: 'article', status: 'matched' }], sends_notification: false, advances_cursor: false } }
    else if (path.endsWith('/' + rule.id) && route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON(); rule.config = payload.config; rule.version += 1; data = rule
    } else if (path === '/api/me/subscriptions') data = { subscriptions: [{ source_id: 'source', source_display_name: '研究来源', source_type: 'X', enabled: true }] }
    else if (path === '/api/notification-services') data = { services: [{ id: 'target', name: '本机测试目标', available: true }] }
    else if (path === '/api/feed/latest') data = { schema_version: 2, items: [{ id: 'article', title: 'AI 研究结果', source_id: 'source' }] }
    else return route.fallback()
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  await page.goto('/agent/automations')
  await page.getByRole('button', { name: '查看与编辑' }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('研究提醒')
  await page.getByRole('checkbox', { name: 'AI 研究结果' }).focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('checkbox', { name: 'AI 研究结果' })).toBeChecked()
  await page.getByRole('button', { name: '测试已保存规则' }).click()
  await expect(page.getByText('版本 1 测试结果 · 未发送通知')).toBeVisible()
  expect(tests).toBe(1); expect(activations).toBe(0)
  await expect(page.getByText('判断方式', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /触发方式/ }).click()
  await page.getByRole('option', { name: '累计条数', exact: true }).click()
  await expect(page.getByLabel('累计多少条后分析')).toHaveValue('5')
  await page.getByLabel('累计多少条后分析').fill('8')
  await page.getByText('设置最长等待时间', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '设置最长等待时间' })).not.toBeChecked()
  await expect(page.getByLabel('最长等待（分钟）')).toHaveCount(0)
  await page.getByRole('button', { name: /触发方式/ }).click()
  await page.getByRole('option', { name: '固定时间', exact: true }).click()
  await expect(page.getByLabel('时间', { exact: true })).toHaveValue('08:00')
  await page.getByRole('button', { name: /重复/ }).click()
  await page.getByRole('option', { name: '每周', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '周一', exact: true })).toBeChecked()
  await page.getByRole('button', { name: /触发方式/ }).click()
  await page.getByRole('option', { name: '固定间隔', exact: true }).click()
  await expect(page.getByLabel('处理间隔', { exact: true })).toHaveValue('1')
  await page.getByLabel('任务名称').fill('未保存草稿')
  await page.getByRole('button', { name: '刷新提醒列表' }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('未保存草稿')
  await page.reload()
  await page.getByRole('button', { name: '查看与编辑' }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('未保存草稿')
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByRole('button', { name: '确认启用' })).toBeEnabled()
  await page.getByRole('button', { name: '确认启用' }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible(); expect(activations).toBe(0)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(activations).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const scan = await new AxeBuilder({ page }).analyze()
  expect(scan.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
  await page.getByRole('button', { name: '收起', exact: true }).click()
  await page.getByRole('button', { name: '新建自动化', exact: true }).click()
  await page.getByLabel('任务名称').fill('新建中的本地草稿')
  await page.reload()
  await page.getByRole('button', { name: '新建自动化', exact: true }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('新建中的本地草稿')
  await page.getByLabel('任务名称').scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('information-reminder.png') })
})
