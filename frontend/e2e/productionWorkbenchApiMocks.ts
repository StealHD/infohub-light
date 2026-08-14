import type { Page, Route } from '@playwright/test'

type FeedItem = {
  id: string
  user_state: { is_read: boolean; is_saved: boolean; is_later: boolean; dismissed: boolean }
  [key: string]: unknown
}

type WorkbenchFixtures = {
  items: FeedItem[]
  rollingItem: FeedItem
  batchRollingItems: FeedItem[]
  savedRouteItem: FeedItem
  historyRouteItem: FeedItem
  tsuchaHistoryItems: FeedItem[]
  socialRouteItem: FeedItem
}

type MockState = {
  backgroundRefreshComplete: boolean
  manualReloadComplete: boolean
  manualReloadGate: Promise<void> | null
  releaseManualReload: () => void
  feedbackRefreshRequested: boolean
  refreshCancelled: boolean
  savedDuringSessionId: string | null
  feedbackRetryRequests: number
  latestFeedRequests: number
  feedUpdateRequests: number
  backgroundRefreshCreatedAt: string
}

function createMockState(): MockState {
  return {
    backgroundRefreshComplete: false,
    manualReloadComplete: false,
    manualReloadGate: null,
    releaseManualReload: () => undefined,
    feedbackRefreshRequested: false,
    refreshCancelled: false,
    savedDuringSessionId: null,
    feedbackRetryRequests: 0,
    latestFeedRequests: 0,
    feedUpdateRequests: 0,
    backgroundRefreshCreatedAt: new Date().toISOString(),
  }
}

function jsonBody(data: unknown) {
  return { contentType: 'application/json', body: JSON.stringify({ ok: true, data }) }
}

