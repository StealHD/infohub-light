import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { installAgentApi } from './agentWorkspaceFixtures'

test('real Service preview completes once and model refresh waits for connector receipt', async ({ page, request }, testInfo) => {
  test.setTimeout(60000)
  page.setDefaultTimeout(8000)
  const root = path.resolve('..')
  let process: ChildProcess | undefined
  const url = await new Promise<string>((resolve, reject) => {
    process = spawn(path.join(root, '.venv/bin/python'), [path.join(root, 'tests/automation_recovery_server.py')], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    const timer = setTimeout(() => reject(new Error('Controlled Service did not start')), 15000)
    process.stdout!.on('data', (chunk) => { output += chunk.toString(); if (output.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(output.split('\n')[0]).url) } })
    process.once('error', reject)
    process.once('exit', (code) => { if (code) { clearTimeout(timer); reject(new Error(`Controlled Service exited: ${code}`)) } })
  })
  try {
    await expect.poll(async () => { try { return (await request.get(url + '/__fixture')).status() } catch { return 0 } }).toBe(200)
    const fixture = await (await request.get(url + '/__fixture')).json()
    await installAgentApi(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.route('**/api/**', async (route) => {
      const parsed = new URL(route.request().url())
      if (parsed.pathname.startsWith('/api/me/information-automations')) {
        const response = await request.fetch(url + parsed.pathname + parsed.search, { method: route.request().method(), data: route.request().postData() || undefined, headers: { 'Content-Type': 'application/json' } })
        return route.fulfill({ response })
      }
      let data: unknown
      if (parsed.pathname === '/api/feed/latest') data = { schema_version: 2, items: [{ id: 'article', title: 'AI article', source_id: fixture.source }] }
      else if (parsed.pathname === '/api/me/subscriptions') data = { subscriptions: [{ source_id: fixture.source, source_display_name: '研究来源', source_type: 'rss', enabled: true }] }
      else if (parsed.pathname === '/api/notification-services') data = { services: [{ id: 'test-target', name: '受控目标', available: true }] }
      else return route.fallback()
      return route.fulfill({ json: { ok: true, data } })
    })
    await page.goto('/agent/automations')
    await page.getByRole('button', { name: '查看与编辑 恢复链路验收' }).click()
    await page.getByRole('tab', { name: '测试', exact: true }).click()
    await page.getByRole('button', { name: '选择文章' }).click()
    await page.getByRole('checkbox', { name: 'AI article' }).focus()
    await page.keyboard.press('Space')
    await page.getByRole('button', { name: '确认选择' }).click()
    await page.getByRole('button', { name: '开始测试' }).dblclick()
    await expect(page.getByText('正在排队等待分析…')).toBeVisible()
    await request.post(url + '/__cycle')
    await expect(page.getByText('测试已完成', { exact: true }).last()).toBeVisible()
    expect((await (await request.get(url + '/__fixture')).json()).calls).toBe(1)
    await page.reload()
    await page.getByRole('button', { name: '查看与编辑 恢复链路验收' }).click()
    await page.getByRole('tab', { name: '测试', exact: true }).click()
    await expect(page.getByText('测试已完成', { exact: true }).last()).toBeVisible()
    await page.getByRole('button', { name: '编辑', exact: true }).click()
    const selection = page.getByRole('button', { name: /分析模型/ })
    await request.post(url + '/__add-model')
    await page.getByRole('button', { name: '刷新模型目录' }).click()
    await expect(page.getByText('正在等待执行器同步模型目录…')).toBeVisible()
    await selection.click()
    await expect(page.getByRole('option', { name: 'New model' })).toHaveCount(0)
    await page.keyboard.press('Escape')
    await request.post(url + '/__cycle')
    await expect(page.getByText('模型目录已刷新。')).toBeVisible()
    await selection.click()
    await expect(page.getByRole('option', { name: 'New model' })).toBeVisible()
    await page.keyboard.press('Escape')
    expect((await (await request.get(url + '/__fixture')).json()).calls).toBe(1)
    await expect(selection).toContainText('Test')
    await page.getByRole('button', { name: '刷新模型目录' }).click()
    await expect(page.getByText('正在等待执行器同步模型目录…')).toBeVisible()
    await request.post(url + '/__cycle')
    await expect(page.getByText('已刷新，无变化。')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.filter((item) => ['serious', 'critical'].includes(item.impact || ''))).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('automation-recovery.png') })
  } finally { process?.kill('SIGTERM') }
})
