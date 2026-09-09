import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installGatewayFixture } from './agentWorkspaceFixtures'

const catalog = [
  { skillKey: 'report', name: '阅读报告', description: '把文章整理成阅读报告', disabled: false, eligible: true, missing: {} },
  { skillKey: 'pdf', name: 'PDF 提取', description: '提取 PDF 内容', disabled: false, eligible: false, missing: { bins: ['pdftotext'] } },
]

function envelope(data: unknown) { return { contentType: 'application/json', body: JSON.stringify({ ok: true, data }) } }

async function installManagedApi(page: Page, role: 'owner' | 'member') {
  let revision = 1
  let allowed: string[] = []
  await page.addInitScript(() => {
    ;(window as unknown as { __managedAllowedSkills: string[] }).__managedAllowedSkills = []
    window.sessionStorage.setItem('inteliscope.ui.insights-dismissed.v1:e2e-skill-user', '1')
    const nativeFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const response = await nativeFetch(input, init)
      const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input)
      if (url.endsWith('/api/admin/agent-skills/policy') && init?.method === 'PUT' && typeof init.body === 'string') {
        const body = JSON.parse(init.body) as { allowed_skill_keys: string[] }
        ;(window as unknown as { __managedAllowedSkills: string[] }).__managedAllowedSkills = body.allowed_skill_keys
      }
      return response
    }
  })
  await page.route((url) => url.pathname.startsWith('/api/'), async (route: Route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/status') return route.fulfill(envelope({ authenticated: true, user: { id: 'e2e-skill-user', username: 'skill-user', display_name: 'Skill 验收', role, enabled: true } }))
    if (url.pathname === '/api/me/agent-delegations') return route.fulfill(envelope({ enabled: true, mcp_url: '/mcp', subscription_writes_enabled: false, openclaw_chat: { enabled: true, default_gateway_url: '/api/me/openclaw/socket', protocol_version: 4, target_version: '2026.9.2' }, token_ttl_days: 90, max_active: 5, connections: [] }))
    if (url.pathname === '/api/me/agent-connection') return route.fulfill(envelope({ state: 'ready', agent_id: 'main', can_connect: true, can_chat: true, verification: { deployment: true, chat: false, own_content: true, information_automations: false, notifications: false } }))
    if (url.pathname === '/api/admin/agent-skills' && route.request().method() === 'GET') {
      if (role !== 'owner') return route.fulfill({ status: 403, body: JSON.stringify({ ok: false, error: { code: 'forbidden', message: 'forbidden' } }) })
      return route.fulfill(envelope({ policy: { revision, allowed_skill_keys: allowed, sync_state: 'synced', sync_in_progress: false, sync_error_code: null, updated_at: '', synced_at: '' }, skills: catalog }))
    }
    if (url.pathname === '/api/admin/agent-skills/policy' && route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as { expected_revision: number; allowed_skill_keys: string[] }
      expect(body.expected_revision).toBe(revision)
      revision += 1; allowed = [...body.allowed_skill_keys].sort()
      return route.fulfill(envelope({ policy: { revision, allowed_skill_keys: allowed, sync_state: 'synced', sync_in_progress: false, sync_error_code: null, updated_at: '', synced_at: '' } }))
    }
    if (url.pathname === '/api/feed/latest') return route.fulfill(envelope({ schema_version: 2, items: [] }))
    if (url.pathname === '/api/catalog/sources') return route.fulfill(envelope({ sources: [] }))
    if (url.pathname === '/api/me/source-health') return route.fulfill(envelope({ summary: { total: 0, healthy: 0, attention: 0, failing: 0, untested: 0 }, items: [] }))
    if (url.pathname === '/api/jobs') return route.fulfill(envelope({ jobs: [] }))
    return route.fulfill({ status: 404, ...envelope(null) })
  })
}

async function connectAndOpenSkills(page: Page, compact: boolean) {
  await installGatewayFixture(page)
  await page.goto('/agent')
  await page.getByRole('button', { name: '连接', exact: true }).click()
  await expect(page.getByText('Gateway 已连接').first()).toBeAttached()
  if (compact) await page.getByRole('button', { name: '打开 OpenClaw 会话' }).click()
  await page.getByRole('link', { name: 'Skills', exact: true }).click()
}

test('owner manages the shared allowlist and the ordinary directory refreshes', async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: testInfo.project.name === 'tablet' ? 'light' : 'dark', reducedMotion: 'reduce' })
  await installManagedApi(page, 'owner')
  await connectAndOpenSkills(page, ['mobile', 'compact-desktop'].includes(testInfo.project.name))
  await expect(page.getByText('管理员尚未开放 Skills')).toBeVisible()
  await page.getByRole('button', { name: '管理开放范围' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('已开放 0 / 共 2 项')).toBeVisible()
  await dialog.getByLabel('搜索 Skills').fill('阅读')
  const checkbox = dialog.getByRole('checkbox', { name: '开放 阅读报告' })
  await checkbox.focus()
  await checkbox.press('Space')
  await expect(checkbox).toBeChecked()
  await dialog.getByRole('button', { name: '保存开放范围' }).click()
  await dialog.getByRole('button', { name: '确认并同步' }).click()
  await expect(page.getByText('阅读报告', { exact: true })).toBeVisible()
  await expect(page.getByText('PDF 提取', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations.filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')).toEqual([])
})

test('member sees only the opened empty state and no management catalog entry', async ({ page }, testInfo) => {
  await installManagedApi(page, 'member')
  await connectAndOpenSkills(page, ['mobile', 'compact-desktop'].includes(testInfo.project.name))
  await expect(page.getByText('管理员尚未开放 Skills')).toBeVisible()
  await expect(page.getByRole('button', { name: '管理开放范围' })).toHaveCount(0)
  await expect(page.getByText('阅读报告', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
