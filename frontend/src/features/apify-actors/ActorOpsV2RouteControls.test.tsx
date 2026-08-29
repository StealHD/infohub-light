import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { AppOutletContext } from '../../app/AppContext'
import { ActorOpsV2RouteControls } from './ActorOpsV2RouteControls'
import { actorOpsV2RouteView, type ActorOpsV2RouteView } from './actorOpsV2RouteModel'

const route: ActorOpsV2RouteView = actorOpsV2RouteView({
  route_id: 'route-instagram', generation: 4,
  route_key: 'instagram/profile/items', platform: 'instagram', health: 'healthy',
  health_reason: 'all_sources_redundant', stable_candidate_count: 2, cooling_candidate_count: 0,
  at_risk_source_count: 0, unavailable_source_count: 0, fallback_source_count: 0, next_repair_at: null,
  target_type: 'profile', capability: 'items', runtime_mode: 'active', per_run_cap_usd: 0.05, last_known_good: null,
  degraded_reason: 'actorops_v2_binding_not_ready',
  active_candidate: {
    candidate_id: 'active', build_number: '1.0.10', lifecycle: 'probationary', assignment: 'active', priority: 0, generation: 3,
    operational_status: 'normal', issue_code: null, last_success_at: null, last_failure_at: null, retry_at: null, avatar_mapping_status: 'ready',
    store_metadata: null, evidence_progress: { verified_bindings: 1, required_bindings: 1 },
  },
  standby_candidates: [{
    candidate_id: 'standby', build_number: '1.0.1', lifecycle: 'probationary', assignment: 'standby', priority: 1, generation: 2,
    operational_status: 'normal', issue_code: null, last_success_at: null, last_failure_at: null, retry_at: null, avatar_mapping_status: 'ready',
    store_metadata: null, evidence_progress: { verified_bindings: 1, required_bindings: 1 },
  }],
  binding_summary: { ready_count: 1, pending_count: 1, disabled_count: 0 },
  maintenance_policy: { authorized: false, workspace: { enabled: false, monthly_budget_usd: 0, generation: 1, authorization_origin: 'none' }, route: { enabled: false, max_probe_usd: 0.01, max_probes_per_utc_day: 1, auto_add_standby: false, auto_replace_non_last: false, generation: 1, authorization_origin: 'none' }, budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 } },
  updated_at: null,
})

function renderControls(routeValue = route) {
  const api = {
    promoteActorOpsV2Candidate: vi.fn().mockResolvedValue({}),
    reconcileActorOpsV2Bindings: vi.fn().mockResolvedValue({}),
    setActorOpsV2PriceCap: vi.fn().mockResolvedValue({}),
    actorOpsV2Candidates: vi.fn().mockResolvedValue({ candidates: [] }),
    refreshActorOpsV2Metadata: vi.fn().mockResolvedValue({}),
    discoverActorOpsV2Candidates: vi.fn().mockResolvedValue({}),
    createActorOpsV2Replacement: vi.fn().mockResolvedValue({}),
    authorizeActorOpsV2Replacement: vi.fn().mockResolvedValue({}),
    applyActorOpsV2Replacement: vi.fn().mockResolvedValue({}),
  } as unknown as ServiceApi
  const context = {
    api, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true },
  } as unknown as AppOutletContext
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <MemoryRouter><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<ActorOpsV2RouteControls route={routeValue} />} /></Route></Routes></MemoryRouter>
  </QueryClientProvider>)
  return api
}

describe('ActorOpsV2RouteControls', () => {
  it('confirms a zero-cost primary switch and rechecks bindings without a phrase', async () => {
    const api = renderControls()
    const browser = userEvent.setup()

    await browser.click(screen.getByRole('button', { name: 'Actor 路由更多操作' }))
    await browser.click(screen.getByRole('button', { name: '设为主用' }))
    await browser.type(screen.getByRole('textbox', { name: '确认短语' }), '确认设为主用 Actor')
    await browser.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(api.promoteActorOpsV2Candidate).toHaveBeenCalledWith('route-instagram', 'standby', {
      expected_route_generation: 4, expected_candidate_generation: 2, confirmation: '确认设为主用 Actor',
    }))

    await browser.click(screen.getByRole('button', { name: 'Actor 路由更多操作' }))
    await browser.click(screen.getByRole('button', { name: '重新检查准备中的来源' }))
    await waitFor(() => expect(api.reconcileActorOpsV2Bindings).toHaveBeenCalledWith('route-instagram', {
      expected_route_generation: 4,
    }))
    expect(screen.queryByText('核验待处理来源')).not.toBeInTheDocument()
  })

  it('requires the raise confirmation before changing the future per-run cap', async () => {
    const api = renderControls()
    const browser = userEvent.setup()

    await browser.click(screen.getByRole('button', { name: '调整单次费用上限' }))
    const input = screen.getByRole('textbox', { name: '美元（最高 $0.20）' })
    await browser.clear(input)
    await browser.type(input, '0.08')
    expect(screen.getByText('输入“确认提高 Actor 费用上限”')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    await browser.type(screen.getByRole('textbox', { name: '输入“确认提高 Actor 费用上限”' }), '确认提高 Actor 费用上限')
    await browser.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(api.setActorOpsV2PriceCap).toHaveBeenCalledWith('route-instagram', {
      expected_route_generation: 4, cap_usd: 0.08, confirmation: '确认提高 Actor 费用上限',
    }))
  })

  it('opens the replacement drawer without starting a paid Candidate', async () => {
    const api = renderControls()
    const browser = userEvent.setup()

    await browser.click(screen.getByRole('button', { name: '管理 Actor' }))
    expect(await screen.findByRole('heading', { name: '管理 Actor' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '替换主用' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '替换备用 1' })).toBeInTheDocument()
    expect(api.createActorOpsV2Replacement).not.toHaveBeenCalled()
    expect(api.authorizeActorOpsV2Replacement).not.toHaveBeenCalled()
  })

  it('shows direct replacement actions for failed active and standby slots', () => {
    renderControls({
      ...route,
      active_candidate: { ...route.active_candidate!, operational_status: 'confirmed_failure', issue_code: 'build_unavailable' },
      standby_candidates: route.standby_candidates.map((candidate) => ({ ...candidate, operational_status: 'confirmed_failure', issue_code: 'repeated_start_rejection' })),
    })

    expect(screen.getByRole('button', { name: '替换主用' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '替换备用 1' })).toBeInTheDocument()
  })

  it('uses persisted standby priorities for direct replacement targets', async () => {
    const browser = userEvent.setup()
    renderControls({
      ...route,
      standby_candidates: [
        { ...route.standby_candidates[0], candidate_id: 'standby-two', priority: 2, operational_status: 'confirmed_failure', issue_code: 'repeated_start_rejection' },
        { ...route.standby_candidates[0], candidate_id: 'standby-one', priority: 1, operational_status: 'confirmed_failure', issue_code: 'repeated_start_rejection' },
      ],
    })

    expect(screen.getByRole('button', { name: '替换备用 1' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '替换备用 2' }))
    expect(await screen.findByRole('heading', { name: '替换备用 2 Actor' })).toBeInTheDocument()
  })

  it('offers direct supplement actions for empty standby slots', async () => {
    const browser = userEvent.setup()
    renderControls({ ...route, standby_candidates: [] })

    expect(screen.getByRole('button', { name: '补充备用 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '补充备用 2' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '补充备用 1' }))
    expect(await screen.findByRole('heading', { name: '补充备用 1 Actor' })).toBeInTheDocument()
  })
})
