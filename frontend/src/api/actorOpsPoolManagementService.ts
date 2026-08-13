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
  }
}
