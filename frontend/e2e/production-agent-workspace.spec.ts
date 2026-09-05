import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type Route } from '@playwright/test'

function jsonBody(data: unknown) { return { contentType: 'application/json', body: JSON.stringify({ ok: true, data }) } }
async function installAgentApi(page: Page, enabled = false) {
  await page.addInitScript(() => window.sessionStorage.setItem('inteliscope.ui.insights-dismissed.v1:e2e-agent', '1'))
  await page.route((url) => url.pathname.startsWith('/api/'), async (route: Route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/status') return route.fulfill(jsonBody({ authenticated: true, user: { id: 'e2e-agent', username: 'agent', display_name: 'Agent 验收', role: 'member', enabled: true } }))
    if (url.pathname === '/api/me/agent-delegations') return route.fulfill(jsonBody({ enabled: true, mcp_url: '/mcp', subscription_writes_enabled: false, openclaw_chat: { enabled, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.8.1' }, token_ttl_days: 90, max_active: 5, connections: [] }))
    if (url.pathname === '/api/feed/latest') return route.fulfill(jsonBody({ schema_version: 2, items: [] }))
    if (url.pathname === '/api/catalog/sources') return route.fulfill(jsonBody({ sources: [] }))
    if (url.pathname === '/api/me/source-health') return route.fulfill(jsonBody({ summary: { total: 0, healthy: 0, attention: 0, failing: 0, untested: 0 }, items: [] }))
    if (url.pathname === '/api/jobs') return route.fulfill(jsonBody({ jobs: [] }))
    return route.fulfill({ status: 404, ...jsonBody(null) })
  })
}

async function installGatewayFixture(page: Page) {
  await page.addInitScript(() => {
    const requests: Array<{ method: string; params: Record<string, unknown> }> = []
    let skillEnabled = false
    let createdWorktree = false
    let taskCancelled = false
    const automation = { id: 'cron-1', name: '每天阅读摘要', enabled: false, schedule: { kind: 'every', everyMs: 3600000 }, sessionTarget: 'isolated', payload: { kind: 'agentTurn', message: '整理今日阅读要点' }, delivery: { mode: 'none' } }
    ;(window as unknown as { __gatewayRequests: typeof requests }).__gatewayRequests = requests
    class FixtureWebSocket {
      readyState = 1
      private listeners = new Map<string, Array<(event: unknown) => void>>()
      constructor() {
        window.setTimeout(() => {
          this.emit('open', {})
          this.emit('message', { data: JSON.stringify({ type: 'event', event: 'connect.challenge', payload: { nonce: 'fixture-nonce' } }) })
        }, 0)
      }
      addEventListener(type: string, listener: (event: unknown) => void) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]) }
      private emit(type: string, event: unknown) { for (const listener of this.listeners.get(type) ?? []) listener(event) }
      send(raw: string) {
        const frame = JSON.parse(raw) as { id: string; method: string; params: Record<string, unknown> }
        if (typeof frame.method !== 'string') return // Ignore Vite HMR ping frames, not Gateway RPCs.
        requests.push({ method: frame.method, params: frame.params })
        const methods = [
          'projects.list', 'sessions.create', 'sessions.list', 'sessions.preview', 'sessions.send', 'worktrees.branches',
          'tasks.list', 'tasks.get', 'tasks.cancel', 'artifacts.list', 'artifacts.get', 'artifacts.download', 'skills.status',
          'skills.update', 'cron.list', 'cron.get', 'cron.status', 'cron.add', 'cron.update', 'cron.run', 'cron.runs', 'cron.remove',
        ]
        let payload: unknown = { ok: true }
        if (frame.method === 'connect') payload = { protocol: 4, auth: { role: 'operator', scopes: frame.params.scopes, deviceToken: 'fixture-device-token' }, snapshot: { sessionDefaults: { defaultAgentId: 'main' } }, features: { methods } }
        else if (frame.method === 'sessions.create') {
          if (frame.params.worktree) createdWorktree = true
          payload = frame.params.worktree ? { ok: true, key: 'child', runStarted: true, runId: 'run-1', worktree: { id: 'wt-1', path: '/tmp/wt-1', branch: 'openclaw/ui' } } : { key: 'root' }
        }
        else if (frame.method === 'models.list') payload = { models: [{ id: 'gpt', provider: 'openai', name: 'GPT', available: true, input: ['text'] }] }
        else if (frame.method === 'agents.list') payload = { defaultId: 'main', agents: [{ id: 'main', model: { primary: 'openai/gpt' } }] }
        else if (frame.method === 'sessions.describe') payload = { session: { key: frame.params.key, modelProvider: 'openai', model: 'gpt' } }
        else if (frame.method === 'tools.effective') payload = { groups: [{ tools: [{ id: 'inteliscope', source: 'mcp' }] }] }
        else if (frame.method === 'chat.history') payload = { messages: [] }
        else if (frame.method === 'sessions.list') payload = { sessions: [{ key: 'root', displayName: 'Inscope · 127.0.0.1:8080 · 384f86ea20d2477f', hasActiveRun: false, totalTokens: 10, contextTokens: 100 }, ...(createdWorktree ? [{ key: 'child', parentSessionKey: 'root', displayName: '登录校验测试', hasActiveRun: true }] : [])] }
        else if (frame.method === 'sessions.preview') payload = { previews: [{ key: (frame.params.keys as string[])[0], status: 'empty', items: [] }] }
        else if (frame.method === 'projects.list') payload = { projects: [{ id: 'infohub', displayName: 'InfoHub', repoRoot: '/repo', source: 'configured' }] }
        else if (frame.method === 'worktrees.branches') payload = { branches: [{ name: 'main', kind: 'local' }], defaultBranch: 'main' }
        else if (frame.method === 'tasks.list') payload = { tasks: [{ id: 'task-1', title: 'Fixture task', status: taskCancelled ? 'cancelled' : 'running', sessionKey: String(frame.params.sessionKey) }] }
        else if (frame.method === 'tasks.get') payload = { task: { id: 'task-1', title: 'Fixture task', status: 'running', sessionKey: frame.params.sessionKey, prompt: '检查登录校验', result: '已定位需要补充的校验' } }
        else if (frame.method === 'tasks.cancel') { taskCancelled = true; payload = { found: true, cancelled: true } }
        else if (frame.method === 'artifacts.list') payload = { artifacts: [{ id: 'artifact-1', title: 'result.md', type: 'text', mimeType: 'text/markdown', sizeBytes: 14, sessionKey: String(frame.params.sessionKey), download: { mode: 'bytes' } }] }
        else if (frame.method === 'artifacts.get' || frame.method === 'artifacts.download') payload = { artifact: { id: 'artifact-1', title: 'result.md', type: 'text', mimeType: 'text/markdown', sizeBytes: 14, sessionKey: frame.params.sessionKey, download: { mode: 'bytes' } }, encoding: 'base64', data: btoa('Example report') }
        else if (frame.method === 'skills.status') payload = { skills: [{ skillKey: 'report', name: '阅读报告', description: '把文章整理成阅读报告', disabled: !skillEnabled, eligible: skillEnabled, missing: { bins: [], env: [] }, install: [] }] }
        else if (frame.method === 'skills.update') { skillEnabled = frame.params.enabled === true; payload = { ok: true } }
        else if (frame.method === 'cron.list') payload = { jobs: [automation] }
        else if (frame.method === 'cron.status') payload = { enabled: true }
        else if (frame.method === 'cron.get' || frame.method === 'cron.add') payload = { job: automation }
        else if (frame.method === 'cron.update') { automation.enabled = (frame.params.patch as { enabled: boolean }).enabled; payload = { ok: true } }
        else if (frame.method === 'cron.run') payload = { runId: 'scheduled-run' }
        else if (frame.method === 'cron.runs') payload = { entries: [{ jobId: 'cron-1', runId: 'scheduled-run', ts: 1788570000000, completionStatus: 'succeeded', summary: '阅读摘要已生成' }] }
        window.setTimeout(() => this.emit('message', { data: JSON.stringify({ type: 'res', id: frame.id, ok: true, payload }) }), 0)
      }
      close() { this.readyState = 3; this.emit('close', { code: 1000 }) }
    }
    ;(window as unknown as { WebSocket: typeof WebSocket }).WebSocket = FixtureWebSocket as unknown as typeof WebSocket
  })
}

test.beforeEach(async ({ page }, testInfo) => installAgentApi(page, testInfo.title.includes('[connected]')))

test('[connected] controlled Gateway proves connected resources and write confirmation', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop fixture covers the protocol-backed path')
  await installGatewayFixture(page)
  await page.goto('/agent')
  await page.getByLabel(/Gateway token 或 dashboard 地址/u).fill('fixture-token')
  await page.getByRole('button', { name: '连接并授权' }).click()
  await expect(page.getByText('Gateway 已连接').first()).toBeAttached()
  await page.getByRole('button', { name: '打开Tasks' }).click()
  await expect(page.getByText('Fixture task')).toBeVisible()
  await page.getByRole('button', { name: 'Fixture task' }).click()
  await expect(page.getByText('已定位需要补充的校验')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '打开Artifacts' }).click()
  await expect(page.getByText('result.md')).toBeVisible()
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await expect(page.getByText('Example report')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '在新 Worktree 中执行' }).click()
  await expect(page.getByRole('heading', { name: '确认独立 Gateway 信任域' })).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { __gatewayRequests: Array<{ method: string }> }).__gatewayRequests.filter((request) => request.method === 'sessions.create').length)).toBe(1)
  await page.getByRole('button', { name: '这是独立信任域' }).click()
  await page.getByRole('button', { name: '在新 Worktree 中执行' }).click()
  await expect(page.getByRole('heading', { name: '在新 Worktree 中执行' })).toBeVisible()
  await page.getByLabel('任务标题').fill('登录校验测试')
  await page.getByLabel('完整提示词').fill('为登录表单补充校验和测试')
  await page.getByRole('button', { name: '确认创建' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '登录校验测试 子 Session · 来源已验证' })).toBeVisible()
  const creates = await page.evaluate(() => (window as unknown as { __gatewayRequests: Array<{ method: string; params: Record<string, unknown> }> }).__gatewayRequests.filter((request) => request.method === 'sessions.create'))
  expect(creates).toHaveLength(2)
  expect(creates[1].params).toMatchObject({ worktree: true, parentSessionKey: 'root', worktreeBaseRef: 'main', succeedsParent: false })
})

