import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'

const items = Array.from({ length: 200 }, (_, index) => ({
  id: `live-${index + 1}`,
  title: `实时条目 ${index + 1}`,
  url: `https://example.com/live-${index + 1}`,
  source: index % 2 ? 'OpenAI Blog' : 'GitHub',
  source_type: index % 2 ? 'rss' : 'github',
  summary_zh: `第 ${index + 1} 条真实 API 摘要`,
  media_urls: [`/api/media/live-${index + 1}`],
  published_at: new Date(Date.UTC(2026, 6, 1, 0, index)).toISOString(),
  channel: index % 2 ? 'AI' : '开发',
  topics: ['Codex'],
  user_state: { is_read: index % 3 === 0, is_saved: false, is_later: false, dismissed: false },
}))
const rollingItem = {
  ...items.at(-1)!,
  id: 'live-201',
  title: '实时条目 201',
  url: 'https://example.com/live-201',
  summary_zh: '固定长度窗口中的新内容',
  published_at: '2026-07-01T04:00:00.000Z',
}
const batchRollingItems = Array.from({ length: 80 }, (_, index) => ({
  ...items.at(-1)!,
  id: `live-${201 + index}`,
  title: `实时条目 ${201 + index}`,
  url: `https://example.com/live-${201 + index}`,
  source: index % 2 ? 'OpenAI Blog' : 'GitHub',
  published_at: new Date(Date.UTC(2026, 6, 1, 4, index)).toISOString(),
  user_state: { is_read: index % 3 === 0, is_saved: false, is_later: false, dismissed: false },
}))
const savedRouteItem = {
  ...items[0],
  id: 'saved-route-item',
  title: '生产收藏路由条目',
  url: 'https://example.com/saved-route-item',
  user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
}
const historyRouteItem = {
  ...items[0],
  id: 'history-route-item',
  title: '生产历史路由条目',
  url: 'https://example.com/history-route-item',
  user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false },
}
const socialRouteItem = {
  id: 'social:x:1',
  title: '@thsottiaux: Oops... I did it again. Enjoy reset usage limits for all paid users fo...',
  url: 'https://x.com/thsottiaux/status/1',
  source: 'X · @thsottiaux',
  source_type: 'apify_social',
  summary_zh: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.',
  published_at: '2026-07-18T08:00:00Z',
  channel: '其他',
  topics: ['行业动态'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
  presentation: {
    version: 2,
    source: { id: 'x-source', catalog_type: 'apify_social', platform: 'x', name: 'X · @thsottiaux' },
    author: { name: 'Tibo', kind: 'person' },
    timing: { published_at: '2026-07-18T08:00:00Z', fetched_at: '2026-07-18T08:05:00Z' },
    links: { canonical_url: 'https://x.com/thsottiaux/status/1', source_url: 'https://x.com/thsottiaux' },
    content: {
      title: '@thsottiaux: Oops... I did it again. Enjoy reset usage limits for all paid users fo...',
      title_origin: 'generated',
      excerpt: 'Oops... I did it again. Enjoy reset usage limits for all paid users.',
      body_text: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.',
      content_kind: 'post_body',
      excerpt_truncated: true,
      body_truncated: false,
      format: 'gallery',
      format_origin: 'upstream',
    },
    media: {
      images: [
        { asset_id: 'social-one', url: '/api/media/social-one', alt: '社交图片一' },
        { asset_id: 'social-two', url: '/api/media/social-two', alt: '社交图片二' },
      ],
      count: 2,
      total_image_count: 4,
      truncated: true,
    },
    taxonomy: { channel: '其他', configured_topics: [], inferred_topics: ['行业动态'], topics: ['行业动态'], entities: [] },
    engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
    analysis: { status: 'ai', score: 7, signal_strength: 'medium', signal_type: 'update', summary_zh: 'Oops... I did it again. Enjoy reset usage limits for all paid users for Codex and ChatGPT Work.' },
  },
}

async function topVisibleSnapshot(page: Page) {
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  return page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollElement) => {
    const bounds = (scrollElement as HTMLElement).getBoundingClientRect()
    const visible = cards
      .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
      .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)
    const top = visible[0]
    return {
      name: top?.getAttribute('aria-label') ?? '',
      offset: top ? top.getBoundingClientRect().top - bounds.top : 0,
    }
  }, await feedScroll.elementHandle())
}

