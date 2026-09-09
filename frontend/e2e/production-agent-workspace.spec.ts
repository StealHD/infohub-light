import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { installAgentApi, installGatewayFixture } from './agentWorkspaceFixtures'

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
  await expect(page.getByRole('button', { name: '在新 Worktree 中执行' })).toHaveCount(0)
  const creates = await page.evaluate(() => (window as unknown as { __gatewayRequests: Array<{ method: string; params: Record<string, unknown> }> }).__gatewayRequests.filter((request) => request.method === 'sessions.create'))
  expect(creates).toHaveLength(1)
  expect(creates.some((request) => request.params.worktree === true)).toBe(false)
})

test('[connected] Skills can be read and explained before authorization, with an explicit toggle afterwards', async ({ page }, testInfo) => {
  await installGatewayFixture(page)
  await page.goto('/agent')
  await page.getByLabel(/Gateway token 或 dashboard 地址/u).fill('fixture-token')
  await page.getByRole('button', { name: '连接并授权' }).click()
  await expect(page.getByText('Gateway 已连接').first()).toBeAttached()
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
  await page.goto('/agent/automations?advanced=cron')
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
    await expect(page.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveCSS('width', '232px')
    await expect(page.getByRole('navigation', { name: 'OpenClaw 工作区' })).toBeVisible()
    await page.getByRole('button', { name: '打开上下文' }).click()
    await expect(page.getByRole('complementary', { name: '上下文检查器' })).toHaveCSS('width', '360px')
  } else if (testInfo.project.name === 'tablet') {
    await expect(page.getByRole('complementary', { name: 'OpenClaw 会话' })).toHaveCSS('width', '232px')
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
  if (['mobile', 'compact-desktop'].includes(testInfo.project.name)) await page.getByRole('button', { name: '打开 OpenClaw 会话' }).click()
  await page.getByRole('link', { name: '使用示例', exact: true }).click()
  await expect(page).toHaveURL(/\/agent\/examples$/u)
  await expect(page.locator('[data-agent-examples]').getByRole('heading', { level: 3 })).toHaveCount(8)
  expect(await page.evaluate(() => (window as unknown as { __gatewayRequests: unknown[] }).__gatewayRequests)).toEqual([])
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
  await page.getByRole('dialog', { name: 'OpenClaw 更多操作' }).evaluate(async (element) => {
    await Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => undefined)))
  })
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
      await page.getByRole('link', { name: '高级 Gateway Cron' }).click()
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
