import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import type { ApifyActorDiscoveryRun } from '../../api/types'
import { poolManagementDetail, renderPoolManagement } from './actorOpsPoolManagementTestFixtures'

it('refreshes the exact slot candidate catalog when delayed free discovery settles', async () => {
  const selected = poolManagementDetail()
  let settleDiscovery: ((value: ApifyActorDiscoveryRun) => void) | undefined
  const delayedDiscovery = new Promise<ApifyActorDiscoveryRun>((resolve) => { settleDiscovery = resolve })
  const candidates = vi.fn().mockResolvedValue({
    schema_version: 1, route_id: selected.route_id, generation: selected.generation,
    goal: 'add_slot', target_slot: 'backup_2', run_id: 'run-free-search',
    required_selection_count: 1, blockers: [], candidates: [],
  })
  const { api } = renderPoolManagement(selected, {
    apifyActorPoolCandidates: candidates,
    refreshApifyActorPoolCandidates: vi.fn().mockResolvedValue({
      schema_version: 1, route_id: selected.route_id,
      generation: selected.generation, route_generation: selected.generation,
      run_id: 'run-free-search', status: 'queued', job: { id: 'job-free-search', status: 'queued' },
    }),
    apifyActorDiscoveryRun: vi.fn((runId: string) => runId === 'run-free-search'
      ? delayedDiscovery
      : Promise.resolve({
        schema_version: 5, run_id: 'run-guided', route_id: selected.route_id,
        generation: selected.generation, stage: 'awaiting_canary_approval', status: 'completed',
        queries_completed: 1, queries_limit: 1, budget_cap_usd: 0.02, candidates: [],
      } as ApifyActorDiscoveryRun)),
  })
  const browser = userEvent.setup()

  await browser.click(await screen.findByRole('button', { name: '添加 Actor' }))
  await waitFor(() => expect(candidates).toHaveBeenCalledTimes(1))
  await browser.click(screen.getByRole('button', { name: '自动搜索候选（免费）' }))
  await waitFor(() => expect(api.refreshApifyActorPoolCandidates).toHaveBeenCalledWith(
    selected.route_id, selected.generation, 'add_slot', 'backup_2',
  ))
  const callsBeforeTerminal = candidates.mock.calls.length
  await act(async () => settleDiscovery?.({
    schema_version: 5, run_id: 'run-free-search', route_id: selected.route_id,
    generation: selected.generation, stage: 'candidate_shortfall', status: 'completed',
    queries_completed: 3, queries_limit: 3, budget_cap_usd: 0.02,
    candidate_count: 0, candidate_shortfall: 1, candidates: [], updated_at: selected.updated_at,
  } as ApifyActorDiscoveryRun))
  await waitFor(() => expect(candidates.mock.calls.length).toBeGreaterThan(callsBeforeTerminal))
})
