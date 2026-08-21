import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { AppOutletContext } from '../../app/AppContext'
import { ActorOpsV2RouteControls } from './ActorOpsV2RouteControls'
import type { ActorOpsV2RouteView } from './ActorOpsV2ControlPlane'

const route: ActorOpsV2RouteView = {
  actorops_version: 2, route_id: 'route-instagram', route_generation: 4,
  route_key: 'instagram/profile/items', platform: 'instagram', health: 'healthy',
  runtime_mode: 'active', last_known_good: null, last_success_at: null,
  degraded_reason: 'actorops_v2_binding_not_ready',
  active_candidate: {
    candidate_id: 'active', actor_id: 'opaque-active', publisher: 'instagram-scraper',
    build_number: '1.0.10', lifecycle: 'probationary', assignment: 'active', priority: 0, generation: 3,
  },
  standby_candidates: [{
    candidate_id: 'standby', actor_id: 'opaque-standby', publisher: 'backup-scraper',
    build_number: '1.0.1', lifecycle: 'probationary', assignment: 'standby', priority: 1, generation: 2,
  }],
  binding_summary: { ready_count: 1, pending_count: 1 },
}

function renderControls() {
  const api = {
    promoteActorOpsV2Candidate: vi.fn().mockResolvedValue({}),
    verifyActorOpsV2Bindings: vi.fn().mockResolvedValue({}),
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
  it('confirms a zero-cost primary switch and binding evidence check', async () => {
    const api = renderControls()
    const browser = userEvent.setup()

    await browser.click(screen.getByRole('button', { name: /设为主用/ }))
    await browser.type(screen.getByRole('textbox', { name: '确认短语' }), '确认设为主用 Actor')
    await browser.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(api.promoteActorOpsV2Candidate).toHaveBeenCalledWith('route-instagram', 'standby', {
      expected_route_generation: 4, expected_candidate_generation: 2, confirmation: '确认设为主用 Actor',
    }))

    await browser.click(screen.getByRole('button', { name: '核验待处理来源' }))
    await browser.type(screen.getByRole('textbox', { name: '确认短语' }), '确认核验来源绑定')
    await browser.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(api.verifyActorOpsV2Bindings).toHaveBeenCalledWith('route-instagram', {
      expected_route_generation: 4, confirmation: '确认核验来源绑定',
    }))
  })
})
