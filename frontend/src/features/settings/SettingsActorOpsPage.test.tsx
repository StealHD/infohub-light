import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type { AppOutletContext } from '../../app/AppContext'
import { SettingsActorOpsPage } from './SettingsActorOpsPage'

function renderPage(api: Partial<ServiceApi>, entry = '/settings/actorops') {
  const context = {
    api,
    user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true },
  } as AppOutletContext
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes><Route element={<Outlet context={context} />}><Route path="*" element={<SettingsActorOpsPage />} /></Route></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SettingsActorOpsPage', () => {
  it('uses the schema-2 v2 route read and never falls back to the legacy control plane', async () => {
    const actorOpsV2Routes = vi.fn().mockResolvedValue({
      schema_version: 2,
      routes: [{
        route_id: 'route-x', route_key: 'x/profile/items', platform: 'x', target_type: 'profile', capability: 'items',
        runtime_mode: 'disabled', generation: 3, per_run_cap_usd: 0.05, health: 'unavailable',
        active_candidate: null, standby_candidates: [], last_known_good: null,
        binding_summary: { ready_count: 0, pending_count: 1, disabled_count: 0 },
        maintenance_policy: { authorized: false, workspace: { enabled: false, monthly_budget_usd: 3, generation: 1 }, route: { enabled: false, max_probe_usd: 0.05, max_probes_per_utc_day: 5, auto_add_standby: false, auto_replace_non_last: false, generation: 1 }, budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 } },
        degraded_reason: 'actorops_v2_route_disabled', updated_at: null,
      }],
    })

    renderPage({ actorOpsV2Routes } as Partial<ServiceApi>)

    await waitFor(() => expect(actorOpsV2Routes).toHaveBeenCalled())
    expect(await screen.findByTestId('actorops-v2-control-plane')).toBeInTheDocument()
    expect(screen.getByText('ActorOps 已停用')).toBeInTheDocument()
    expect(screen.queryByText('旁路核验')).not.toBeInTheDocument()
  })

  it.each(['pool', 'sources', 'unexpected'])('keeps %s on the canonical routes tab', async (legacyTab) => {
    const actorOpsV2Routes = vi.fn().mockResolvedValue({ schema_version: 2, routes: [] })
    renderPage({ actorOpsV2Routes } as Partial<ServiceApi>, `/settings/actorops?tab=${legacyTab}`)

    await waitFor(() => expect(actorOpsV2Routes).toHaveBeenCalled())
    expect(await screen.findByText('暂无 ActorOps v2 Route')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '路由管理' })).toHaveAttribute('aria-selected', 'true')
  })

  it('opens legacy operations on logs without loading routes and scopes a deep-linked job', async () => {
    const actorOpsV2Routes = vi.fn()
    const actorOpsV2Events = vi.fn().mockResolvedValue({ schema_version: 3, availability: 'empty', events: [], returned: 0, truncated: false, window: { from: '2026-08-24T00:00:00Z', to: '2026-08-25T00:00:00Z' } })
    renderPage({
      actorOpsV2Routes,
      actorOpsV2Events,
      apifyActorAlertSettings: vi.fn().mockResolvedValue({ schema_version: 3, enabled: true, target_ids: [], events: [] }),
      apifyActorAlertIncidents: vi.fn().mockResolvedValue({ schema_version: 3, incidents: [] }),
    } as Partial<ServiceApi>, '/settings/actorops?tab=operations&job=job-safe_1')

    expect(await screen.findByTestId('actorops-v2-logs')).toBeInTheDocument()
    await waitFor(() => expect(actorOpsV2Events).toHaveBeenCalledWith({ job_id: 'job-safe_1' }, expect.anything()))
    expect(actorOpsV2Routes).not.toHaveBeenCalled()
    expect(screen.getByRole('tab', { name: '运行日志' })).toHaveAttribute('aria-selected', 'true')
  })

  it.each([
    ['actorops_v2_migration_required', 'ActorOps v2 需要数据库迁移'],
    ['actorops_v1_retired', '旧 ActorOps 控制面已退役'],
    ['actorops_v2_unavailable', 'ActorOps v2 当前不可用'],
  ])('renders %s as a contained v2 availability state', async (code, heading) => {
    renderPage({ actorOpsV2Routes: vi.fn().mockRejectedValue(new ApiError(code === 'actorops_v1_retired' ? 410 : 503, { code, message: code, retryable: code === 'actorops_v2_unavailable' })) } as Partial<ServiceApi>)

    expect(await screen.findByText(heading)).toBeInTheDocument()
    if (code === 'actorops_v2_unavailable') expect(screen.getByRole('button', { name: '重试此区域' })).toBeInTheDocument()
    else expect(screen.queryByRole('button', { name: '重试此区域' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('actorops-v2-control-plane')).not.toBeInTheDocument()
  })
})