test('[connected] Skills can be read and explained before authorization, with an explicit toggle afterwards', async ({ page }, testInfo) => {
  await installGatewayFixture(page)
  await page.goto('/agent')
  await page.getByLabel(/Gateway token 或 dashboard 地址/u).fill('fixture-token')
  await page.getByRole('button', { name: '连接并授权' }).click()
  await expect(page.getByRole('heading', { name: 'OpenClaw 对话', level: 1 })).toBeVisible()
  if (testInfo.project.name === 'compact-desktop' || testInfo.project.name === 'mobile') await page.getByRole('button', { name: '打开 OpenClaw 会话' }).click()
  await page.getByRole('link', { name: 'Skills', exact: true }).click()
  await expect(page.getByText('阅读报告', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看 阅读报告 详情' }).click()
  await expect(page.getByText(/使用方式：回到对话/)).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
  expect(await page.evaluate(() => (window as unknown as { __gatewayRequests: Array<{ method: string }> }).__gatewayRequests.filter((r) => r.method === 'connect').length)).toBe(1)
  await page.getByRole('button', { name: '启用', exact: true }).click()
  await page.getByRole('checkbox').focus()
  await page.getByRole('checkbox').press('Space')
  await expect(page.getByRole('checkbox')).toBeChecked()
  await page.getByLabel('Gateway admin token').fill('fixture-admin')
  await page.getByRole('button', { name: '授权本次操作' }).click()
  await expect(page.getByText('临时管理连接已授权')).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { __gatewayRequests: Array<{ method: string }> }).__gatewayRequests.filter((r) => r.method === 'skills.update').length)).toBe(0)
  await page.getByRole('button', { name: '启用', exact: true }).click()
  await page.getByRole('button', { name: '确认执行' }).click()
  await expect(page.getByText('可使用', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('skills-connected.png') })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([])
})

