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
        apply_id: string
        confirmation: '确认启用 Actor 主备'
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
    promoteActorOpsV2Candidate: (
      routeId: string,
      candidateId: string,
      payload: {
        expected_route_generation: number
        expected_candidate_generation: number
        confirmation: '确认设为主用 Actor'
      },
    ) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-candidates/${encodeURIComponent(candidateId)}/promote`,
      payload,
    ),
    verifyActorOpsV2Bindings: (
      routeId: string,
      payload: { expected_route_generation: number; confirmation: '确认核验来源绑定' },
    ) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-bindings/verify`,
      payload,
    ),
    actorOpsV2Candidates: (routeId: string, signal?: AbortSignal) => client.get<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-candidates`, signal,
    ),
    refreshActorOpsV2Metadata: (routeId: string, payload: { expected_route_generation: number }) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-metadata/refresh`, payload,
    ),
    discoverActorOpsV2Candidates: (routeId: string, payload: { expected_route_generation: number }) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-discoveries`, payload,
    ),
    setActorOpsV2PriceCap: (routeId: string, payload: { expected_route_generation: number; cap_usd: number; confirmation?: '确认提高 Actor 费用上限' }) => client.patch<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-price-cap`, payload,
    ),
    createActorOpsV2Replacement: (routeId: string, payload: {
      target_assignment: 'active' | 'standby'; target_priority: number; candidate_id: string
      expected_route_generation: number; expected_candidate_generation: number; idempotency_key: string
      per_probe_cap_usd: number; total_cap_usd: number
    }) => client.post<Record<string, unknown>>(`${resource('/api/admin/apify-routes', routeId)}/v2-replacements`, payload),
    actorOpsV2Replacement: (routeId: string, planId: string, signal?: AbortSignal) => client.get<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}`, signal,
    ),
    authorizeActorOpsV2Replacement: (routeId: string, planId: string, payload: { expected_generation: number; confirmation: '确认实测替换 Actor' }) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}/authorize`, payload,
    ),
    applyActorOpsV2Replacement: (routeId: string, planId: string, payload: { expected_generation: number; confirmation: '确认替换 Actor' }) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}/apply`, payload,
    ),
    cancelActorOpsV2Replacement: (routeId: string, planId: string, payload: { expected_generation: number }) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}/cancel`, payload,
    ),
    setApifyActorRoutePriceCap: (
      routeId: string,
      payload: { expected_generation: number; per_run_cap_usd: number },
    ) => client.patch<ApifyActorRouteDetail>(
      `${resource('/api/admin/apify-routes', routeId)}/price-cap`, payload,
    ),
  }
}
