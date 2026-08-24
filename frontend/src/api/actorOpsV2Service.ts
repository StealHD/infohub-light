import type { ApiClient } from './client'
import type {
  ActorOpsV2OperationEvents,
  ActorOpsV2Candidate,
  ActorOpsV2ReplacementPlan,
  ActorOpsV2RouteDetail,
  ActorOpsV2RoutesResponse,
} from './actorOpsV2Types'

const resource = (path: string, id: string) => `${path}/${encodeURIComponent(id)}`

export function actorOpsV2Api(client: ApiClient) {
  return {
    actorOpsV2Routes: (signal?: AbortSignal) => client.get<ActorOpsV2RoutesResponse>(
      '/api/admin/apify-routes', signal,
    ),
    actorOpsV2Route: (routeId: string, signal?: AbortSignal) => client.get<ActorOpsV2RouteDetail>(
      resource('/api/admin/apify-routes', routeId), signal,
    ),
    actorOpsV2Events: (
      params: { action?: string; job_id?: string; route_id?: string; repair_id?: string; phase?: string; outcome?: string; cursor?: string; source_id?: string; since?: string; until?: string; limit?: number } = {},
      signal?: AbortSignal,
    ) => {
      const query = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== '') query.set(key, String(value))
      })
      const suffix = query.toString()
      return client.get<ActorOpsV2OperationEvents>(
        `/api/admin/apify-actor-events${suffix ? `?${suffix}` : ''}`,
        signal,
      )
    },
    promoteActorOpsV2Candidate: (
      routeId: string,
      candidateId: string,
      payload: { expected_route_generation: number; expected_candidate_generation: number; confirmation: '确认设为主用 Actor' },
    ) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-candidates/${encodeURIComponent(candidateId)}/promote`, payload,
    ),
    verifyActorOpsV2Bindings: (
      routeId: string,
      payload: { expected_route_generation: number; confirmation: '确认核验来源绑定' },
    ) => client.post<Record<string, unknown>>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-bindings/verify`, payload,
    ),
    actorOpsV2Candidates: (routeId: string, signal?: AbortSignal) => client.get<{ candidates: ActorOpsV2Candidate[] }>(
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
    }) => client.post<ActorOpsV2ReplacementPlan>(`${resource('/api/admin/apify-routes', routeId)}/v2-replacements`, payload),
    actorOpsV2Replacement: (routeId: string, planId: string, signal?: AbortSignal) => client.get<ActorOpsV2ReplacementPlan>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}`, signal,
    ),
    authorizeActorOpsV2Replacement: (routeId: string, planId: string, payload: { expected_generation: number; confirmation: '确认实测替换 Actor' }) => client.post<ActorOpsV2ReplacementPlan>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}/authorize`, payload,
    ),
    applyActorOpsV2Replacement: (routeId: string, planId: string, payload: { expected_generation: number; confirmation: '确认替换 Actor' }) => client.post<ActorOpsV2ReplacementPlan>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}/apply`, payload,
    ),
    cancelActorOpsV2Replacement: (routeId: string, planId: string, payload: { expected_generation: number }) => client.post<ActorOpsV2ReplacementPlan>(
      `${resource('/api/admin/apify-routes', routeId)}/v2-replacements/${encodeURIComponent(planId)}/cancel`, payload,
    ),
  }
}