async function stableTopVisibleSnapshot(page: Page) {
  let previous = await topVisibleSnapshot(page)
  let stableFrames = 0
  for (let frame = 0; frame < 120 && stableFrames < 3; frame += 1) {
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
    const current = await topVisibleSnapshot(page)
    stableFrames = current.name === previous.name && Math.abs(current.offset - previous.offset) <= 0.5
      ? stableFrames + 1
      : 0
    previous = current
  }
  expect(stableFrames).toBe(3)
  return previous
}

async function alignVisibleCardToTop(page: Page) {
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  let stableFrames = 0
  let previous = await topVisibleSnapshot(page)
  for (let frame = 0; frame < 120 && stableFrames < 3; frame += 1) {
    expect(previous.name).not.toBe('')
    if (Math.abs(previous.offset) > 0.5) {
      stableFrames = 0
      await feedScroll.evaluate((element, correction) => {
        element.scrollTop += correction
        element.dispatchEvent(new Event('scroll'))
      }, previous.offset)
    }
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
    const current = await topVisibleSnapshot(page)
    if (current.name === previous.name && Math.abs(current.offset) <= 0.5 && Math.abs(current.offset - previous.offset) <= 0.5) {
      stableFrames += 1
    } else if (Math.abs(previous.offset) <= 0.5) {
      stableFrames = 0
    }
    previous = current
  }
  expect(stableFrames).toBe(3)
  expect(Math.abs(previous.offset)).toBeLessThanOrEqual(0.5)
  return previous
}

async function requestBackgroundRefresh(page: Page) {
  await page.evaluate(async () => {
    window.dispatchEvent(new Event('inteliscope:workbench-refresh-request'))
    await (window as typeof window & {
      completeBackgroundRefresh: () => Promise<void>
    }).completeBackgroundRefresh()
  })
}

test.beforeEach(async ({ page }) => {
  let backgroundRefreshComplete = false
  const backgroundRefreshCreatedAt = new Date().toISOString()
  await page.exposeFunction('completeBackgroundRefresh', () => {
    backgroundRefreshComplete = true
  })
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname.startsWith('/api/media/')) {
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#29272f"/></svg>',
      })
      return
    }
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } }
    else if (url.pathname === '/api/feed/latest') {
      const batchMode = new URL(page.url()).searchParams.has('batch')
      const socialMode = new URL(page.url()).searchParams.has('social')
      data = { schema_version: 2, items: socialMode ? [socialRouteItem] : backgroundRefreshComplete
        ? batchMode ? [...items.slice(80), ...batchRollingItems] : [...items.slice(1), rollingItem]
        : items }
    }
    else if (url.pathname === '/api/feed/saved') data = { items: [savedRouteItem] }
    else if (url.pathname === '/api/feed/history') data = { items: [historyRouteItem] }
    else if (url.pathname === '/api/jobs') data = { jobs: [{
      id: 'refresh-1',
      user_id: 'e2e-user',
      job_type: 'user_feed_refresh',
      status: backgroundRefreshComplete ? 'succeeded' : 'queued',
      created_at: backgroundRefreshCreatedAt,
      finished_at: backgroundRefreshComplete ? new Date().toISOString() : null,
      result: {},
    }] }
    else if (url.pathname === '/api/me/feed-schedule') data = { enabled: true, interval_minutes: 60, worker_status: 'ready' }
    else if (url.pathname === '/api/me/source-health') data = {
      summary: { total: 2, healthy: 1, attention: 1, failing: 0, untested: 0 },
      items: [
        { source_id: 'source-healthy', status: 'healthy' },
        { source_id: 'source-degraded', status: 'degraded' },
      ],
    }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: '/mcp',
      subscription_writes_enabled: false,
      openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' },
      token_ttl_days: 90,
      max_active: 5,
      connections: [{ id: 'agent-1', name: 'OpenClaw', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'], token_prefix: 'abc', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname.startsWith('/api/feed/items/')) {
      const item = [...items, rollingItem, savedRouteItem, historyRouteItem, socialRouteItem].find((candidate) => candidate.id === decodeURIComponent(url.pathname.split('/').at(-1) || ''))
      if (!item) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
        return
      }
      data = item
    }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
      return
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
})

