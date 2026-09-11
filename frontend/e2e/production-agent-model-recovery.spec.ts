import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { installAgentApi } from './agentWorkspaceFixtures'

test('real relay blocks inherited model and preserves terminal diagnostics after recovery', async ({ page, context, request, baseURL }, testInfo) => {
  test.setTimeout(60000)
  page.setDefaultTimeout(8000)
  let server: ChildProcess | undefined
  const root = path.resolve('..')
  const fixture = await new Promise<{ url: string; user: string; agent: string; key: string; cookie: string }>((resolve, reject) => {
    server = spawn(path.join(root, '.venv/bin/python'), [path.join(root, 'tests/openclaw_recovery_server.py'), baseURL!], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    const timer = setTimeout(() => reject(new Error('Service fixture startup timed out')), 15000)
    server.stdout!.on('data', (chunk) => { output += chunk.toString(); if (output.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(output.split('\n')[0])) } })
    server.once('error', reject)
    server.once('exit', (code) => { if (code) { clearTimeout(timer); reject(new Error(`Fixture exited: ${code}`)) } })
  })
  try {
    await installAgentApi(page, true)
    await context.addCookies([{ name: 'horizon_session', value: fixture.cookie, url: fixture.url }])
    await page.addInitScript(({ user, key }) => {
      const marker = 'recovery-fixture-initialized'
      if (!sessionStorage.getItem(marker)) {
        sessionStorage.setItem('infohub-managed-session:' + user, key)
        sessionStorage.setItem(marker, 'true')
      }
      localStorage.setItem('infohub-managed-session:' + user, 'auto')
    }, fixture)
    await page.route('**/api/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname
      let data: unknown
      if (pathname === '/api/auth/status') data = { authenticated: true, user: { id: fixture.user, username: 'owner', role: 'owner', enabled: true } }
      else if (pathname === '/api/me/agent-delegations') data = { enabled: true, connections: [], openclaw_chat: { enabled: true, image_io_enabled: true, default_gateway_url: '/api/me/openclaw/socket', protocol_version: 4 } }
      else if (pathname === '/api/me/agent-connection') data = { state: 'ready', agent_id: fixture.agent, can_connect: true, can_chat: true }
      else return route.fallback()
      return route.fulfill({ json: { ok: true, data } })
    })
    await page.emulateMedia({ colorScheme: testInfo.project.name === 'tablet' ? 'light' : 'dark', reducedMotion: 'reduce' })
    await page.goto(fixture.url + '/agent')
    await expect(page.getByText(/当前会话的模型继承异常/)).toBeVisible()
    const input = page.getByRole('textbox', { name: '发送给 OpenClaw 的问题' })
    await input.fill('保留草稿并验证选择模型')
    const snapshot = async () => (await (await request.get(fixture.url + '/__fixture')).json())
    expect(Object.keys((await snapshot()).calls)).toHaveLength(0)
    await expect(page.getByTestId('openclaw-timeline').getByText('切换前的上下文', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: /OpenClaw 模型：DeepSeek/ }).click()
    await page.getByRole('button', { name: /选择模型：/ }).click()
    await page.getByRole('option', { name: /DeepSeek/ }).click()
    await expect(page.getByRole('dialog', { name: '模型与思考程度' })).toBeHidden()
    await expect(page.getByText(/当前会话的模型继承异常/)).toHaveCount(0)
    await expect(input).toHaveValue('保留草稿并验证选择模型')
    await expect(page.getByTestId('openclaw-timeline').getByText('切换前的上下文', { exact: true })).toBeVisible()
    expect((await snapshot()).created).toEqual([{ agentId: fixture.agent, model: 'deepseek/flash', parentSessionKey: fixture.key, fork: true }])
    await page.getByRole('button', { name: '发送给 OpenClaw', exact: true }).dblclick()
    await expect(page.getByText('已有部分回复', { exact: true })).toBeVisible()
    await expect(page.getByText('本次实际模型：deepseek/flash')).toBeVisible()
    await expect(page.getByText(/运行编号：/)).toBeVisible()
    expect(Object.values((await snapshot()).calls)).toMatchObject([{ actual: 'deepseek/flash', deliver: false }])
    await page.reload()
    await expect(page.getByText('已有部分回复', { exact: true })).toBeVisible()
    await expect(page.getByText('模型额度受限，请稍后手动重试或检查额度。').last()).toBeVisible()
    await expect(page.getByText(/运行编号：/)).toBeVisible()
    expect(Object.keys((await snapshot()).calls)).toHaveLength(1)
    expect(await page.locator('body').innerText()).not.toContain('SECRET')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.filter((item) => ['serious', 'critical'].includes(item.impact || ''))).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('model-recovery.png') })
  } finally {
    server?.kill('SIGTERM')
  }
})
