import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ActorOpsV2ControlPlane } from './ActorOpsV2ControlPlane'
import { actorOpsV2RouteView } from './actorOpsV2RouteModel'

describe('ActorOpsV2ControlPlane', () => {
  it('shows readable v2 route selection and a safe Store preview without internal identifiers', async () => {
    render(
      <ActorOpsV2ControlPlane
        routes={[
          actorOpsV2RouteView({
            route_id: 'route-youtube',
            route_key: 'youtube/channel/items',
            platform: 'youtube',
            target_type: 'channel',
            capability: 'items',
            health: 'degraded',
            runtime_mode: 'disabled',
            generation: 2,
            per_run_cap_usd: 0.05,
            active_candidate: {
              candidate_id: 'active', build_number: '1', lifecycle: 'certified', assignment: 'active', priority: 0, generation: 2,
              store_metadata: { actor_slug: 'publisher/actor', display_name: 'Instagram API Scraper', short_description: null, developer_name: 'Apify', maintained_by_apify: true, rating: 4.7, review_count: 10, bookmark_count: 2, total_users: 10, monthly_active_users: 2, pricing: [], last_modified_at: null, observed_at: '2026-08-21T00:00:00+00:00', generation: 1 }, evidence_progress: { verified_bindings: 1, required_bindings: 1 },
            },
            standby_candidates: [],
            last_known_good: null,
            degraded_reason: 'actorops_v2_single_runnable_candidate',
            binding_summary: { ready_count: 1, pending_count: 0, disabled_count: 0 },
            maintenance_policy: { authorized: false, workspace: { enabled: false, monthly_budget_usd: 0, generation: 1 }, route: { enabled: false, max_probe_usd: 0.01, max_probes_per_utc_day: 1, auto_add_standby: false, auto_replace_non_last: false, generation: 1 }, budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 } },
            updated_at: null,
          }),
        ]}
      />,
    )

    expect(screen.getByTestId('actorops-v2-control-plane')).toBeInTheDocument()
    expect(screen.getAllByTestId('actorops-v2-control-plane').length).toBe(1)
    expect(screen.getByTestId('actorops-v2-control-plane').querySelectorAll('[data-actorops-route-card]')).toHaveLength(1)
    expect(screen.getByText('降级可用')).toBeInTheDocument()
    expect(screen.getByText('YouTube 视频更新')).toBeInTheDocument()
    expect(screen.getByText('主用')).toBeInTheDocument()
    expect(screen.getByText('Instagram API Scraper')).toBeInTheDocument()
    expect(screen.queryByText('publisher/actor')).not.toBeInTheDocument()
    expect(screen.getByText(/商城标价只作参考/)).toBeInTheDocument()
    expect(screen.queryByText(/Probe/)).not.toBeInTheDocument()
    await userEvent.setup().hover(screen.getByRole('button', { name: '查看Instagram API Scraper商城信息' }))
    expect(await screen.findByText('评分')).toBeInTheDocument()
    expect(screen.getByText('Maintained by Apify', { exact: false })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '打开 Apify' })).toHaveAttribute('href', 'https://apify.com/publisher/actor')
  })

  it('normalizes an invalid legacy transport mode to disabled', () => {
    const route = actorOpsV2RouteView({
      route_id: 'route-x', route_key: 'x/profile/items', platform: 'x', target_type: 'profile', capability: 'items',
      runtime_mode: 'legacy', generation: 1, per_run_cap_usd: 0.05, health: 'unavailable', active_candidate: null,
      standby_candidates: [], last_known_good: null, binding_summary: { ready_count: 0, pending_count: 0, disabled_count: 0 },
      maintenance_policy: { authorized: false, workspace: { enabled: false, monthly_budget_usd: 0, generation: 1 }, route: { enabled: false, max_probe_usd: 0.01, max_probes_per_utc_day: 1, auto_add_standby: false, auto_replace_non_last: false, generation: 1 }, budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 } },
      degraded_reason: null, updated_at: null,
    })

    render(<ActorOpsV2ControlPlane routes={[route]} />)

    expect(screen.getByText('ActorOps 已停用')).toBeInTheDocument()
    expect(screen.queryByText(/legacy/i)).not.toBeInTheDocument()
  })
})
