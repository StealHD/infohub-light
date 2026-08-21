import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ActorOpsV2ControlPlane } from './ActorOpsV2ControlPlane'

describe('ActorOpsV2ControlPlane', () => {
  it('shows readable v2 route selection without internal Actor identifiers', () => {
    render(
      <ActorOpsV2ControlPlane
        routes={[
          {
            actorops_version: 2,
            route_id: 'route-youtube',
            route_generation: 2,
            route_key: 'youtube/channel/items',
            platform: 'youtube',
            health: 'degraded',
            runtime_mode: 'shadow',
            active_candidate: {
              candidate_id: 'active', actor_id: 'publisher/actor', publisher: 'publisher',
              build_number: '1', lifecycle: 'certified', assignment: 'active', priority: 0, generation: 2,
            },
            standby_candidates: [],
            last_known_good: null,
            last_success_at: null,
            degraded_reason: 'actorops_v2_single_runnable_candidate',
            binding_summary: { ready_count: 1, pending_count: 0 },
          },
        ]}
      />,
    )

    expect(screen.getByTestId('actorops-v2-control-plane')).toBeInTheDocument()
    expect(screen.getByText('降级可用')).toBeInTheDocument()
    expect(screen.getByText('YouTube 视频更新')).toBeInTheDocument()
    expect(screen.getByText('Publisher · 版本 1')).toBeInTheDocument()
    expect(screen.queryByText('publisher/actor')).not.toBeInTheDocument()
    expect(screen.getByText(/切换主用或核验来源不会启动 Actor/)).toBeInTheDocument()
    expect(screen.queryByText(/Probe/)).not.toBeInTheDocument()
  })
})
