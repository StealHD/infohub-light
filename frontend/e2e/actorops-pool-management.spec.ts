import { expect, test, type Page } from '@playwright/test'

function candidate(candidateId: string, assignment: 'active' | 'standby', priority: number) {
  return {
    candidate_id: candidateId,
    build_number: '2026.08.22',
    lifecycle: 'certified',
    assignment,
    priority,
    generation: priority + 2,
    store_metadata: {
      actor_slug: `publisher/${candidateId}`,
      display_name: candidateId === 'active' ? 'Publisher A Primary' : 'Publisher B Standby',
      short_description: '公开商城信息',
      developer_name: 'Publisher',
      maintained_by_apify: false,
      rating: 4.8,
      review_count: 12,
      bookmark_count: 3,
      total_users: 42,
      monthly_active_users: 10,
      pricing: [],
      last_modified_at: null,
      observed_at: '2026-08-22T08:00:00Z',
      generation: 1,
    },
    evidence_progress: { verified_bindings: 1, required_bindings: 1 },
  }
}

function routeDetail() {
  const active = candidate('active', 'active', 0)
  const standby = candidate('standby', 'standby', 1)
  const summary = {
    route_id: 'route-x-profile',
    route_key: 'x/profile/items',
    platform: 'x',
    target_type: 'profile',
    capability: 'items',
    runtime_mode: 'active',
    generation: 12,
    per_run_cap_usd: 0.02,
    health: 'healthy',
    active_candidate: active,
    standby_candidates: [standby],
    last_known_good: active,
    binding_summary: { ready_count: 1, pending_count: 1, disabled_count: 0 },
    maintenance_policy: {
      authorized: false,
      workspace: { enabled: false, monthly_budget_usd: 0, generation: 1 },
      route: { enabled: false, max_probe_usd: 0.01, max_probes_per_utc_day: 1, auto_add_standby: false, auto_replace_non_last: false, generation: 1 },
      budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 },
    },
    degraded_reason: null,
    updated_at: '2026-08-22T08:00:00Z',
  }
  return {
    ...summary,
    candidates: [active, standby],
    bindings: [{ binding_id: 'binding-x', status: 'ready', binding_version: 2, preferred_candidate_id: 'active', last_known_good_candidate_id: 'active', last_success_at: '2026-08-22T08:00:00Z' }],
    attempts: [{ attempt_id: 'attempt-x', kind: 'fetch', status: 'completed', result_state: 'validated', semantic_outcome: 'success', failure_class: null, error_code: null, reserved_usd: 0.02, actual_cost_usd: 0.01, cost_final: true, created_at: '2026-08-22T08:00:00Z', terminal_at: '2026-08-22T08:01:00Z', updated_at: '2026-08-22T08:01:00Z' }],
    discoveries: [{ discovery_id: 'discovery-x', trigger_reason: 'manual', status: 'completed', stage: 'settled', stage_attempt: 1, candidate_count: 2, rejection_count: 0, error_code: null, created_at: '2026-08-22T08:00:00Z', terminal_at: '2026-08-22T08:01:00Z', updated_at: '2026-08-22T08:01:00Z' }],
    replacements: [],
  }
}

async function mockActorOpsV2(page: Page) {
  let promotePayload: Record<string, unknown> | null = null
  const retiredRequests: string[] = []
  let routeListRequests = 0
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const detail = routeDetail()
    if (/\/(pool|canary|freshness|support-check|apify-discovery-settings)/.test(url.pathname)) retiredRequests.push(url.pathname)
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true } }
    else if (url.pathname === '/api/admin/apify-routes') { routeListRequests += 1; data = { schema_version: 2, routes: [{ ...detail, candidates: undefined, bindings: undefined, attempts: undefined, discoveries: undefined, replacements: undefined }] } }
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile' && request.method() === 'GET') data = detail
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/v2-candidates/standby/promote' && request.method() === 'POST') {
      promotePayload = request.postDataJSON() as Record<string, unknown>
      data = { route_id: detail.route_id }
    }
    else if (url.pathname === '/api/admin/apify-actor-alert-settings') data = { schema_version: 4, enabled: false, target_ids: [], selected_targets: [], channels: [], channel: 'email', channel_states: {}, events: [], email_configured: false, email_transport_ready: false, webhook_configured: false, webhook_provider: 'generic_event', webhook_provider_explicit: false, webhook_signing_secret_configured: false, webhook_verification_mode: 'http_status', webhook_provider_options: [], telegram_configured: false, telegram_transport_ready: false, last_test_status: null, last_tested_at: null, last_test_error_code: null, last_alert_status: null, last_alerted_at: null, last_alert_error_code: null, updated_at: null }
    else if (url.pathname === '/api/admin/apify-actor-alert-incidents') data = { schema_version: 3, incidents: [{ schema_version: 3, id: 'incident-unknown', route: 'x/profile', event_type: 'start_outcome_unknown', severity: 'critical', status: 'open', actor_name: null, active_actor_name: null, reason_code: 'hidden', opened_at: '2026-08-22T08:00:00Z', last_seen_at: '2026-08-22T08:01:00Z', resolved_at: null, deliveries: [], delivery_status: 'pending', delivery_error_code: null }] }
    else if (url.pathname === '/api/admin/apify-actor-events') data = { schema_version: 3, availability: 'available', events: [{ event_id: 'event-promote', timestamp: '2026-08-22T08:00:00Z', action: 'actorops_v2_candidate_promote', outcome: 'succeeded', level: 'info', phase: 'apply', changed_fields: ['actorops_v2_candidate_promote'], counts: { changed: 1 }, final_cost_usd: 0, method: 'POST', status_code: 200 }, { event_id: 'event-unknown', timestamp: '2026-08-22T08:01:00Z', action: 'actorops_v2_future_action', outcome: 'failed', level: 'error', error_code: 'actorops_v2_safe_error', method: 'POST', status_code: 409 }], returned: 2, truncated: false, window: { from: '2026-08-21T00:00:00Z', to: '2026-08-22T00:00:00Z' } }
    else if (url.pathname === '/api/notification-services') data = { schema_version: 1, services: [], channel_credentials: {} }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found' } }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  return { promotePayload: () => promotePayload, retiredRequests: () => retiredRequests, routeListRequests: () => routeListRequests }
}

