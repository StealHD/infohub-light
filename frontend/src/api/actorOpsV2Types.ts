export type ActorOpsV2StoreMetadata = {
  actor_slug: string
  display_name: string
  short_description: string | null
  developer_name: string | null
  maintained_by_apify: boolean
  rating: number | null
  review_count: number | null
  bookmark_count: number | null
  total_users: number | null
  monthly_active_users: number | null
  pricing: Array<Record<string, unknown>>
  last_modified_at: string | null
  observed_at: string
  generation: number
}

export type ActorOpsV2Candidate = {
  candidate_id: string
  build_number: string | null
  lifecycle: string
  assignment: string
  priority: number | null
  generation: number
  last_success_at?: string | null
  last_failure_at?: string | null
  last_error_code?: string | null
  store_metadata: ActorOpsV2StoreMetadata | null
  evidence_progress: { verified_bindings: number; required_bindings: number }
}

export type ActorOpsV2MaintenancePolicy = {
  authorized: boolean
  workspace: { enabled: boolean; monthly_budget_usd: number; generation: number }
  route: {
    enabled: boolean
    max_probe_usd: number
    max_probes_per_utc_day: number
    auto_add_standby: boolean
    auto_replace_non_last: boolean
    generation: number
  }
  budget: { spent_usd: number; reserved_usd: number; probe_count: number }
}

export type ActorOpsV2BindingSummary = {
  ready_count: number
  pending_count: number
  disabled_count: number
}

export type ActorOpsV2RuntimeMode = 'active' | 'disabled'

export type ActorOpsV2RouteSummary = {
  route_id: string
  route_key: string
  platform: string
  target_type: string
  capability: string
  runtime_mode: ActorOpsV2RuntimeMode
  generation: number
  per_run_cap_usd: number
  health: 'healthy' | 'degraded' | 'unavailable'
  active_candidate: ActorOpsV2Candidate | null
  standby_candidates: ActorOpsV2Candidate[]
  last_known_good: ActorOpsV2Candidate | null
  binding_summary: ActorOpsV2BindingSummary
  maintenance_policy: ActorOpsV2MaintenancePolicy
  degraded_reason: string | null
  updated_at: string | null
}

/** Raw transport accepts a retired mode so the view can fail closed during migration. */
export type ActorOpsV2RouteTransport = Omit<ActorOpsV2RouteSummary, 'runtime_mode'> & {
  runtime_mode: string
}

export type ActorOpsV2Binding = {
  binding_id: string
  status: 'pending' | 'ready' | 'disabled'
  binding_version: number
  preferred_candidate_id: string | null
  last_known_good_candidate_id: string | null
  last_success_at: string | null
}

export type ActorOpsV2Attempt = {
  attempt_id: string
  kind: string
  status: string
  result_state: string
  semantic_outcome: string | null
  failure_class: string | null
  error_code: string | null
  reserved_usd: number
  actual_cost_usd: number | null
  cost_final: boolean
  created_at: string
  terminal_at: string | null
  updated_at: string
}

export type ActorOpsV2Discovery = {
  discovery_id: string
  trigger_reason: string
  status: string
  stage: string
  stage_attempt: number
  candidate_count: number
  rejection_count: number
  error_code: string | null
  created_at: string
  terminal_at: string | null
  updated_at: string
}

export type ActorOpsV2ReplacementPlan = {
  plan_id: string
  target_assignment: 'active' | 'standby'
  target_priority: number
  status: 'previewed' | 'authorized' | 'running' | 'ready' | 'applied' | 'failed' | 'cancelled'
  generation: number
  binding_count: number
  per_probe_cap_usd: number
  total_cap_usd: number
  error_code: string | null
  candidate: ActorOpsV2Candidate
}

export type ActorOpsV2RouteDetail = ActorOpsV2RouteTransport & {
  candidates: ActorOpsV2Candidate[]
  bindings: ActorOpsV2Binding[]
  attempts: ActorOpsV2Attempt[]
  discoveries: ActorOpsV2Discovery[]
  replacements: ActorOpsV2ReplacementPlan[]
}

export type ActorOpsV2RoutesResponse = {
  schema_version: 2
  routes: ActorOpsV2RouteTransport[]
}

export type ActorOpsV2OperationEvent = {
  event_id: string
  timestamp: string
  action: string
  outcome: string
  level: 'info' | 'warning' | 'error'
  source_id?: string
  error_code?: string
  changed_fields?: string[]
}

export type ActorOpsV2OperationEvents = {
  schema_version: 2
  availability: 'available' | 'empty' | 'unavailable'
  events: ActorOpsV2OperationEvent[]
  returned: number
  truncated: boolean
  window: { from: string; to: string }
}
