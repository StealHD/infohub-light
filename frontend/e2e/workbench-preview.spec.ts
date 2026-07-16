import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

test('next workbench prototype keeps its responsive interaction contract', async ({ page }, testInfo) => {
  const apiRequests: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url())
  })
  page.on('pageerror', (error) => { throw error })

  await page.goto('/__preview/workbench')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(page.locator('nav[aria-label="工作台导航"]')).toBeAttached()
  await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toBeAttached()
  await expect(page.getByText('精选')).toHaveCount(0)
  await expect(page.getByText('日报')).toHaveCount(0)
  await expect(page.getByText('稍后读')).toHaveCount(0)
  expect(apiRequests).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  const agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
  if (testInfo.project.name === 'desktop') {
    await expect(page.getByRole('button', { name: '收起 Agent 面板' }).first()).toBeVisible()
    const rail = page.getByRole('navigation', { name: '信息流进度' })
    const railBounds = await rail.boundingBox()
    expect(railBounds?.height).toBeLessThanOrEqual(115)
    await rail.getByRole('button', { name: '跳转到第 3 条信息' }).click()
    await expect(rail.getByRole('button', { name: '跳转到第 3 条信息' })).toHaveAttribute('aria-current', 'true')

    const title = '从任务到结果：AI 原生产品的交互范式演进'
    const story = page.getByRole('article', { name: title })
    await story.getByRole('button', { name: `展开 ${title}` }).click()
    const add = story.getByRole('button', { name: `将 ${title} 加入 Agent 上下文` })
    const addBounds = await add.boundingBox()
    const agentBounds = await agent.boundingBox()
    expect(addBounds && agentBounds && addBounds.x + addBounds.width <= agentBounds.x).toBe(true)
    await add.click()
    await expect(agent.getByText('1 / 8')).toBeVisible()
  } else {
    const closedBounds = await agent.boundingBox()
    expect(closedBounds?.x).toBeGreaterThanOrEqual(testInfo.project.name === 'mobile' ? 390 : 1024)
    await page.getByRole('button', { name: '展开 Agent 面板' }).click()
    await expect(page.getByRole('textbox', { name: '交给 OpenClaw 的问题' })).toBeVisible()
    const openBounds = await agent.boundingBox()
    expect(openBounds?.x).toBeLessThan(testInfo.project.name === 'mobile' ? 390 : 1024)
  }

  if (testInfo.project.name === 'mobile') {
    const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
    await expect(mobileNavigation).toBeVisible()
    expect(await mobileNavigation.getByRole('link').evaluateAll((links) => links.every((link) => {
      const bounds = link.getBoundingClientRect()
      return bounds.width >= 44 && bounds.height >= 44
    }))).toBe(true)
  }
})