test('production HeroUI workbench preserves responsive shell, virtualization and Agent handoff', async ({ context, page }, testInfo) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/feed')
  await expect(page.getByRole('heading', { name: '信息流' })).toBeVisible()
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByText('稍后读')).toHaveCount(0)
  expect(await page.locator('[data-testid="workbench-card"]').count()).toBeLessThanOrEqual(40)
  await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
  await expect(page.getByText('200 条内容', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '最新优先' })).toBeVisible()
  await expect(page.getByText('全部', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '更新信息流' })).toBeVisible()
  const agentToggle = page.getByRole('banner').getByRole('button', { name: /^(收起|展开) Agent 面板$/ })
  await expect(agentToggle).toHaveAttribute('data-agent-toggle-visual', 'quiet-studio')
  await expect(agentToggle.locator('[data-split-panel-icon]')).toHaveCount(1)
  await expect(page.getByRole('banner')).toHaveAttribute('data-header-visual', 'quiet-studio')
  await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
  await page.evaluate(() => document.fonts.ready)

  const shell = page.getByTestId('live-workbench-shell')
  expect(await page.locator('body').evaluate((element) => getComputedStyle(element).color)).toBe(
    await shell.evaluate((element) => getComputedStyle(element).color),
  )
  const desktopNavigation = page.getByRole('complementary', { name: '桌面导航' })
  const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
  let agent: Locator

  if (testInfo.project.name === 'desktop') {
    await page.getByRole('button', { name: '展开信息概览' }).click()
    const insights = page.getByRole('complementary', { name: '信息概览' })
    await expect(insights).toBeVisible()
    await expect(insights.getByText('今日内容', { exact: true })).toBeVisible()
    await expect(insights.getByText('异常来源', { exact: true })).toBeVisible()
    await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toHaveCount(0)
    await page.getByRole('button', { name: '展开 Agent 面板' }).click()
    agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    const railSeparator = page.getByRole('separator', { name: '调整信息流和 Agent 面板宽度' })
    await expect(railSeparator).toHaveAttribute('aria-valuenow', '360')
    await railSeparator.focus()
    await page.keyboard.press('ArrowLeft')
    await expect(railSeparator).toHaveAttribute('aria-valuenow', '384')
    expect(await page.evaluate(() => window.localStorage.getItem('inteliscope.ui.right-rail.v1:e2e-user'))).toBe(JSON.stringify({ width: 384 }))
    const quietCard = page.locator('[data-card-visual="quiet-studio"]').first()
    expect(await quietCard.evaluate((element) => getComputedStyle(element).borderRadius)).toBe('18px')
    expect((await quietCard.boundingBox())?.width ?? 0).toBeLessThanOrEqual(820)
    await expect(desktopNavigation).toBeVisible()
    await expect(mobileNavigation).toBeHidden()
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect(agent.getByText('对话未启用')).toBeVisible()
    await page.getByRole('button', { name: '展开侧栏' }).click()
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(232)
    expect(await page.evaluate(() => window.localStorage.getItem('inteliscope.ui.sidebar.v1:e2e-user'))).toBe('expanded')
    await expect(desktopNavigation.getByText('浏览', { exact: true })).toBeVisible()
    await expect(desktopNavigation.getByText('常用视图', { exact: true })).toBeVisible()
    await expect(desktopNavigation.getByRole('button', { name: '当天' })).toBeVisible()
    await expect(desktopNavigation.getByText('管理', { exact: true })).toBeVisible()
    const accountTrigger = desktopNavigation.getByRole('button', { name: '打开账户菜单' })
    await accountTrigger.click()
    const accountMenu = page.getByRole('dialog', { name: '账户菜单' })
    await expect(accountMenu.getByRole('button', { name: '退出登录' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(accountTrigger).toBeFocused()

    const fullyVisibleCards = await page.locator('[data-testid="workbench-card"]').evaluateAll((cards, scrollSelector) => {
      const viewport = document.querySelector(scrollSelector as string)?.getBoundingClientRect()
      if (!viewport) return 0
      return cards.filter((card) => {
        const bounds = card.getBoundingClientRect()
        return bounds.top >= viewport.top && bounds.bottom <= viewport.bottom
      }).length
    }, '[data-testid="workbench-feed-scroll"]')
    expect(fullyVisibleCards).toBeGreaterThanOrEqual(4)
    expect(fullyVisibleCards).toBeLessThanOrEqual(5)

    await page.setViewportSize({ width: 1280, height: 800 })
    expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
    await expect(page.getByRole('button', { name: /侧栏/ })).toHaveCount(0)
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    agent = page.getByRole('dialog', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()

    const desktopFeed = page.getByTestId('workbench-feed-scroll')
    await desktopFeed.evaluate((element) => {
      element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
      element.dispatchEvent(new Event('scroll'))
    })
    const panelAnchor = await alignVisibleCardToTop(page)
    await agent.getByRole('button', { name: '关闭 Agent 面板' }).click()
    await expect(page.getByRole('dialog', { name: 'OpenClaw 上下文' })).toBeHidden()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
    await expect(page.getByRole('button', { name: '关闭 Agent 面板' })).toHaveCount(0)
    await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(panelAnchor.name)
    await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - panelAnchor.offset)).toBeLessThanOrEqual(2)
    await page.getByRole('button', { name: '展开 Agent 面板' }).click()
    await expect(page.getByRole('dialog', { name: 'OpenClaw 上下文' })).toBeVisible()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    await page.setViewportSize({ width: 1440, height: 900 })
    agent = page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(3)
    await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(panelAnchor.name)
    await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - panelAnchor.offset)).toBeLessThanOrEqual(2)
  } else {
    const toggle = page.getByRole('button', { name: '展开 Agent 面板' })
    const feedScroll = page.getByTestId('workbench-feed-scroll')
    const feedBounds = await feedScroll.boundingBox()
    const feedScrollTop = await feedScroll.evaluate((element) => element.scrollTop)
    if (testInfo.project.name === 'mobile') {
      await expect(desktopNavigation).toBeHidden()
      await expect(mobileNavigation).toBeVisible()
      expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(1)
    } else {
      await expect(desktopNavigation).toBeVisible()
      await expect(mobileNavigation).toBeHidden()
      expect(Math.round((await desktopNavigation.boundingBox())?.width ?? 0)).toBe(72)
      expect((await shell.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(2)
    }
    await toggle.click()
    agent = page.getByRole('dialog', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    await expect(page.getByTestId('right-rail-drawer-backdrop')).toBeVisible()
    await expect(agent.getByText('对话未启用')).toBeVisible()
    await agent.evaluate(async (element) => Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined))))
    expect(await feedScroll.boundingBox()).toEqual(feedBounds)
    expect(await feedScroll.evaluate((element) => element.scrollTop)).toBe(feedScrollTop)
    expect(await shell.evaluate((element) => {
      let current: HTMLElement | null = element
      while (current && current !== document.body) {
        if (current.inert || current.getAttribute('aria-hidden') === 'true') return true
        current = current.parentElement
      }
      return false
    })).toBe(true)
    await page.keyboard.press('Tab')
    expect(await agent.evaluate((element) => element.contains(document.activeElement))).toBe(true)
    const agentBounds = await agent.boundingBox()
    if (testInfo.project.name === 'mobile') {
      expect(Math.round(agentBounds?.width ?? 0)).toBe(390)
      expect(Math.round((agentBounds?.y ?? 0) + (agentBounds?.height ?? 0))).toBe(844)
    } else {
      expect(Math.abs((agentBounds?.width ?? 0) - 360)).toBeLessThanOrEqual(1)
      expect(Math.round((agentBounds?.x ?? 0) + (agentBounds?.width ?? 0))).toBe(1024)
    }
    await page.keyboard.press('Escape')
    await expect(toggle).toBeFocused()
    await expect(agent).toBeHidden()
  }
  if (testInfo.project.name === 'mobile') {
    await expect(mobileNavigation.getByRole('link')).toHaveCount(6)
    await expect(mobileNavigation.getByRole('link', { name: '助手连接' })).toBeVisible()
  }

  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  const expansionAnchorBefore = await stableTopVisibleSnapshot(page)
  const anchorName = expansionAnchorBefore.name
  await feedScroll.dispatchEvent('scroll')
  const card = page.getByRole('article', { name: anchorName })
  // Invoke the already-visible control directly: Playwright's actionability helper otherwise
  // scrolls a partially visible first card before dispatching the click, unlike a pointer click.
  await card.getByRole('button', { name: `展开 ${anchorName}` }).evaluate((element: HTMLElement) => element.click())
  await expect(page).toHaveURL(/item=live-/)
  await expect(card.getByRole('button', { name: `收起 ${anchorName}` })).toBeVisible()
  await expect(card).toHaveAttribute('data-card-expanded', 'true')
  const expandedId = await card.locator('xpath=..').getAttribute('data-item-id')
  expect(expandedId).not.toBeNull()
  await expect(page.getByTestId(`card-details-${expandedId}`)).toHaveAttribute('data-state', 'expanded')
  const expansionAnchorAfter = await stableTopVisibleSnapshot(page)
  expect(expansionAnchorAfter.name).toBe(anchorName)
  expect(Math.abs(expansionAnchorAfter.offset - expansionAnchorBefore.offset)).toBeLessThanOrEqual(2)
  await card.getByRole('button', { name: `将 ${anchorName} 加入 Agent 上下文` }).click()
  if (testInfo.project.name !== 'desktop') {
    agent = page.getByRole('dialog', { name: 'OpenClaw 上下文' })
    await expect(agent).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(agent).toBeHidden()
  }

  const rollingAnchorBefore = await alignVisibleCardToTop(page)
  await requestBackgroundRefresh(page)
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeVisible({ timeout: 7000 })
  const rollingAnchorAfter = await topVisibleSnapshot(page)
  expect(rollingAnchorAfter.name).toBe(rollingAnchorBefore.name)
  expect(Math.abs(rollingAnchorAfter.offset - rollingAnchorBefore.offset)).toBeLessThanOrEqual(2)
  await page.getByRole('button', { name: '查看 1 条新内容' }).click()
  await expect(page.getByRole('button', { name: '查看 1 条新内容' })).toBeHidden()
  await expect.poll(() => feedScroll.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(96)

  const openAgent = page.getByRole('button', { name: '展开 Agent 面板' })
  if (await openAgent.isVisible()) await openAgent.click()
  agent = testInfo.project.name === 'desktop'
    ? page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    : page.getByRole('dialog', { name: 'OpenClaw 上下文' })
  await expect(agent.getByText('1 / 8', { exact: true })).toBeVisible()
  await agent.getByRole('textbox', { name: '交给 OpenClaw 的问题' }).fill('提炼机会')
  await expect(agent.getByText('使用 OpenClaw 当前设置', { exact: true })).toBeVisible()
  await expect(agent.getByRole('button', { name: /模型偏好/ })).toHaveCount(0)
  await agent.getByRole('button', { name: '复制交接提示词' }).click()
  const handoff = await page.evaluate(() => navigator.clipboard.readText())
  expect(handoff).toContain('[INTELISCOPE_HANDOFF_V3]')
  expect(handoff).toContain('调用 get_item')
  expect(handoff).not.toContain('模型偏好：')

  const horizontalOverflow = await agent.evaluate((element) => {
    const regions = [element, ...element.querySelectorAll<HTMLElement>('*')]
    return regions.flatMap((region) => region.scrollWidth > region.clientWidth ? [{
      testId: region.getAttribute('data-testid') || 'agent-panel',
      tag: region.tagName.toLowerCase(),
      className: region.className,
      clientWidth: region.clientWidth,
      scrollWidth: region.scrollWidth,
    }] : []).slice(0, 20)
  })
  expect(horizontalOverflow).toEqual([])

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('a proven-stale initial deep link returns the real Feed viewport to the newest edge', async ({ page }) => {
  await page.goto('/feed?item=missing')
  await expect(page.getByText(/这条信息已不可用/)).toBeVisible()
  await expect(page).toHaveURL('/feed')
  await expect(page.getByRole('article', { name: '实时条目 200' })).toBeVisible()
  const offset = await page.getByTestId('workbench-feed-scroll').evaluate((element) => element.scrollTop)
  expect(offset).toBeLessThanOrEqual(96)
})

test('social cards and Agent context show source information once without exposing item IDs', async ({ page }, testInfo) => {
  await page.goto('/feed?social=1')
  const card = page.getByTestId('workbench-card')
  const source = card.getByLabel('来源信息')

  await expect(card).toBeVisible()
  await expect(source.getByText('Tibo', { exact: true })).toBeVisible()
  await expect(source.getByText('@thsottiaux', { exact: true })).toBeVisible()
  await expect(page.getByText('Oops... I did it again. Enjoy reset usage limits for all paid users.', { exact: true })).toHaveCount(1)
  await expect(page.getByText(socialRouteItem.title, { exact: true })).toHaveCount(0)
  await expect(card.getByText('图集', { exact: true })).toBeVisible()
  await expect(card.getByText('4 张图片 · 可查看 2 张', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: /展开 / }).click()
  await expect(card.getByLabel('2 张可查看图片').getByRole('img')).toHaveCount(2)
  await expect(card.getByText('仅获取到内容片段，打开原文查看完整内容。', { exact: true })).toBeVisible()

  await card.getByRole('button', { name: /加入 Agent 上下文/ }).click()
  const agent = testInfo.project.name === 'desktop'
    ? page.getByRole('complementary', { name: 'OpenClaw 上下文' })
    : page.getByRole('dialog', { name: 'OpenClaw 上下文' })
  await expect(agent).toBeVisible()
  await expect(agent.getByText('Tibo', { exact: true })).toBeVisible()
  await expect(agent.getByText('@thsottiaux', { exact: true })).toBeVisible()
  await expect(agent.getByText('Oops... I did it again. Enjoy reset usage limits for all paid users.', { exact: true })).toBeVisible()
  await expect(page.getByText(socialRouteItem.id, { exact: true })).toHaveCount(0)
})

test('a filtered unread-first Feed restores an unmounted anchor with the rendered card index', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('inteliscope.ui.feed.v2:e2e-user', JSON.stringify({
    unreadFirst: true,
    source: 'GitHub',
    channel: '',
    topic: '',
  })))
  await page.goto('/feed?batch=1')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await expect(page.getByLabel('已启用 2 项筛选')).toBeVisible()
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) * 0.1)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)

  // Sample and complete the background task in one browser task so a later Virtualizer measurement cannot make
  // the expected anchor older than the request-time geometry captured by the application.
  const anchorBefore = await feedScroll.evaluate(async (scroll) => {
    const bounds = scroll.getBoundingClientRect()
    const top = Array.from(scroll.querySelectorAll<HTMLElement>('[data-testid="workbench-card"]'))
      .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
      .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
    const anchor = {
      name: top?.getAttribute('aria-label') ?? '',
      offset: top ? top.getBoundingClientRect().top - bounds.top : 0,
    }
    window.dispatchEvent(new Event('inteliscope:workbench-refresh-request'))
    await (window as typeof window & {
      completeBackgroundRefresh: () => Promise<void>
    }).completeBackgroundRefresh()
    return anchor
  })
  expect(anchorBefore.name).not.toBe('')
  await expect(page.getByRole('button', { name: '查看 80 条新内容' })).toBeVisible({ timeout: 7000 })
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorBefore.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorBefore.offset)).toBeLessThanOrEqual(2)

})

