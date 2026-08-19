import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { ApifyActorCanaryPlan, ApifyActorRevisionSummary, ApifyActorRouteDetail, ApifyActorRoutesResponse, ApifyActorWorkflow } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { HeroActorOpsControlPlane } from './HeroActorOpsControlPlane'

const workflow = (kind: string): ApifyActorWorkflow => ({ kind, goal: 'complete_third', run_id: 'run-guided', progress: {}, blockers: [] })
const revision = (id: string, publisher: string): ApifyActorRevisionSummary => ({
  revision_id: `revision-${id}`, actor_id: `${publisher}/${id}`, actor_public_name: `${publisher} ${id}`, publisher,
  build_id: `build-${id}`, build_number: '2026.08.1', manifest_hash: 'a'.repeat(64), lifecycle: 'certified', last_canary_at: null, last_canary_status: null, can_canary: false, can_activate: true,
})

export function poolManagementDetail(): ApifyActorRouteDetail {
  const primary = revision('primary', 'publisher-a'), backup = revision('backup-1', 'publisher-b')
  return {
    route_id: 'route-x-profile', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', generation: 12,
    support_status: 'degraded', runtime_status: 'ready', active_slot_count: 2, runnable_slots: 2, required_slots: 3, min_runtime_healthy: 2, admission_mode: 'standard', publisher_count: 2, per_run_cap_usd: 0.02,
    discovery_run_id: 'run-guided', blocked_reason: null, updated_at: '2026-08-09T08:00:00Z', workflow: workflow('backup_2_canary_approval_required'),
    slots: [
      { slot: 'primary', revision_id: primary.revision_id, runnable: true, revision: primary, actions: { add: false, replace: true, remove: true } },
      { slot: 'backup_1', revision_id: backup.revision_id, runnable: true, revision: backup, actions: { add: false, replace: true, remove: true, promote: true } },
      { slot: 'backup_2', revision_id: null, runnable: false, revision: null, actions: { add: true, replace: false, remove: false } },
    ], revisions: [primary, backup], source_validations: [], source_validation_summary: { ready: 0, pending: 0, failed: 0 },
  }
}

const plan = (detail: ApifyActorRouteDetail, goal: 'add_slot' | 'replace_slot', slot: 'primary' | 'backup_2', count: 2 | 3): ApifyActorCanaryPlan => ({
  schema_version: 3, goal, operation_slot: slot, selection_mode: 'manual', run_id: 'run-guided', route_id: detail.route_id, route_key: detail.route_key, platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', generation: detail.generation,
  status: 'ready', ready: true, activation_ready: false, plan_hash: 'b'.repeat(64), max_candidates: 1, max_total_charge_usd: 0.02, per_candidate_cap_usd: 0.02, successful_actor_count: 2, successful_publisher_count: 2, attempts_used: 0, attempts_remaining: 3, budget_remaining_usd: 0.02, base_pool_hash: 'c'.repeat(64), required_success_count: 1, route_validation_cap_usd: 0.02, source_validation_cap_usd: 0, source_count: 0, source_validation_count: 0, target_slot_count: count,
  items: [{ ordinal: 1, revision_id: 'revision-new', candidate_id: 'candidate-new', actor_id: 'publisher-c/new', actor_public_name: '新 Actor', publisher: 'publisher-c', build_id: 'build-new', build_number: '2026.08.2', lifecycle: 'static_valid', authorized_cap_usd: 0.02, validation_profile: { timeout_seconds: 300, sample_items: 1, max_charge_usd: 0.02, supports_sample_items: true, options_hash: 'a'.repeat(64), profile_hash: 'f'.repeat(64) } }],
})

export function renderPoolManagement(selected = poolManagementDetail(), overrides: Partial<ServiceApi> = {}) {
  const summary = { ...selected, workflow: selected.workflow } as ApifyActorRoutesResponse['routes'][number]
  const api = {
    apifyActorRoutes: vi.fn().mockResolvedValue({ schema_version: 1, generation: 1, support_profiles: [], routes: [summary] }),
    apifyActorRoute: vi.fn().mockResolvedValue(selected),
    apifyActorDiscoveryRun: vi.fn().mockResolvedValue({ schema_version: 5, run_id: 'run-guided', route_id: selected.route_id, generation: selected.generation, stage: 'awaiting_canary_approval', status: 'completed', queries_completed: 1, queries_limit: 1, budget_cap_usd: 0.02, spent_usd: 0, candidate_count: 1, candidate_shortfall: 0, candidates: [], updated_at: selected.updated_at }),
    apifyActorPoolCandidates: vi.fn().mockResolvedValue({ schema_version: 1, route_id: selected.route_id, generation: selected.generation, goal: 'add_slot', target_slot: 'backup_2', run_id: 'run-guided', required_selection_count: 1, blockers: [], candidates: [{ candidate_id: 'candidate-new', actor_public_name: '新 Actor', publisher: 'publisher-c', pricing: {}, store_quality: { rating: 4.7, rating_count: 152, user_count: 195000 }, max_validation_charge_usd: 0.02, validation_options: { timeout_seconds: 300, timeout_min_seconds: 180, timeout_max_seconds: 900, sample_items: 1, allowed_sample_items: [1, 3, 5], max_charge_usd: 0.02, max_charge_limit_usd: 0.02, supports_sample_items: true, options_hash: 'a'.repeat(64), profile_hash: 'f'.repeat(64) }, already_validated: true, selectable: true, unavailable_reason: null }] }),
    activateVerifiedApifyActorPool: vi.fn().mockResolvedValue(selected),
    createApifyActorManualCanaryPlan: vi.fn().mockResolvedValue(plan(selected, 'add_slot', 'backup_2', 3)),
    apifyActorCanaryPlan: vi.fn().mockResolvedValue(plan(selected, 'add_slot', 'backup_2', 3)),
    apifyActorCanaryBatch: vi.fn(), apifyActorSourceSupport: vi.fn().mockResolvedValue({ slots: [] }), apifyActorFreshnessPlan: vi.fn().mockResolvedValue({}), apifyActorEvents: vi.fn().mockResolvedValue({ events: [] }), sources: vi.fn().mockResolvedValue({ sources: [] }),
    refreshApifyActorPoolCandidates: vi.fn(), removeApifyActorRouteActivePoolSlot: vi.fn().mockResolvedValue(selected), promoteApifyActorRouteActivePoolSlot: vi.fn().mockResolvedValue(selected), setApifyActorRoutePriceCap: vi.fn().mockResolvedValue(selected), ...overrides,
  } as unknown as ServiceApi
  const context = { api, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true }, query: '', setQuery: vi.fn(), activity: { state: 'idle', message: '' }, refresh: vi.fn(), reloadFeed: vi.fn(), beginAction: vi.fn(() => ({ userId: 'owner-1', generation: 0 })), isActionCurrent: vi.fn(() => true) } as unknown as AppOutletContext
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><MemoryRouter initialEntries={['/?route=x%2Fprofile%2Fitems&tab=pool']}><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<HeroActorOpsControlPlane />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  return { api, plan: (goal: 'add_slot' | 'replace_slot', slot: 'primary' | 'backup_2', count: 2 | 3) => plan(selected, goal, slot, count) }
}
