import type { Page } from '@playwright/test'

export type GuidedActorOpsGoal = 'initial_pool' | 'complete_third' | 'upgrade_legacy'

export async function mockGuidedActorOpsFlow(page: Page, goal: GuidedActorOpsGoal) {
  let phase: 'selection' | 'complete' = 'selection'
  let applies = 0
  let activationPayload: Record<string, unknown> | null = null
  const revision = (id: string, publisher: string, lifecycle: string, publicName: string) => ({
    revision_id: `revision-${id}`,
    actor_id: `${publisher}/${id}`,
    actor_public_name: publicName,
    publisher,
    build_id: `build-${id}`,
    build_number: `2026.08.${id}`,
    manifest_hash: id.padEnd(64, id[0] || 'a').slice(0, 64),
    lifecycle,
    last_charge_usd: lifecycle === 'static_valid' ? null : 0.01,
    avg_charge_24h_usd: lifecycle === 'static_valid' ? null : 0.01,
    last_canary_at: lifecycle === 'static_valid' ? null : '2026-08-09T08:00:00Z',
    last_canary_status: lifecycle === 'static_valid' ? null : 'valid_nonempty',
    can_canary: lifecycle === 'static_valid',
    can_activate: lifecycle !== 'static_valid',
  })
  const exactPrimary = revision('primary', 'publisher-a', 'certified', 'Exact Primary')
  const exactBackup = revision('backup-1', 'publisher-b', 'certified', 'Exact Backup')
  const third = revision('backup-2', 'publisher-c', 'static_valid', 'Exact Backup 2')
  const legacyPrimary = revision('legacy-primary', 'builtin-a', 'legacy_builtin', 'Legacy Primary')
  const legacyBackup = revision('legacy-backup', 'builtin-b', 'legacy_builtin', 'Legacy Backup')
  const legacyBackup2 = revision('legacy-backup-2', 'builtin-a', 'legacy_builtin', 'Legacy Backup 2')
  const initialPrimary = revision('initial-primary', 'publisher-new-a', 'static_valid', 'Selected Primary')
  const initialBackup = revision('initial-backup', 'publisher-new-b', 'static_valid', 'Selected Backup 1')
  const initialBackup2 = revision('initial-backup-2', 'publisher-new-a', 'static_valid', 'Selected Backup 2')
  const replacementPrimary = revision('replacement-primary', 'publisher-new-a', 'static_valid', 'New Exact Primary')
  const replacementBackup = revision('replacement-backup', 'publisher-new-b', 'static_valid', 'New Exact Backup')
  const replacementBackup2 = revision('replacement-backup-2', 'publisher-new-a', 'static_valid', 'New Exact Backup 2')
  const selectedRevisions = goal === 'complete_third'
    ? [third]
    : goal === 'upgrade_legacy'
      ? [replacementPrimary, replacementBackup, replacementBackup2]
      : [initialPrimary, initialBackup, initialBackup2]
  const planItems = selectedRevisions.map((item, index) => ({
    ordinal: index + 1,
    candidate_id: `candidate-e2e-${index + 1}`,
    revision_id: item.revision_id,
    actor_id: item.actor_id,
    actor_public_name: item.actor_public_name,
    publisher: item.publisher,
    build_id: item.build_id,
    build_number: item.build_number,
    lifecycle: item.lifecycle,
    authorized_cap_usd: 0.02,
  }))

  const currentDetail = () => {
    const applied = phase === 'complete'
    const baseRevisions = goal === 'complete_third'
      ? [exactPrimary, exactBackup]
      : goal === 'upgrade_legacy'
        ? [legacyPrimary, legacyBackup, legacyBackup2]
        : []
    const appliedRevisions = goal === 'complete_third'
      ? [exactPrimary, exactBackup, { ...third, lifecycle: 'probationary', can_canary: false, can_activate: true }]
      : selectedRevisions.map((item) => ({ ...item, lifecycle: 'probationary', can_canary: false, can_activate: true }))
    const active = applied ? appliedRevisions : baseRevisions
    const workflowKind = applied
      ? 'probation_observing'
      : `${goal === 'complete_third' ? 'backup_2' : goal === 'upgrade_legacy' ? 'legacy' : 'setup'}_${phase === 'selection' ? 'candidate_selection_required' : 'activation_approval_required'}`
    return {
      route_id: 'route-x-profile',
      route_key: 'x/profile',
      platform: 'x',
      target_type: 'profile',
      capability: 'items',
      mode: 'primary',
      generation: applied ? 13 : 12,
      support_status: applied || goal === 'upgrade_legacy' ? 'supported' : 'degraded',
      runtime_status: 'ready',
      runnable_slots: active.length,
      required_slots: 3,
      min_runtime_healthy: 2,
      publisher_count: new Set(active.map((item) => item.publisher)).size,
      per_run_cap_usd: 0.02,
      discovery_run_id: 'run-e2e',
      blocked_reason: null,
      updated_at: '2026-08-09T08:00:00Z',
      workflow: {
        kind: workflowKind,
        goal: applied ? null : goal,
        run_id: 'run-e2e',
        stage_id: null,
        plan_hash: null,
        progress: {},
        blockers: [],
      },
      slots: [
        { slot: 'primary', revision_id: active[0]?.revision_id ?? null, runnable: Boolean(active[0]), revision: active[0] ?? null },
        { slot: 'backup_1', revision_id: active[1]?.revision_id ?? null, runnable: Boolean(active[1]), revision: active[1] ?? null },
        { slot: 'backup_2', revision_id: active[2]?.revision_id ?? null, runnable: Boolean(active[2]), revision: active[2] ?? null },
      ],
      revisions: [...baseRevisions, ...selectedRevisions],
      source_validations: [],
      source_validation_summary: { ready: 0, pending: 0, failed: 0 },
      replacement_needed: goal === 'upgrade_legacy' && !applied,
    }
  }
  const currentRoutes = () => {
    const detail = currentDetail()
    return {
      schema_version: 1,
      generation: 22,
      support_profiles: [{ id: 'x/profile/items', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', label: 'X Profile' }],
      routes: [{
        route_id: detail.route_id,
        route_key: detail.route_key,
        platform: detail.platform,
        target_type: detail.target_type,
        capability: detail.capability,
        mode: detail.mode,
        generation: detail.generation,
        support_status: detail.support_status,
        runtime_status: detail.runtime_status,
        runnable_slots: detail.runnable_slots,
        required_slots: detail.required_slots,
        min_runtime_healthy: detail.min_runtime_healthy,
        publisher_count: detail.publisher_count,
        per_run_cap_usd: detail.per_run_cap_usd,
        discovery_run_id: detail.discovery_run_id,
        blocked_reason: detail.blocked_reason,
        updated_at: detail.updated_at,
        workflow: detail.workflow,
      }],
    }
  }
  await page.route(/^https?:\/\/[^/]+\/api\/admin\/apify-/, async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    let data: unknown
    if (url.pathname === '/api/admin/apify-routes' && method === 'GET') data = currentRoutes()
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile' && method === 'GET') data = currentDetail()
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/pool-candidates' && method === 'GET') {
      data = {
        schema_version: 1,
        route_id: 'route-x-profile',
        generation: 12,
        goal,
        run_id: 'run-e2e',
        required_selection_count: planItems.length,
        blockers: [],
        candidates: planItems.map((item) => ({
          candidate_id: item.candidate_id,
          actor_public_name: item.actor_public_name,
          publisher: item.publisher,
          pricing: {
            model: 'PAY_PER_EVENT',
            billing_unit: 'event',
            unit_price_min_usd: 0.001,
            unit_price_max_usd: 0.001,
            minimum_charge_usd: null,
            minimum_run_cap_usd: 0.02,
          },
          max_validation_charge_usd: 0.02,
          validation_options: {
            timeout_seconds: 300,
            timeout_min_seconds: 180,
            timeout_max_seconds: 900,
            sample_items: 1,
            allowed_sample_items: [1],
            max_charge_usd: 0.02,
            max_charge_limit_usd: 0.10,
            supports_sample_items: false,
            options_hash: `options-e2e-${item.candidate_id}`,
            profile_hash: `profile-e2e-${item.candidate_id}`,
          },
          last_failure: null,
          requires_profile_change: false,
          already_validated: true, selectable: true,
          unavailable_reason: null,
        })),
      }
    }
    else if (url.pathname === '/api/admin/apify-support-checks' && method === 'POST') {
      data = { schema_version: 1, kind: 'discovery', generation: 23, route_generation: 12, discovery_run_id: 'run-e2e' }
    }
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile/verified-pool-activation' && method === 'POST') {
      activationPayload = route.request().postDataJSON() as Record<string, unknown>
      applies += 1
      phase = 'complete'
      data = currentDetail()
    }
    else {
      await route.fallback()
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })

  return { applies: () => applies, activationPayload: () => activationPayload }
}