test('live unread-first and source filters preserve the surviving rendered-card anchor', async ({ page }) => {
  await page.goto('/feed')
  await page.evaluate(() => document.fonts.ready)
  const feedScroll = page.getByTestId('workbench-feed-scroll')
  await feedScroll.evaluate((element) => {
    element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2)
    element.dispatchEvent(new Event('scroll'))
  })
  await alignVisibleCardToTop(page)

  await page.getByRole('button', { name: '筛选信息流' }).click()
  const filterDialog = page.getByRole('dialog', { name: '信息流筛选' })
  await expect(filterDialog).toBeVisible()
  await expect(filterDialog.getByRole('button', { name: /来源/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(filterDialog).toBeHidden()
  await expect(page.getByRole('button', { name: '筛选信息流' })).toBeFocused()
  await page.getByRole('button', { name: '筛选信息流' }).click()
  await expect(filterDialog).toBeVisible()
  await page.mouse.click(4, 100)
  await expect(filterDialog).toBeHidden()
  await expect(page.getByRole('button', { name: '筛选信息流' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(filterDialog).toBeVisible()
  const anchorAtTransition = await alignVisibleCardToTop(page)
  const itemNumber = Number(anchorAtTransition.name.match(/\d+/)?.[0])
  const survivingSource = itemNumber % 2 === 1 ? 'GitHub' : 'OpenAI Blog'
  await filterDialog.getByText('未读优先', { exact: true }).click()
  await expect(page.getByText('未读优先', { exact: true }).first()).toBeVisible()
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorAtTransition.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorAtTransition.offset)).toBeLessThanOrEqual(2)

  const sourceSelect = filterDialog.getByRole('button', { name: /来源/ })
  await sourceSelect.click()
  await page.getByRole('option', { name: survivingSource }).click()
  await expect.poll(async () => (await topVisibleSnapshot(page)).name).toBe(anchorAtTransition.name)
  await expect.poll(async () => Math.abs((await topVisibleSnapshot(page)).offset - anchorAtTransition.offset)).toBeLessThanOrEqual(2)
})

test('Quiet Studio honors Reduced Motion without losing state', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/feed')
  const card = page.getByRole('article', { name: '实时条目 200' })
  await card.getByRole('button', { name: '展开 实时条目 200' }).click()
  const id = await card.locator('xpath=..').getAttribute('data-item-id')
  expect(id).not.toBeNull()
  const details = page.getByTestId(`card-details-${id}`)
  await expect(details).toHaveAttribute('data-state', 'expanded')
  const durations = await details.evaluate((element) => getComputedStyle(element).transitionDuration
    .split(',')
    .map((value) => Number.parseFloat(value)))
  expect(durations.every((seconds) => seconds <= 0.001)).toBe(true)
})

test('Quiet Studio keeps keyboard expansion and mobile action targets accessible', async ({ page }, testInfo) => {
  await page.goto('/feed')
  const card = page.getByRole('article', { name: '实时条目 200' })
  const expand = card.getByRole('button', { name: '展开 实时条目 200' })
  await expand.focus()
  await page.keyboard.press('Enter')
  await expect(card.getByRole('button', { name: '收起 实时条目 200' })).toHaveAttribute('aria-expanded', 'true')

  if (testInfo.project.name === 'mobile') {
    const openOriginal = card.getByRole('link', { name: '打开 实时条目 200 原文' })
    const box = await openOriginal.boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44)
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
})

test('saved, history and legacy later are accepted by the production workbench routes', async ({ page }) => {
  await page.goto('/saved')
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: savedRouteItem.title })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
  await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
  await expect(page.locator('[data-card-visual="quiet-studio"]')).toHaveCount(1)
  await expect(page.getByRole('banner')).toHaveAttribute('data-header-visual', 'quiet-studio')
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '最新优先' })).toBeVisible()
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '更新信息流' })).toHaveCount(0)
  await expect(page.getByRole('article', { name: savedRouteItem.title }).getByText('文章', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  await page.goto('/history')
  await expect(page.getByRole('heading', { name: '历史', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: historyRouteItem.title })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '信息流进度' })).toHaveCount(0)
  await expect(page.getByTestId('workbench-feed-scroll')).toHaveAttribute('data-feed-visual', 'quiet-studio')
  await expect(page.locator('[data-card-visual="quiet-studio"]')).toHaveCount(1)
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '最新优先' })).toBeVisible()
  await expect(page.getByTestId('collection-view-bar').getByRole('button', { name: '更新信息流' })).toHaveCount(0)
  await expect(page.getByRole('article', { name: historyRouteItem.title }).getByText('文章', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect((await new AxeBuilder({ page }).analyze()).violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  await page.goto('/later?mode=featured&item=saved-route-item')
  await expect(page).toHaveURL('/saved?item=saved-route-item')
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: savedRouteItem.title })).toBeVisible()
})