test('ActorOps v2 route cards keep a safe desktop flow', async ({ page }) => {
  const state = await mockActorOpsV2(page)
  await page.goto('/settings/actorops')

  await expect(page.getByTestId('actorops-v2-control-plane')).toBeVisible()
  const routeCard = page.locator('[data-actorops-route-card="x"]')
  await expect(routeCard).toBeVisible()
  await expect(page.locator('[data-actorops-route-card]')).toHaveCount(1)
  await expect(page.getByText('X 动态', { exact: true })).toBeVisible()
  await expect(page.getByText('Publisher A Primary', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '查看运行详情' }).click()
  await expect(page.getByText('候选与商城信息', { exact: true })).toBeVisible()
  await expect(page.getByText('近期运行与费用', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Actor 路由更多操作' }).click()
  await page.getByRole('button', { name: '设为主用' }).click()
  const dialog = page.getByRole('dialog', { name: '设为当前主用' })
  await dialog.getByRole('textbox', { name: '确认短语' }).fill('确认设为主用 Actor')
  await dialog.getByRole('button', { name: '确认' }).click()
  await expect.poll(state.promotePayload).toEqual({ expected_route_generation: 12, expected_candidate_generation: 3, confirmation: '确认设为主用 Actor' })
  expect(state.retiredRequests()).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('ActorOps v2 route card keeps the approved three-viewport visual baseline', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    window.localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({ themeName: 'graphite-purple', colorMode: 'light' }))
  })
  await mockActorOpsV2(page)
  await page.goto('/settings/actorops')

  const routeCard = page.locator('[data-actorops-route-card="x"]')
  await expect(routeCard).toBeVisible()
  await expect(routeCard).toHaveScreenshot('actorops-v2-route-card.png', { animations: 'disabled' })
})

test('ActorOps v2 route controls remain single-column at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockActorOpsV2(page)
  await page.goto('/settings/actorops')

  await expect(page.getByTestId('actorops-v2-control-plane')).toBeVisible()
  await expect(page.getByText('X 动态', { exact: true })).toBeVisible()
  expect(state.retiredRequests()).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('ActorOps separates routes from logs and keeps incident recovery safe at supported widths', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'This test sets the three supported viewport widths directly.')
  const state = await mockActorOpsV2(page)
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/settings/actorops?tab=operations&job=job-safe_1')
    await expect(page).toHaveURL(/tab=logs&job=job-safe_1/)
    await expect(page.getByTestId('actorops-v2-logs')).toBeVisible()
    await expect(page.getByTestId('actorops-v2-control-plane')).toHaveCount(0)
    await expect(page.getByText('待处理事件', { exact: true })).toBeVisible()
    await expect(page.getByText('无法确认 Actor 是否已启动。')).toBeVisible()
    await expect(page.getByText(/不要重试/)).toBeVisible()
    await expect(page.getByRole('link', { name: '打开 Apify 运行记录' })).toHaveAttribute('href', 'https://console.apify.com/actors/runs')
    await page.getByRole('button', { name: '查看详情' }).first().click()
    await expect(page.getByText('请求结果')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }
  expect(state.routeListRequests()).toBe(0)
})

test('Actor marketplace preview remains open across its trigger and surface, then returns focus safely', async ({ page }) => {
  await mockActorOpsV2(page)
  await page.goto('/settings/actorops')

  const trigger = page.getByRole('button', { name: '查看Publisher A Primary商城信息' })
  await trigger.hover()
  const preview = page.getByRole('dialog', { name: 'Publisher A Primary 商城信息' })
  await expect(preview.getByRole('link', { name: '打开 Apify' })).toBeVisible()
  await preview.hover()
  await expect(preview).toBeVisible()
  await page.mouse.move(0, 0)
  await expect(preview).toBeHidden()

  await trigger.focus()
  await expect(preview).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(preview).toBeHidden()
  await expect(trigger).toBeFocused()
  await trigger.click()
  await expect(preview.getByRole('link', { name: '打开 Apify' })).toBeVisible()
})
