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
    else if (path.endsWith('/test')) { tests += 1; data = { version: 1, preview_id: 'preview', status: 'pending', results: [], sends_notification: false, advances_cursor: false } }
    else if (path.endsWith('/test/preview')) data = { version: 1, preview_id: 'preview', status: 'completed', results: [{ article_id: 'article', status: 'matched' }], sends_notification: false, advances_cursor: false }
    else if (path.endsWith('/' + rule.id) && route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON(); rule.config = payload.config; rule.version += 1; data = rule
    } else if (path === '/api/me/subscriptions') data = { subscriptions: [{ source_id: 'source', source_display_name: '研究来源', source_type: 'X', enabled: true }] }
    else if (path === '/api/notification-services') data = { services: [{ id: 'target', name: '本机测试目标', available: true }] }
    else if (path === '/api/feed/latest') data = { schema_version: 2, items: [{ id: 'article', title: 'AI 研究结果', source_id: 'source' }] }
    else return route.fallback()
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  await page.goto('/agent/automations')
  await page.getByRole('button', { name: '查看与编辑 研究提醒' }).click()
  await expect(page.getByRole('tab', { name: '概览' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: '测试' }).click()
  await page.getByRole('button', { name: '选择文章' }).click()
  await page.getByRole('checkbox', { name: 'AI 研究结果' }).focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('checkbox', { name: 'AI 研究结果' })).toBeChecked()
  await page.getByRole('button', { name: '确认选择' }).click()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect(page.getByRole('tabpanel', { name: '测试' }).getByText('测试排队中')).toBeVisible()
  expect(tests).toBe(1); expect(activations).toBe(0)
  await page.getByRole('button', { name: /关闭研究提醒/ }).click()
  const taskRow = page.getByRole('button', { name: '查看与编辑 研究提醒' })
  await expect(taskRow.getByText('测试排队中')).toBeVisible()
  await expect(taskRow.getByText('测试已完成')).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: '查看与编辑 研究提醒' }).click()
  await page.getByRole('tab', { name: '测试' }).click()
  await expect(page.getByRole('tabpanel', { name: '测试' }).getByText('测试已完成')).toBeVisible()
  await page.getByRole('tab', { name: '概览' }).click()
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('研究提醒')
  await expect(page.getByText('判断方式', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /分析模型/ })).toBeVisible()
  await page.getByRole('button', { name: /触发与通知/ }).click()
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
  if (testInfo.project.name === 'desktop') await page.getByRole('button', { name: '刷新提醒列表' }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('未保存草稿')
  await page.reload()
  await page.getByRole('button', { name: '查看与编辑 研究提醒' }).click()
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('未保存草稿')
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByRole('button', { name: '确认启用' })).toBeEnabled()
  await page.getByRole('button', { name: '确认启用' }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: '确认启用“未保存草稿”' })
  await expect(dialog).toBeVisible(); expect(activations).toBe(0)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(activations).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const scan = await new AxeBuilder({ page }).analyze()
  expect(scan.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
  if (testInfo.project.name === 'desktop') {
    await page.evaluate(() => { document.documentElement.style.zoom = '2' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.evaluate(() => { document.documentElement.style.zoom = '' })
  }
  await page.getByRole('button', { name: /关闭未保存草稿/ }).click()
  await page.getByRole('button', { name: '新建自动化', exact: true }).click()
  await page.getByLabel('任务名称').fill('新建中的本地草稿')
  await page.reload()
  await page.getByRole('button', { name: '新建自动化', exact: true }).click()
  await expect(page.getByLabel('任务名称')).toHaveValue('新建中的本地草稿')
  await page.getByLabel('任务名称').scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('information-reminder.png') })
})