test('content-route navigation keeps the same shell and a closed Agent panel', async ({ page }) => {
  await page.goto('/feed')
  const shell = page.getByTestId('live-workbench-shell')
  await shell.evaluate((element) => {
    ;(window as typeof window & { workbenchShellProbe?: Element }).workbenchShellProbe = element
    element.setAttribute('data-lifecycle-probe', 'persistent-shell')
  })

  const closeAgent = page.getByRole('button', { name: '收起 Agent 面板' })
  if (await closeAgent.isVisible()) await closeAgent.click()
  await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()

  await page.getByRole('link', { name: '收藏', exact: true }).click()
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
  expect(await page.evaluate(() => (window as typeof window & { workbenchShellProbe?: Element }).workbenchShellProbe === document.querySelector('[data-testid="live-workbench-shell"]'))).toBe(true)

  await page.getByRole('link', { name: '历史', exact: true }).click()
  await expect(page.getByRole('heading', { name: '历史', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '展开 Agent 面板' })).toBeVisible()
  await expect(shell).toHaveAttribute('data-lifecycle-probe', 'persistent-shell')
  expect(await page.evaluate(() => (window as typeof window & { workbenchShellProbe?: Element }).workbenchShellProbe === document.querySelector('[data-testid="live-workbench-shell"]'))).toBe(true)
})
