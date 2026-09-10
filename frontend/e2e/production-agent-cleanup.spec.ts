import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { installShortcutFixture } from './fixtures/agent-shortcuts'

test('revocation confirmation, failed cleanup and cross-browser denial', async ({ page, browser, baseURL }, testInfo) => {
  let phase = ''
  let calls = 0
  async function install(target: Page, role: string) {
    await installShortcutFixture(target)
    await target.route('**/api/auth/status', route => route.fulfill({ json: { ok: true, data: {
      authenticated: true, user: { id: role, username: role, role, enabled: true },
    } } }))
    await target.route('**/api/me/agent-connection', route => route.fulfill({ json: { ok: true, data: {
      state: phase ? 'revoked' : 'ready', can_connect: !phase, can_manage_setup: role === 'owner',
      can_request: role === 'member' && phase === 'complete', verification: {},
      cleanup: phase ? { phase, revision: 2 } : null,
    } } }))
    await target.route('**/api/admin/agent-access-requests?*', route => route.fulfill({ json: { ok: true, data: {
      items: [{ id: 'request', binding_id: 'binding', state: 'ready', revision: 3, username: 'member',
        display_name: '测试成员', role: 'member', created_at: '2026-09-10T01:00:00Z', cleanup: phase ? { phase, revision: 2 } : null }],
      total: 1, pending_count: 0,
    } } }))
    await target.route('**/api/admin/agent-access-requests/request/revoke', route => {
      calls += 1; phase = 'failed'
      expect(route.request().postDataJSON()).toEqual({ revision: 3, confirmed: true })
      return route.fulfill({ json: { ok: true, data: { phase, revision: 2 } } })
    })
    await target.route('**/api/admin/agent-access-requests/request/cleanup-retry', route => {
      calls += 1; phase = 'complete'
      return route.fulfill({ json: { ok: true, data: { phase, revision: 3 } } })
    })
  }
  await install(page, 'owner')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/agents?tab=requests')
  const context = await browser.newContext({ baseURL, viewport: page.viewportSize()! })
  try {
    const member = await context.newPage()
    await install(member, 'member')
    await member.goto('/agents')
    await expect(member.getByRole('link', { name: '进入 OpenClaw' })).toBeVisible()
    const revoke = page.getByRole('button', { name: '撤销接入', exact: true })
    await revoke.click()
    const dialog = page.getByRole('dialog', { name: '撤销成员接入？' })
    await expect(dialog).toBeVisible()
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await expect(revoke).toBeFocused()
    expect(calls).toBe(0)
    await revoke.press('Enter')
    await page.getByRole('button', { name: '确认撤销' }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText(/权限已撤销，OpenClaw 清理待完成/)).toBeVisible()
    await member.reload()
    await expect(member.getByText('权限已撤销，OpenClaw 清理待完成')).toBeVisible()
    await expect(member.getByRole('link', { name: '进入 OpenClaw' })).toHaveCount(0)
    await expect(member.getByRole('button', { name: '申请接入' })).toHaveCount(0)
    await page.getByRole('button', { name: '重试清理' }).click()
    await expect(page.getByText(/已撤销，历史数据保留/)).toBeVisible()
    await member.reload()
    await expect(member.getByRole('button', { name: '申请接入' })).toBeVisible()
    expect(calls).toBe(2)
    await page.getByRole('button', { name: '切换到白天模式' }).click()
    await expect(page.getByRole('button', { name: '切换到黑夜模式' })).toBeVisible()
    await expect(page.locator('[data-ui-system="heroui"]')).toHaveAttribute('data-theme', 'light')
    await expect.poll(() => page.getByText('测试成员 · member').evaluate(node => getComputedStyle(node).color)).not.toBe('oklch(0.94 0.005 286)')
    expect((await new AxeBuilder({ page }).include('main').analyze()).violations).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('cleanup-light.png') })
  } finally { await context.close() }
})
