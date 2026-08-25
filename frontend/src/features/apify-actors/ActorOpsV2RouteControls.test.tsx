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
  target_type: 'profile', capability: 'items', runtime_mode: 'active', per_run_cap_usd: 0.05, last_known_good: null,
  degraded_reason: 'actorops_v2_binding_not_ready',
  active_candidate: {
    candidate_id: 'active', build_number: '1.0.10', lifecycle: 'probationary', assignment: 'active', priority: 0, generation: 3,
    store_metadata: null, evidence_progress: { verified_bindings: 1, required_bindings: 1 },
  },
  standby_candidates: [{
    candidate_id: 'standby', build_number: '1.0.1', lifecycle: 'probationary', assignment: 'standby', priority: 1, generation: 2,
    store_metadata: null, evidence_progress: { verified_bindings: 1, required_bindings: 1 },
  }],
  binding_summary: { ready_count: 1, pending_count: 1, disabled_count: 0 },
  maintenance_policy: { authorized: false, workspace: { enabled: false, monthly_budget_usd: 0, generation: 1 }, route: { enabled: false, max_probe_usd: 0.01, max_probes_per_utc_day: 1, auto_add_standby: false, auto_replace_non_last: false, generation: 1 }, budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 } },
  updated_at: null,
})

function renderControls() {
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
    <MemoryRouter><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<ActorOpsV2RouteControls route={route} />} /></Route></Routes></MemoryRouter>
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

    await browser.click(screen.getByRole('button', { name: 'Actor 路由更多操作' }))
    await browser.click(screen.getByRole('button', { name: '替换主用 Actor' }))
    expect(await screen.findByText('替换 Actor')).toBeInTheDocument()
    expect(api.createActorOpsV2Replacement).not.toHaveBeenCalled()
    expect(api.authorizeActorOpsV2Replacement).not.toHaveBeenCalled()
  })
})