test('task list search, selection, pending close and focus preserve the editor', async ({ page }, testInfo) => {
  await installAgentApi(page)
  const rules = ['active', 'paused', 'draft', 'archived'].map((state, index) => ({
    id: `iar_${String(index).repeat(32)}`, version: 1, state, issue: null,
    config: { ...emptyInformationRule(), name: ['每日研究简报', '行业发布追踪', '待配置提醒', '旧研究任务'][index], requirement: `研究任务 ${index}` },
    source_names: ['研究来源'], created_at: '2026-09-08', updated_at: '2026-09-08', confirmed_at: null,
  }))
  let saves = 0
  let restores = 0
  let releaseSave: (() => void) | undefined
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path === '/api/me/information-automations') data = { items: rules, has_more: false, next_offset: null }
    else if (path.endsWith('/models')) data = { status: 'ready', models: [] }
    else if (path.endsWith('/transition')) {
      const target = rules.find((candidate) => path.includes(candidate.id))!
      if (route.request().postDataJSON().action === 'restore') { restores += 1; target.state = 'draft' }
      data = target
    }
    else if (path.endsWith('/' + rules[0].id) && route.request().method() === 'PUT') {
      saves += 1
      await new Promise<void>((resolve) => { releaseSave = resolve })
      rules[0].config = route.request().postDataJSON().config; rules[0].version += 1; data = rules[0]
    } else if (path === '/api/me/subscriptions') data = { subscriptions: [] }
    else if (path === '/api/notification-services') data = { services: [] }
    else if (path === '/api/feed/latest') data = { schema_version: 2, items: [] }
    else return route.fallback()
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  await page.goto('/agent/automations')
  const list = page.getByRole('list', { name: '自动化任务' })
  await expect(list.getByRole('listitem')).toHaveCount(4)
  await page.getByRole('button', { name: '已暂停', exact: true }).click()
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list.getByText('行业发布追踪')).toBeVisible()
  await page.getByRole('button', { name: '全部', exact: true }).click()
  await page.getByRole('button', { name: '已归档', exact: true }).click()
  await page.getByRole('button', { name: '查看与编辑 旧研究任务' }).click()
  await page.getByRole('button', { name: '恢复', exact: true }).dblclick()
  const restoredDetails = testInfo.project.name === 'desktop'
    ? page.getByRole('complementary', { name: '自动化任务详情' })
    : page.getByRole('dialog', { name: '旧研究任务', exact: true })
  await expect(restoredDetails.getByText('草稿', { exact: true })).toBeVisible()
  expect(restores).toBe(1)
  await page.getByRole('button', { name: '关闭旧研究任务', exact: true }).click()
  if (testInfo.project.name !== 'desktop') await expect(restoredDetails).toBeHidden()
  await page.getByRole('button', { name: '全部', exact: true }).click()
  const search = page.getByRole('searchbox', { name: '搜索已安排任务' })
  await search.fill('每日')
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await search.fill('')
  const row = page.getByRole('button', { name: '查看与编辑 每日研究简报' })
  await row.focus(); await page.keyboard.press('Enter')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  const input = page.getByLabel('任务名称')
  await expect(input).toHaveValue('每日研究简报')
  const original = await input.elementHandle()
  await input.fill('尚未保存的标题')
  if (testInfo.project.name === 'desktop') {
    await page.getByRole('button', { name: '已归档', exact: true }).click()
    await page.getByRole('button', { name: '刷新提醒列表' }).click()
    expect(await original!.evaluate((node) => node.isConnected)).toBe(true)
    await expect(input).toHaveValue('尚未保存的标题')
    await page.getByRole('button', { name: '全部', exact: true }).click()
    const panel = page.getByRole('complementary', { name: '自动化任务详情' })
    await expect(panel).toBeVisible()
    expect((await panel.boundingBox())!.width).toBe(400)
    const resizer = page.getByRole('separator', { name: '调整任务列表和详情宽度' })
    await resizer.focus(); await page.keyboard.press('Shift+ArrowLeft')
    await expect.poll(async () => (await panel.boundingBox())!.width).toBe(464)
    await page.keyboard.press('Home')
    await expect.poll(async () => (await panel.boundingBox())!.width).toBe(320)
    await resizer.dblclick()
    await expect.poll(async () => (await panel.boundingBox())!.width).toBe(400)
  }
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  try {
    await expect(page.getByRole('button', { name: '正在保存…', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: /关闭每日研究简报/ }).click()
    await expect(input).toHaveValue('尚未保存的标题')
    expect(saves).toBe(1)
  } finally { releaseSave?.() }
  await expect(page.getByRole('button', { name: '保存草稿', exact: true })).toBeDisabled()
  await expect.poll(async () => await page.getByRole('button', { name: '正在保存…', exact: true }).count()).toBe(0)
  expect(await original!.evaluate((node) => node.isConnected)).toBe(true)
  await input.scrollIntoViewIfNeeded()
  const scan = await new AxeBuilder({ page }).analyze()
  expect(scan.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('automation-task-details.png') })
  await page.getByRole('button', { name: /关闭尚未保存的标题/ }).click()
  await expect(page.getByRole('button', { name: '查看与编辑 尚未保存的标题' })).toBeFocused()
  if (testInfo.project.name === 'desktop') await expect(page.locator('aside[aria-label="自动化任务详情"]')).toHaveCSS('width', '0px')
  else await expect(page.getByRole('dialog', { name: '尚未保存的标题', exact: true })).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('automation-task-list.png') })
})
