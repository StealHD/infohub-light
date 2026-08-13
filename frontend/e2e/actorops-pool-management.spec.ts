import { expect, test, type Page } from '@playwright/test'

type Slot = 'primary' | 'backup_1' | 'backup_2'

const revisions = [
  revision('primary', 'Publisher A Primary', 'publisher-a'),
  revision('backup-1', 'Publisher B Backup', 'publisher-b'),
]

function revision(id: string, actor_public_name: string, publisher: string) {
  return {
    revision_id: `revision-${id}`,
    actor_id: `${publisher}/${id}`,
    actor_public_name,
    publisher,
    build_id: `build-${id}`,
    build_number: '2026.08.13',
    manifest_hash: id.padEnd(64, id[0]).slice(0, 64),
    lifecycle: 'certified',
    last_canary_at: '2026-08-13T08:00:00Z',
    last_canary_status: 'valid_nonempty',
    can_canary: false,
    can_activate: true,
  }
}

function actorDetail() {
  const slots = (['primary', 'backup_1', 'backup_2'] as Slot[]).map((slot, index) => {
    const value = revisions[index] ?? null
    return {
      slot,
      revision_id: value?.revision_id ?? null,
      runnable: Boolean(value),
      validation_status: value?.lifecycle ?? 'unconfigured',
      revision: value,
      actions: value
        ? { add: false, replace: true, remove: true, add_reason: 'pool_full', replace_reason: null, remove_reason: null }
        : { add: true, replace: false, remove: false, add_reason: null, replace_reason: 'replace_requires_occupied_slot', remove_reason: 'slot_empty' },
    }
  })
  return {
    route_id: 'route-x-profile', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary',
    generation: 12, support_status: 'supported', runtime_status: 'ready', active_slot_count: revisions.length, runnable_slots: revisions.length,
    required_slots: 3, min_runtime_healthy: 2, admission_mode: 'standard', publisher_count: 2, per_run_cap_usd: 0.02,
    discovery_run_id: 'run-pool-e2e', blocked_reason: null, updated_at: '2026-08-13T08:00:00Z',
    workflow: { kind: 'backup_2_candidate_selection_required', goal: 'add_slot', run_id: 'run-pool-e2e', progress: {}, blockers: [] },
    slots, revisions, source_validations: [], source_validation_summary: { ready: 0, pending: 0, failed: 0 }, replacement_needed: false,
  }
}

async function mockActorOpsPool(page: Page) {
  let removePayload: Record<string, unknown> | null = null
  await page.route(/^http:\/\/127\.0\.0\.1:4173\/api\//, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const detail = actorDetail()
    let data: unknown
    if (url.pathname === '/api/auth/status') data = { authenticated: true, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true } }
    else if (url.pathname === '/api/admin/apify-routes') data = {
      schema_version: 1,
      generation: 12,
      support_profiles: [{ id: 'x/profile/items', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', label: 'X 用户动态' }],
      routes: [{ ...detail, slots: undefined, revisions: undefined, source_validations: undefined, source_validation_summary: undefined }],
    }
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile' && request.method() === 'GET') data = detail
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/active-pool/remove' && request.method() === 'POST') {
      removePayload = request.postDataJSON() as Record<string, unknown>
      data = detail
    }
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/pool-candidates') data = {
      schema_version: 1, route_id: detail.route_id, generation: detail.generation, goal: url.searchParams.get('goal') || 'add_slot',
      target_slot: url.searchParams.get('target_slot'), run_id: 'run-pool-e2e', required_selection_count: 1, blockers: [], candidates: [],
    }
    else if (url.pathname === '/api/admin/apify-discovery-runs/run-pool-e2e') data = { schema_version: 5, run_id: 'run-pool-e2e', route_id: detail.route_id, generation: detail.generation, stage: 'awaiting_canary_approval', status: 'completed', queries_completed: 1, queries_limit: 1, budget_cap_usd: 0.02, spent_usd: 0, candidate_count: 0, candidate_shortfall: 0, candidates: [], updated_at: detail.updated_at }
    else if (url.pathname === '/api/catalog/sources') data = { sources: [] }
    else if (url.pathname === '/api/admin/apify-actor-alert-settings') data = { schema_version: 4, enabled: false, channels: [], target_ids: [], selected_targets: [], channel_states: {}, events: [], updated_at: null }
    else if (url.pathname === '/api/admin/apify-discovery-settings') data = { schema_version: 4, generation: 1, enabled: false, ai_options: [], max_queries_per_run: 3, max_candidates: 12, max_output_tokens: 4096, measurements: {}, updated_at: null }
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/freshness/plan') data = {}
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/events') data = { events: [] }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found' } }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  return { removePayload: () => removePayload }
}

test('ActorOps pool operations keep a flat, safe desktop flow', async ({ page }) => {
  const state = await mockActorOpsPool(page)
  await page.goto('/settings/actorops?route=x%2Fprofile%2Fitems&tab=pool')
  await expect(page.getByRole('list', { name: '当前 Actor 主备槽位' })).toBeVisible()
  await expect(page.getByRole('button', { name: '添加 Actor' })).toBeVisible()
  await expect(page.getByRole('button', { name: '替换' }).first()).toBeVisible()
  await page.getByRole('button', { name: '移出主备池' }).first().click()
  const dialog = page.getByRole('dialog', { name: '移出主备池' })
  await expect(dialog).toContainText('压紧后顺序：备用 1 → 备用 2')
  await expect(dialog.getByRole('button', { name: '确认移出主备池' })).toBeDisabled()
  await dialog.getByRole('textbox', { name: '确认短语' }).fill('确认移出 Actor 主备池')
  await dialog.getByRole('button', { name: '确认移出主备池' }).click()
  await expect.poll(state.removePayload).toEqual({
    target_slot: 'primary', expected_generation: 12, confirmation: '确认移出 Actor 主备池',
  })
  await expect(page.getByRole('tablist', { name: 'ActorOps 配置任务' })).toHaveClass(/shadow-none/)
  await expect(page.locator('[data-settings-disclosure="高级设置与技术详情"]')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('ActorOps pool controls remain single-column at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockActorOpsPool(page)
  await page.goto('/settings/actorops?route=x%2Fprofile%2Fitems&tab=pool')
  await expect(page.getByRole('list', { name: '当前 Actor 主备槽位' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
