import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { poolManagementDetail, renderPoolManagement } from './actorOpsPoolManagementTestFixtures'

describe('HeroActorOpsControlPlane verified Actor catalog', () => {
  it('never renders raw discovery inventory as selectable Actors', async () => {
    const selected = {
      ...poolManagementDetail(),
      workflow: {
        kind: 'backup_2_discovery_running', goal: 'complete_third' as const,
        run_id: 'run-searching', progress: {}, blockers: [],
      },
    }
    const { api } = renderPoolManagement(selected, {
      apifyActorDiscoveryRun: vi.fn().mockResolvedValue({
        schema_version: 5, run_id: 'run-searching', route_id: selected.route_id,
        generation: selected.generation, stage: 'searching', status: 'searching',
        queries_completed: 1, queries_limit: 3, budget_cap_usd: 0.02,
        candidates: [{ revision: { actor_public_name: '待测 Actor' } }],
      }),
    })

    await waitFor(() => expect(api.apifyActorDiscoveryRun).toHaveBeenCalled())
    expect(await screen.findByText(/已完成 1\/3 轮查询/)).toBeVisible()
    expect(screen.queryByText('待测 Actor')).not.toBeInTheDocument()
  })

  it('shows only settled candidates and enables the chosen one without a Canary', async () => {
    const selected = poolManagementDetail()
    const { api } = renderPoolManagement(selected, {
      apifyActorPoolCandidates: vi.fn().mockResolvedValue({
        schema_version: 1, route_id: selected.route_id, generation: selected.generation,
        goal: 'add_slot', target_slot: 'backup_2', run_id: 'run-guided',
        required_selection_count: 1, blockers: ['candidate_verification_pending'],
        candidates: [
          {
            candidate_id: 'candidate-settled', actor_public_name: '已验证 Actor',
            publisher: 'publisher-c', pricing: {}, max_validation_charge_usd: 0.02,
            already_validated: true, selectable: true, unavailable_reason: null,
          },
          {
            candidate_id: 'candidate-pending', actor_public_name: '待测 Actor',
            publisher: 'publisher-d', pricing: {}, max_validation_charge_usd: 0.02,
            already_validated: false, selectable: true, unavailable_reason: null,
          },
        ],
      }),
    })
    const browser = userEvent.setup()

    await browser.click(await screen.findByRole('button', { name: '添加 Actor' }))
    expect(await screen.findByText('这里只显示已验证 Actor')).toBeVisible()
    expect(screen.getByText('已验证 Actor')).toBeVisible()
    expect(screen.queryByText('待测 Actor')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('checkbox', { name: /已验证 Actor/ }))
    await browser.click(screen.getByRole('button', { name: '选择并启用' }))

    await waitFor(() => expect(api.activateVerifiedApifyActorPool).toHaveBeenCalledWith(
      selected.route_id,
      expect.objectContaining({
        run_id: 'run-guided', candidate_ids: ['candidate-settled'],
        goal: 'add_slot', target_slot: 'backup_2', target_slot_count: 3,
      }),
    ))
    expect(api.createApifyActorManualCanaryPlan).not.toHaveBeenCalled()
  })
})
