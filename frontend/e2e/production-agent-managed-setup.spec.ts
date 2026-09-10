import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { installShortcutFixture } from './fixtures/agent-shortcuts'

test('member request and administrator decision share state across browsers', async ({ page, browser, baseURL }) => {
  let request: Record<string, unknown> | null = null
  let submitted = 0
  let decisions = 0
  async function install(target: Page, role: string) {
    await installShortcutFixture(target)
    await target.route('**/api/auth/status', route => route.fulfill({ json: { ok: true, data: {
      authenticated: true, user: { id: role, username: role, role, enabled: true },
    } } }))
    await target.route('**/api/me/agent-connection', route => route.fulfill({ json: { ok: true, data: {
      state: request?.state === 'ready' ? 'ready' : 'unconfigured', can_manage_setup: role === 'owner',
      can_request: role === 'member', can_connect: role === 'member' && request?.state === 'ready',
      verification: {}, setup: { available: true, state: 'idle' }, access_request: role === 'member' ? request : null,
    } } }))
    await target.route('**/api/me/agent-access-requests', route => {
      submitted += 1
      request = { id: 'request', state: 'pending', revision: 1, created_at: '2026-09-10T01:00:00Z',
        username: 'member', display_name: '测试成员', role: 'member' }
      return route.fulfill({ json: { ok: true, data: request } })
    })
    await target.route('**/api/admin/agent-access-requests?*', route => {
      const group = new URL(route.request().url()).searchParams.get('group')
      const visible = request && (group === 'pending' ? request.state === 'pending' : group === 'processing'
        ? request.state === 'approved' : ['ready', 'rejected'].includes(String(request.state)))
      return route.fulfill({ json: { ok: true, data: { items: visible ? [request] : [], total: visible ? 1 : 0,
        pending_count: request?.state === 'pending' ? 1 : 0 } } })
    })
    await target.route('**/api/admin/agent-access-requests/request/decision', route => {
      decisions += 1
      const body = route.request().postDataJSON()
      request = { ...request, state: body.decision, reason: body.reason, revision: 2, phase: 'configuring' }
      return route.fulfill({ json: { ok: true, data: request } })
    })
  }
  await install(page, 'member')
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
  await page.goto('/agents')
  await page.getByRole('button', { name: '申请接入', exact: true }).click()
  await expect(page.getByText(/等待管理员审核/)).toBeVisible()
  await page.reload()
  await expect(page.getByText(/等待管理员审核/)).toBeVisible()
  expect(submitted).toBe(1)
  const context = await browser.newContext({ baseURL, viewport: page.viewportSize()!, reducedMotion: 'reduce' })
  try {
    const admin = await context.newPage()
    await install(admin, 'owner')
    await admin.goto('/agents?tab=requests')
    await admin.getByRole('button', { name: '拒绝', exact: true }).click()
    const modal = admin.getByRole('dialog', { name: '拒绝接入申请' })
    await expect(modal).toBeVisible()
    await expect(admin.getByRole('button', { name: '确认拒绝' })).toBeDisabled()
    await admin.getByRole('button', { name: '取消', exact: true }).click()
    await expect(modal).toBeHidden()
    expect(decisions).toBe(0)
    await admin.getByRole('button', { name: '拒绝', exact: true }).press('Enter')
    await admin.getByRole('textbox', { name: '拒绝原因' }).fill('请稍后重新申请')
    await admin.getByRole('button', { name: '确认拒绝' }).click()
    await expect(page.getByText('申请已拒绝：请稍后重新申请')).toBeVisible()
    await page.getByRole('button', { name: '重新申请' }).click()
    await expect(admin.getByRole('button', { name: '允许并接入' })).toBeVisible({ timeout: 10000 })
    await admin.getByRole('button', { name: '允许并接入' }).click()
    await expect(page.getByText(/已允许，正在配置/)).toBeVisible()
    request = { ...request, state: 'ready', phase: null }
    await expect(page.getByRole('link', { name: '进入 OpenClaw' })).toBeVisible()
    expect(decisions).toBe(2)
    for (const target of [page, admin]) {
      expect((await new AxeBuilder({ page: target }).include('main').analyze()).violations).toEqual([])
      expect(await target.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
  } finally { await context.close() }
})

test('one onboarding entry survives browser changes without another setup', async ({ page, browser, baseURL }, testInfo) => {
  let submissions = 0
  let stage = 'idle'
  async function install(target: Page) {
    await installShortcutFixture(target)
    await target.route('**/api/auth/status', (route) => route.fulfill({ json: { ok: true, data: {
      authenticated: true, user: { id: 'shortcuts', username: 'fixture', role: 'owner', enabled: true },
    } } }))
    await target.route('**/api/me/agent-connection', (route) => {
      if (route.request().method() === 'DELETE') stage = 'revoked'
      return route.fulfill({ json: { ok: true, data: {
      state: stage === 'complete' ? 'ready' : stage === 'revoked' ? 'revoked' : stage === 'idle' ? 'unconfigured' : 'pending_verification',
      can_manage_setup: true, can_connect: stage === 'complete', can_chat: stage === 'complete',
      verification: {}, setup: { available: true, state: stage, phase: stage === 'running' ? 'verifying' : null },
    } } }) })
    await target.route('**/api/me/agent-connection/setup/reconnect', (route) => {
      submissions += 1
      stage = 'running'
      return route.fulfill({ status: 202, json: { ok: true, data: { state: stage } } })
    })
    await target.route('**/api/me/agent-connection/setup/managed', (route) => {
      submissions += 1
      expect(route.request().postDataJSON()).toEqual({ confirmed: true })
      stage = 'running'
      return route.fulfill({ status: 202, json: { ok: true, data: { state: stage } } })
    })
  }
  await install(page)
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
  await page.goto('/agents')
  const start = page.getByRole('button', { name: '接入 Agent', exact: true })
  await expect(start).toBeVisible()
  expect(submissions).toBe(0)
  await expect(page.getByRole('button', { name: /创建连接|下载|上传/u })).toHaveCount(0)
  const before = await start.boundingBox()
  await start.press('Enter')
  const pending = page.getByRole('button', { name: '正在接入', exact: true })
  await expect(pending).toBeDisabled()
  expect(Math.abs((await pending.boundingBox())!.width - before!.width)).toBeLessThanOrEqual(1)
  await expect(page.getByText('正在验证连接与数据授权')).toBeVisible()
  await page.reload()
  await expect(pending).toBeDisabled()
  expect(submissions).toBe(1)
  expect((await new AxeBuilder({ page }).include('main').analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('managed-dark.png') })

  const second = await browser.newContext({ baseURL, viewport: page.viewportSize()!, colorScheme: 'light', reducedMotion: 'reduce' })
  try {
    const other = await second.newPage()
    await install(other)
    stage = 'complete'
    await other.goto('/agents')
    await expect(other.getByRole('link', { name: '进入 OpenClaw' })).toBeVisible()
    await other.getByRole('button', { name: '切换到白天模式' }).click()
    await expect(other.getByRole('button', { name: '切换到黑夜模式' })).toBeVisible()
    await expect(other.getByRole('link', { name: '进入 OpenClaw' })).toHaveCSS('color', 'oklch(0.23 0.01 286)')
    await expect.poll(() => other.getByRole('heading', { name: '我的 Agent' }).evaluate((element) =>
      getComputedStyle(element).color === getComputedStyle(document.querySelector('.inteliscope-design-system')!).color)).toBe(true)
    expect(submissions).toBe(1)
    await other.screenshot({ path: testInfo.outputPath('managed-light.png') })
    expect((await new AxeBuilder({ page: other }).include('main').analyze()).violations.map((item) => ({
      id: item.id, nodes: item.nodes.map((node) => ({ html: node.html, target: node.target })),
    }))).toEqual([])
    if (page.viewportSize()!.width >= 1024) {
      // Browser zoom reflow: halve the available CSS viewport at 200%.
      await other.setViewportSize({ width: Math.floor(page.viewportSize()!.width / 2), height: 600 })
      const entry = other.getByRole('link', { name: '进入 OpenClaw' })
      await expect(entry).toBeVisible()
      const bounds = (await entry.boundingBox())!
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(other.viewportSize()!.width)
      expect(await other.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await other.screenshot({ path: testInfo.outputPath('managed-200-percent-reflow.png') })
    }
    await other.getByRole('button', { name: '解除接入', exact: true }).click()
    const dialog = other.getByRole('dialog', { name: '解除 Agent 接入？' })
    await expect(dialog).toBeVisible()
    expect((await new AxeBuilder({ page: other }).analyze()).violations).toEqual([])
    await other.getByRole('button', { name: '取消', exact: true }).click()
    await expect(other.getByRole('button', { name: '解除接入', exact: true })).toBeFocused()
    await other.getByRole('button', { name: '解除接入', exact: true }).press('Enter')
    await other.getByRole('button', { name: '确认解除', exact: true }).press('Enter')
    await expect(dialog).toBeHidden()
    for (const target of [page, other]) {
      await target.reload()
      await expect(target.getByText(/个人接入已解除/u)).toBeVisible()
      await expect(target.getByRole('link', { name: '进入 OpenClaw' })).toHaveCount(0)
      await expect(target.getByRole('button', { name: '接入 Agent', exact: true })).toHaveCount(0)
    }
    expect(submissions).toBe(1)
    await other.getByRole('button', { name: '重新接入', exact: true }).click()
    await expect(other.getByRole('button', { name: '正在接入', exact: true })).toBeDisabled()
    expect(submissions).toBe(2)
  } finally {
    await second.close()
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
