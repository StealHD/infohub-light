import type { ApiClient } from './client'
import type {
  ApifyActorActivePoolRemove,
  ApifyActorCanaryBatch,
  ApifyActorCanaryBatchRequest,
  ApifyActorCanaryBatchResponse,
  ApifyActorCanaryPlan,
  ApifyActorPoolCandidateRefresh,
  ApifyActorPoolCandidates,
  ApifyActorPoolGoal,
  ApifyActorRouteDetail,
  ApifyActorValidationProfileRequest,
} from './types'

const resource = (path: string, id: string) => `${path}/${encodeURIComponent(id)}`
type Slot = 'primary' | 'backup_1' | 'backup_2'
type BackupSlot = Exclude<Slot, 'primary'>
type ApifyActorAutoPoolRun = {
  run_id: string
  route_id: string
  slot_name: Slot
  goal: 'add_slot' | 'replace_slot'
  status: 'running' | 'succeeded' | 'budget_exhausted' | 'failed' | 'cancelled'
  budget_cap_usd: number
  total_spent_usd: number
  last_discovery_run_id?: string | null
  last_canary_batch_id?: string | null
  error_code?: string | null
  updated_at: string
}

export function actorOpsPoolManagementApi(client: ApiClient) {
  return {
    apifyActorCanaryPlan: (
      runId: string, goal: ApifyActorPoolGoal = 'initial_pool', signal?: AbortSignal, targetSlot?: Slot,
    ) => client.get<ApifyActorCanaryPlan>(
      `${resource('/api/admin/apify-discovery-runs', runId)}/canary-plan?goal=${encodeURIComponent(goal)}${targetSlot ? `&target_slot=${encodeURIComponent(targetSlot)}` : ''}`,
      signal,
    ),
    apifyActorPoolCandidates: (
      routeId: string, goal: ApifyActorPoolGoal, signal?: AbortSignal, targetSlot?: Slot,
    ) => client.get<ApifyActorPoolCandidates>(
      `${resource('/api/admin/apify-routes', routeId)}/pool-candidates?goal=${encodeURIComponent(goal)}${targetSlot ? `&target_slot=${encodeURIComponent(targetSlot)}` : ''}`,
      signal,
    ),
    refreshApifyActorPoolCandidates: (
      routeId: string, expectedGeneration: number, goal: ApifyActorPoolGoal = 'initial_pool', targetSlot?: Slot,
    ) => client.post<ApifyActorPoolCandidateRefresh>(
      `${resource('/api/admin/apify-routes', routeId)}/pool-candidates/refresh`,
      { expected_generation: expectedGeneration, goal, ...(targetSlot ? { target_slot: targetSlot } : {}) },
    ),
    createApifyActorManualCanaryPlan: (
      runId: string,
      payload: {
        goal: ApifyActorPoolGoal
        candidate_ids: string[]
        candidate_validation_profiles: ApifyActorValidationProfileRequest[]
        expected_generation: number
        target_slot_count: 1 | 2 | 3
        target_slot?: Slot
      },
    ) => client.post<ApifyActorCanaryPlan>(
      `${resource('/api/admin/apify-discovery-runs', runId)}/canary-plan`, payload,
    ),
    activateVerifiedApifyActorPool: (
      routeId: string,
      payload: {
        run_id: string
        goal: ApifyActorPoolGoal
        candidate_ids: string[]
        expected_generation: number
        target_slot_count: 1 | 2 | 3
        target_slot?: Slot
      },
    ) => client.post<ApifyActorRouteDetail>(
      `${resource('/api/admin/apify-routes', routeId)}/verified-pool-activation`, payload,
    ),
    createApifyActorCanaryBatch: (runId: string, payload: ApifyActorCanaryBatchRequest) => (
      client.post<ApifyActorCanaryBatchResponse>(
        `${resource('/api/admin/apify-discovery-runs', runId)}/canary-batches`, payload,
      )
    ),
    apifyActorCanaryBatch: (batchId: string, signal?: AbortSignal) => (
      client.get<ApifyActorCanaryBatch>(resource('/api/admin/apify-canary-batches', batchId), signal)
    ),
    removeApifyActorRouteActivePoolSlot: (routeId: string, payload: ApifyActorActivePoolRemove) => (
      client.post<ApifyActorRouteDetail>(`${resource('/api/admin/apify-routes', routeId)}/active-pool/remove`, payload)
    ),
    promoteApifyActorRouteActivePoolSlot: (
      routeId: string,
      payload: { target_slot: BackupSlot; expected_generation: number; confirmation: '确认设为主用 Actor' },
    ) => client.post<ApifyActorRouteDetail>(
      `${resource('/api/admin/apify-routes', routeId)}/active-pool/promote`, payload,
    ),
    setApifyActorRoutePriceCap: (
      routeId: string,
      payload: { expected_generation: number; per_run_cap_usd: number },
    ) => client.patch<ApifyActorRouteDetail>(
      `${resource('/api/admin/apify-routes', routeId)}/price-cap`, payload,
    ),
    startApifyActorAutoPool: (
      routeId: string,
      payload: {
        goal: 'add_slot' | 'replace_slot'
        target_slot: Slot
        expected_generation: number
        budget_cap_usd?: number
      },
    ) => client.post<{ run: ApifyActorAutoPoolRun }>(
      `${resource('/api/admin/apify-routes', routeId)}/auto-pool`, payload,
    ),
    apifyActorAutoPoolRun: (runId: string, signal?: AbortSignal) => (
      client.get<{ run: ApifyActorAutoPoolRun }>(
        resource('/api/admin/apify-auto-pool-runs', runId), signal,
      )
    ),
  }
}
