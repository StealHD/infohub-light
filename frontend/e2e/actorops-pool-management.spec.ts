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
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const detail = routeDetail()
    if (/\/(pool|canary|freshness|support-check|apify-discovery-settings)/.test(url.pathname)) retiredRequests.push(url.pathname)
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true } }
    else if (url.pathname === '/api/admin/apify-routes') data = { schema_version: 2, routes: [{ ...detail, candidates: undefined, bindings: undefined, attempts: undefined, discoveries: undefined, replacements: undefined }] }
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile' && request.method() === 'GET') data = detail
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/v2-candidates/standby/promote' && request.method() === 'POST') {
      promotePayload = request.postDataJSON() as Record<string, unknown>
      data = { route_id: detail.route_id }
    }
    else if (url.pathname === '/api/admin/apify-actor-alert-settings') data = { schema_version: 4, enabled: false, target_ids: [], selected_targets: [], channels: [], channel: 'email', channel_states: {}, events: [], email_configured: false, email_transport_ready: false, webhook_configured: false, webhook_provider: 'generic_event', webhook_provider_explicit: false, webhook_signing_secret_configured: false, webhook_verification_mode: 'http_status', webhook_provider_options: [], telegram_configured: false, telegram_transport_ready: false, last_test_status: null, last_tested_at: null, last_test_error_code: null, last_alert_status: null, last_alerted_at: null, last_alert_error_code: null, updated_at: null }
    else if (url.pathname === '/api/admin/apify-actor-alert-incidents') data = { incidents: [] }
    else if (url.pathname === '/api/admin/apify-actor-events') data = { schema_version: 2, availability: 'empty', events: [], returned: 0, truncated: false, window: { from: '2026-08-21T00:00:00Z', to: '2026-08-22T00:00:00Z' } }
    else if (url.pathname === '/api/notification-services') data = { schema_version: 1, services: [], channel_credentials: {} }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found' } }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  return { promotePayload: () => promotePayload, retiredRequests: () => retiredRequests }
}

test('ActorOps v2 route controls keep a flat, safe desktop flow', async ({ page }) => {
  const state = await mockActorOpsV2(page)
  await page.goto('/settings/actorops')

  await expect(page.getByTestId('actorops-v2-control-plane')).toBeVisible()
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

test('ActorOps v2 route controls remain single-column at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockActorOpsV2(page)
  await page.goto('/settings/actorops')

  await expect(page.getByTestId('actorops-v2-control-plane')).toBeVisible()
  await expect(page.getByText('X 动态', { exact: true })).toBeVisible()
  expect(state.retiredRequests()).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
