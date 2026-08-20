import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ActorOpsV2ControlPlane } from './ActorOpsV2ControlPlane'

describe('ActorOpsV2ControlPlane', () => {
  it('shows only v2 route health, assignment, LKG and maintenance projections', () => {
    render(
      <ActorOpsV2ControlPlane
        routes={[
          {
            actorops_version: 2,
            route_id: 'route-youtube',
            route_key: 'youtube/channel/items',
            platform: 'youtube',
            health: 'degraded',
            runtime_mode: 'shadow',
            active_candidate: {
              candidate_id: 'active', actor_id: 'publisher/actor', publisher: 'publisher',
              build_number: '1', lifecycle: 'certified', assignment: 'active', priority: 0,
            },
            standby_candidates: [],
            last_known_good: null,
            last_success_at: null,
            degraded_reason: 'actorops_v2_single_runnable_candidate',
            maintenance_policy: {
              authorized: false,
              workspace: { enabled: false, monthly_budget_usd: 3, generation: 1 },
              route: {
                enabled: false, max_probe_usd: 0.05, max_probes_per_utc_day: 5,
                auto_add_standby: true, auto_replace_non_last: true, generation: 1,
              },
              budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 },
            },
          },
        ]}
      />,
    )

    expect(screen.getByTestId('actorops-v2-control-plane')).toBeInTheDocument()
    expect(screen.getByText('降级可用')).toBeInTheDocument()
    expect(screen.getByText('publisher/actor')).toBeInTheDocument()
    expect(screen.getByText(/历史批次和发现阶段不在此界面出现/)).toBeInTheDocument()
    expect(screen.queryByText(/Canary/)).not.toBeInTheDocument()
  })
})