function createApiRoute(page: Page, fixtures: WorkbenchFixtures, state: MockState) {
  return async (route: Route) => {
    const url = new URL(route.request().url())
    const feedbackMode = new URL(page.url()).searchParams.has('toast-feedback')
    let data: unknown
    if (url.pathname.startsWith('/api/media/')) {
      const portrait = url.pathname.endsWith('/social-one')
      const landscape = url.pathname.endsWith('/social-two')
      const width = portrait ? 2046 : landscape ? 1600 : 640
      const height = portrait ? 2728 : landscape ? 900 : 480
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#29272f"/></svg>`,
      })
      return
    }
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'e2e-user', username: 'e2e', display_name: '验收用户', role: 'member', enabled: true } }
    else if (url.pathname === '/api/feed/latest') {
      state.latestFeedRequests += 1
      if (state.manualReloadGate) await state.manualReloadGate
      const batchMode = new URL(page.url()).searchParams.has('batch')
      const socialMode = new URL(page.url()).searchParams.has('social')
      data = { schema_version: 2, items: socialMode ? [fixtures.socialRouteItem] : state.backgroundRefreshComplete || state.manualReloadComplete
        ? batchMode ? [...fixtures.items.slice(80), ...fixtures.batchRollingItems] : [...fixtures.items.slice(1), fixtures.rollingItem]
        : fixtures.items }
    }
    else if (url.pathname === '/api/feed/search') data = {
      schema_version: 1,
      scope: 'user',
      items: fixtures.items,
      item_count: fixtures.items.length,
      total_count: fixtures.items.length,
      has_more: false,
      next_cursor: null,
      window: { timezone: 'Asia/Shanghai', feed_days: 7, today_start: '2026-07-01T00:00:00Z', feed_start: '2026-06-24T00:00:00Z', now: '2026-07-01T04:00:00Z' },
    }
    else if (url.pathname === '/api/feed/source-summary' && route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { article_ids: string[] }
      data = { schema_version: 1, overview: '近期更新集中在产品能力与工程进展。', highlights: ['连续发布多项更新', `覆盖 ${body.article_ids.length} 篇当前内容`], item_count: body.article_ids.length }
    }
    else if (url.pathname === '/api/feed/saved') {
      const saved = state.savedDuringSessionId ? fixtures.items.find((item) => item.id === state.savedDuringSessionId) : undefined
      data = { items: saved ? [{ ...saved, user_state: { ...saved.user_state, is_saved: true } }] : [fixtures.savedRouteItem] }
    }
    else if (url.pathname === '/api/feed/history') {
      const sourceId = url.searchParams.get('source_id')
      const offset = Number(url.searchParams.get('offset') || '0')
      const sourceItems = sourceId === 'source-tsucha'
        ? { items: [fixtures.tsuchaHistoryItems[offset === 0 ? 0 : 1]], total_count: 2, offset, has_more: offset === 0 }
        : { items: [fixtures.historyRouteItem], total_count: 1, offset: 0, has_more: false }
      data = { ...sourceItems, item_count: sourceItems.items.length, limit: 50, snapshots: [], featured_items: [] }
    }
    else if (url.pathname === '/api/catalog/sources') data = { sources: [{ id: 'source-tsucha', type: 'apify_social', display_name: 'tsucha_ri', scope: 'public', enabled: true }] }
    else if (url.pathname === '/api/jobs/user-feed-refresh' && route.request().method() === 'POST') {
      state.feedUpdateRequests += 1
      state.feedbackRefreshRequested = true
      data = { id: 'refresh-1', user_id: 'e2e-user', job_type: 'user_feed_refresh', status: 'queued', created_at: state.backgroundRefreshCreatedAt }
    }
    else if (url.pathname === '/api/jobs/refresh-1/retry' && route.request().method() === 'POST') {
      state.feedbackRetryRequests += 1
      data = { id: 'refresh-1', user_id: 'e2e-user', job_type: 'user_feed_refresh', status: 'queued', created_at: state.backgroundRefreshCreatedAt }
    }
    else if (url.pathname === '/api/jobs/refresh-1/cancel' && route.request().method() === 'POST') {
      state.refreshCancelled = true
      data = { id: 'refresh-1', user_id: 'e2e-user', job_type: 'user_feed_refresh', status: 'cancelled', created_at: state.backgroundRefreshCreatedAt, cancelled_at: new Date().toISOString(), finished_at: new Date().toISOString() }
    }
    else if (url.pathname === '/api/jobs') data = { jobs: !state.feedbackRefreshRequested ? [] : [{
      id: 'refresh-1', user_id: 'e2e-user', job_type: 'user_feed_refresh',
      status: state.refreshCancelled ? 'cancelled' : state.backgroundRefreshComplete ? (feedbackMode ? 'failed' : 'succeeded') : 'queued',
      created_at: state.backgroundRefreshCreatedAt,
      cancelled_at: state.refreshCancelled ? new Date().toISOString() : null,
      finished_at: state.backgroundRefreshComplete || state.refreshCancelled ? new Date().toISOString() : null,
      retryable: feedbackMode && state.backgroundRefreshComplete,
      error_message: feedbackMode && state.backgroundRefreshComplete ? '模拟信息流更新失败' : undefined,
      result: {},
    }] }
    else if (url.pathname === '/api/me/feed-schedule') data = { enabled: true, interval_minutes: 60, worker_status: 'ready' }
    else if (url.pathname === '/api/me/source-health') data = { summary: { total: 2, healthy: 1, attention: 1, failing: 0, untested: 0 }, items: [{ source_id: 'source-healthy', status: 'healthy' }, { source_id: 'source-degraded', status: 'degraded' }] }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true, mcp_url: '/mcp', subscription_writes_enabled: false,
      openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' },
      token_ttl_days: 90, max_active: 5,
      connections: [{ id: 'agent-1', name: 'OpenClaw', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'], token_prefix: 'abc', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname.startsWith('/api/me/items/') && url.pathname.endsWith('/state') && route.request().method() === 'PATCH') {
      state.savedDuringSessionId = decodeURIComponent(url.pathname.split('/')[4] || '')
      data = { is_read: false, is_saved: true, is_later: false, dismissed: false }
    }
    else if (url.pathname.startsWith('/api/feed/items/')) {
      const allItems = [...fixtures.items, fixtures.rollingItem, fixtures.savedRouteItem, fixtures.historyRouteItem, ...fixtures.tsuchaHistoryItems, fixtures.socialRouteItem]
      const item = allItems.find((candidate) => candidate.id === decodeURIComponent(url.pathname.split('/').at(-1) || ''))
      if (!item) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
        return
      }
      data = item
    } else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: 'not found' } }) })
      return
    }
    await route.fulfill(jsonBody(data))
  }
}

export async function installProductionWorkbenchApiMocks(page: Page, fixtures: WorkbenchFixtures) {
  const state = createMockState()
  await page.exposeFunction('completeBackgroundRefresh', () => { state.backgroundRefreshComplete = true })
  await page.exposeFunction('completeManualFeedReload', () => {
    state.manualReloadComplete = true
    state.releaseManualReload()
  })
  await page.exposeFunction('pauseManualFeedReload', () => {
    state.manualReloadComplete = true
    state.manualReloadGate = new Promise<void>((resolve) => {
      state.releaseManualReload = () => {
        state.manualReloadGate = null
        state.releaseManualReload = () => undefined
        resolve()
      }
    })
  })
  await page.exposeFunction('feedRequestCounts', () => ({ latest: state.latestFeedRequests, updates: state.feedUpdateRequests }))
  await page.exposeFunction('feedbackRetryCount', () => state.feedbackRetryRequests)
  await page.route((url) => url.pathname.startsWith('/api/'), createApiRoute(page, fixtures, state))
}