test('[connected] Automation authorization does not run a job; run and records remain explicit', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop exercises the separate admin connection')
  await installGatewayFixture(page)
  await page.goto('/agent/automations')
  await page.getByRole('button', { name: '临时授权' }).click()
  await page.getByRole('checkbox').focus()
  await page.getByRole('checkbox').press('Space')
  await expect(page.getByRole('checkbox')).toBeChecked()
  await page.getByLabel('Gateway admin token').fill('fixture-admin')
  await page.getByRole('button', { name: '授权本次操作' }).click()
  await expect(page.getByText('每天阅读摘要', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { __gatewayRequests: Array<{ method: string }> }).__gatewayRequests.filter((r) => ['cron.add', 'cron.update', 'cron.run'].includes(r.method)).length)).toBe(0)
  await page.getByRole('button', { name: '运行', exact: true }).click()
  await expect(page.getByRole('heading', { name: '确认 Gateway 写操作' })).toBeVisible()
  await page.getByRole('button', { name: '确认执行' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: '记录', exact: true }).click()
  await expect(page.getByText('阅读摘要已生成')).toBeVisible()
})

test('OpenClaw Workspace uses one layer, an on-demand inspector and accessible responsive navigation', async ({ page }, testInfo) => {
  await page.goto('/agent')
  await expect(page.locator('[data-agent-workspace-layout]')).toHaveJSProperty('offsetTop', 0)
  await expect(page.getByText('站内 OpenClaw 对话尚未启用')).toBeVisible()
  await expect(page.getByRole('complementary', { name: /检查器/ })).toHaveCount(0)
  await expect(page.getByRole('separator', { name: /调整/ })).toHaveCount(0)

  if (testInfo.project.name === 'desktop') {
    await expect(page.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveCSS('width', '288px')
    await expect(page.getByRole('navigation', { name: 'OpenClaw 工作区' })).toBeVisible()
    await page.getByRole('button', { name: '打开上下文' }).click()
    await expect(page.getByRole('complementary', { name: '上下文检查器' })).toHaveCSS('width', '360px')
  } else if (testInfo.project.name === 'tablet') {
    await expect(page.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveCSS('width', '288px')
    await page.getByRole('button', { name: '打开上下文' }).click()
    await expect(page.getByRole('dialog', { name: '上下文' })).toBeVisible()
  } else if (testInfo.project.name === 'compact-desktop') {
    await expect(page.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveCount(0)
    await page.getByRole('button', { name: '打开 OpenClaw 会话' }).click()
    await expect(page.getByRole('dialog', { name: 'OpenClaw 会话' })).toBeVisible()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '打开上下文' }).click()
    await expect(page.getByRole('dialog', { name: '上下文' })).toBeVisible()
  } else {
    await expect(page.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveCount(0)
    await page.getByRole('button', { name: '打开 OpenClaw 会话' }).click()
    await expect(page.getByRole('dialog', { name: 'OpenClaw 会话' })).toBeVisible()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '打开更多操作' }).click()
    await page.getByRole('button', { name: '上下文' }).click()
    await expect(page.getByRole('dialog', { name: '上下文' })).toBeVisible()
  }

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations.filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')).toEqual([])
})

