import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

test('HeroUI workbench keeps its isolated responsive interaction contract', async ({ context, page }, testInfo) => {
  const apiRequests: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url())
  })
  page.on('pageerror', (error) => { throw error })

  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/__preview/workbench-heroui')

  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"][data-theme="dark"]')).toBeVisible()
  await expect(page.locator('a[aria-label*="MUI"]')).toHaveCount(0)
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByText('精选')).toHaveCount(0)
  await expect(page.getByText('日报')).toHaveCount(0)
  await expect(page.getByText('稍后读')).toHaveCount(0)
  expect(apiRequests).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect(await page.evaluate(() => [...document.querySelectorAll('style[data-vite-dev-id], link[rel="stylesheet"]')]
    .some((element) => (element.getAttribute('data-vite-dev-id') ?? element.getAttribute('href') ?? '').includes('/styles/global.css')))).toBe(false)

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  const agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
  const feed = page.getByTestId('hero-feed-scroll')
  const title = '从任务到结果：AI 原生产品的交互范式演进'

  if (testInfo.project.name === 'desktop') {
    await expect(page.getByRole('navigation', { name: '工作台导航' })).toBeVisible()
    await expect(page.getByRole('button', { name: '收起 Agent 面板' })).toBeVisible()

    const fullyVisibleCards = await page.locator('[data-testid="hero-story-card"]').evaluateAll((cards, scrollSelector) => {
      const viewport = document.querySelector(scrollSelector as string)?.getBoundingClientRect()
      if (!viewport) return 0
      return cards.filter((card) => {
        const bounds = card.getBoundingClientRect()
        return bounds.top >= viewport.top && bounds.bottom <= viewport.bottom
      }).length
    }, '[data-testid="hero-feed-scroll"]')
    expect(fullyVisibleCards).toBeGreaterThanOrEqual(4)
    expect(fullyVisibleCards).toBeLessThanOrEqual(5)

    const rail = page.getByRole('navigation', { name: '信息流进度' })
    const railBounds = await rail.boundingBox()
    expect(railBounds?.height).toBeLessThanOrEqual(115)
    await rail.getByRole('button', { name: '跳转到第 3 条信息' }).click()
    await expect(rail.getByRole('button', { name: '跳转到第 3 条信息' })).toHaveAttribute('aria-current', 'true')

    const story = page.getByRole('article', { name: title })
    const expand = story.getByRole('button', { name: `展开 ${title}` })
    await expand.press('Enter')
    await expect(story.getByRole('button', { name: `收起 ${title}` })).toHaveAttribute('aria-expanded', 'true')
    await story.getByRole('button', { name: `将 ${title} 加入 Agent 上下文` }).click()
    await expect(agent.getByText('1 / 8')).toBeVisible()

    await agent.getByRole('textbox', { name: '交给 OpenClaw 的问题' }).fill('请提炼产品机会')
    await agent.getByRole('button', { name: '复制并交给 OpenClaw' }).click()
    await expect(agent.getByRole('status')).toHaveText('交接提示词已复制')
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('get_item')
  } else {
    const closedBounds = await agent.boundingBox()
    if (testInfo.project.name === 'mobile') expect(closedBounds?.y).toBeGreaterThanOrEqual(844)
    else expect(closedBounds?.x).toBeGreaterThanOrEqual(1024)

    const openAgent = page.getByRole('button', { name: '展开 Agent 面板' })
    await openAgent.click()
    await expect(page.getByRole('textbox', { name: '交给 OpenClaw 的问题' })).toBeVisible()
    if (testInfo.project.name === 'mobile') {
      await expect.poll(async () => (await agent.boundingBox())?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(844)
    } else {
      await expect.poll(async () => (await agent.boundingBox())?.x ?? Number.POSITIVE_INFINITY).toBeLessThan(1024)
    }

    await page.keyboard.press('Escape')
    await expect(page.getByRole('textbox', { name: '交给 OpenClaw 的问题' })).toBeHidden()
    await expect(openAgent).toBeFocused()

    await openAgent.click()
    await agent.getByRole('button', { name: '关闭 Agent 面板' }).click()
    await expect(openAgent).toBeFocused()
  }

  if (testInfo.project.name === 'mobile') {
    const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
    await expect(mobileNavigation).toBeVisible()
    expect(await mobileNavigation.getByRole('link').evaluateAll((links) => links.every((link) => {
      const bounds = link.getBoundingClientRect()
      return bounds.width >= 44 && bounds.height >= 44
    }))).toBe(true)
  } else {
    await expect(page.getByRole('navigation', { name: '移动端主导航' })).toBeHidden()
  }

  expect(await feed.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
})

test('HeroUI workbench honors reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/__preview/workbench-heroui')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()

  const duration = await page.locator('[data-testid="hero-story-card"]').first().evaluate((element) => Number.parseFloat(getComputedStyle(element).transitionDuration) * 1000)
  expect(duration).toBeLessThanOrEqual(0.02)
})