test('workspace switcher restores the latest Inscope and OpenClaw route', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop covers the shared route-memory behavior')
  await page.goto('/saved')
  const headerGeometry = (element: Element) => {
    const style = getComputedStyle(element)
    return { height: element.getBoundingClientRect().height, top: element.getBoundingClientRect().top, radius: style.borderRadius, background: style.backgroundColor }
  }
  const inscopeHeader = await page.locator('[data-page-header]').evaluate(headerGeometry)
  await page.getByRole('button', { name: '切换工作区，当前为 Inscope' }).click()
  await page.getByRole('button', { name: /OpenClaw.*对话、执行与自动化/ }).click()
  await expect(page).toHaveURL(/\/agent$/u)
  await expect.poll(() => page.locator('[data-page-header]').evaluate(headerGeometry)).toEqual(inscopeHeader)
  await page.getByRole('button', { name: '切换工作区，当前为 OpenClaw' }).click()
  await page.getByRole('button', { name: /Inscope.*订阅、阅读与追踪/ }).click()
  await expect(page).toHaveURL(/\/saved$/u)
})

test('usage examples are reachable on every viewport and never dispatch work', async ({ page }, testInfo) => {
  await installGatewayFixture(page)
  await page.goto('/agent')
  if (testInfo.project.name === 'mobile') await page.getByRole('button', { name: '打开更多操作' }).click()
  await page.getByRole('button', { name: '使用示例', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'OpenClaw 使用示例' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading', { level: 3 })).toHaveCount(8)
  expect(await page.evaluate(() => (window as unknown as { __gatewayRequests: unknown[] }).__gatewayRequests)).toEqual([])
  await dialog.getByRole('button', { name: '知道了' }).click()
  await expect(dialog).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('workspace-header.png') })
})

test('OpenClaw Workspace reflows at a 200 percent equivalent viewport in both themes and Reduced Motion', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'one browser covers the 200 percent equivalent reflow')
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 720, height: 450 })
  await page.goto('/agent')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.getByRole('button', { name: '打开 OpenClaw 会话' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.getByRole('button', { name: '打开更多操作' }).click()
  await page.getByRole('button', { name: '切换到白天模式' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations.filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')).toEqual([])
})

test('Feed handoff opens the full workspace without clearing the draft or issuing a Gateway request', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop continuity coverage')
  await page.goto('/feed')
  await page.getByRole('button', { name: '展开 Agent 面板' }).click()
  const composer = page.getByLabel('交给 OpenClaw 的问题')
  await composer.fill('保留这段未发送问题')
  await page.getByRole('button', { name: '在 Agent 工作台打开' }).click()
  await expect(page).toHaveURL(/\/agent$/u)
  await expect(page.getByLabel('交给 OpenClaw 的问题')).toHaveValue('保留这段未发送问题')
  await expect(page.getByText('站内 OpenClaw 对话尚未启用')).toBeVisible()
})

for (const resource of ['tasks', 'artifacts', 'skills', 'automations'] as const) {
  test(`resource routes: ${resource} deep link and local unavailable state`, async ({ page }) => {
    await page.goto(`/agent/${resource}`)
    if (resource === 'tasks' || resource === 'artifacts') await expect(page.getByTestId('agent-scroll-region')).toBeVisible()
    if (resource === 'automations') {
      await expect(page.getByRole('heading', { name: 'Automations', level: 1 })).toBeVisible()
      await page.getByRole('button', { name: '临时授权' }).click()
      await expect(page.getByRole('heading', { name: '临时管理授权' })).toBeVisible()
      await page.getByRole('button', { name: '取消', exact: true }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
    } else {
      const label = { tasks: 'Tasks', artifacts: 'Artifacts', skills: 'Skills' }[resource]
      await expect(page.getByText(`连接 Gateway 后查看 ${label}`)).toBeVisible()
    }
  })
}
