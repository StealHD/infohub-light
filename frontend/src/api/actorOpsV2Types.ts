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
  mapping_issue_code?: 'missing_post_author_handle' | 'output_not_content_items' | 'missing_target_input' | 'missing_required_input_value' | 'missing_post_id' | 'missing_post_url' | 'missing_post_published_at' | 'missing_post_text' | 'missing_source_identity' | 'ambiguous_output' | 'wrong_actor_type' | 'nested_content_items' | 'named_dataset_required' | 'output_schema_incomplete' | 'target_identity_derivable' | 'relative_published_at' | 'nested_extraction_failed' | 'mixed_rows_unclassified' | 'dataset_run_unbound' | 'dataset_expansion_overflow' | 'observed_mapping_failed' | 'output_sample_required' | 'input_plan_invalid' | 'route_type_uncertain' | 'sample_dataset_empty' | null
  compatibility_stage?: 'candidate' | 'static_ready' | 'sample_required' | 'adapting' | 'system_usable' | 'blocked'
  mapping_evidence?: 'schema' | 'dataset'
  dataset_shape?: 'flat' | 'nested' | 'mixed' | 'run_bound' | 'unknown'
  system_usable?: boolean
  probe_eligible?: boolean
  binding_proof_count?: number
  binding_required_count?: number
  compatibility_issue_code?: 'actor_deleted' | 'build_unavailable' | 'contract_invalid' | 'repeated_start_rejection' | 'stale_regression' | 'candidate_failure' | 'candidate_unavailable' | 'output_sample_required' | 'binding_proof_incomplete' | 'route_binding_missing' | null
  operational_status: 'normal' | 'recent_failure' | 'confirmed_failure'
  issue_code: 'actor_deleted' | 'build_unavailable' | 'contract_invalid' | 'repeated_start_rejection' | 'stale_regression' | 'candidate_failure' | null
  last_success_at: string | null
  last_failure_at: string | null
  retry_at: string | null
  avatar_mapping_status: 'ready' | 'missing' | 'stale'
  store_metadata: ActorOpsV2StoreMetadata | null
  evidence_progress: { verified_bindings: number; required_bindings: number }
}

export type ActorOpsV2MaintenancePolicy = {
  authorized: boolean
  workspace: { enabled: boolean; monthly_budget_usd: number; generation: number; authorization_origin: 'system_default' | 'operator' | 'none' }
  route: {
    enabled: boolean
    max_probe_usd: number
    max_probes_per_utc_day: number
    auto_add_standby: boolean
    auto_replace_non_last: boolean
    generation: number
    authorization_origin: 'system_default' | 'operator' | 'none'
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
  health_reason: 'all_sources_redundant' | 'insufficient_stable_paths' | 'source_fallback_only' | 'source_unavailable' | null
  stable_candidate_count: number
  cooling_candidate_count: number
  at_risk_source_count: number
  unavailable_source_count: number
  fallback_source_count: number
  next_repair_at: string | null
  active_candidate: ActorOpsV2Candidate | null
  standby_candidates: ActorOpsV2Candidate[]
  last_known_good: ActorOpsV2Candidate | null
  binding_summary: ActorOpsV2BindingSummary
  maintenance_policy: ActorOpsV2MaintenancePolicy
  workflow?: ActorOpsV2Workflow
  degraded_reason: string | null
  updated_at: string | null
}

/** Raw transport accepts a retired mode so the view can fail closed during migration. */
export type ActorOpsV2RouteTransport = Omit<ActorOpsV2RouteSummary, 'runtime_mode'> & {
  runtime_mode: string
}

export type ActorOpsV2Binding = {
  binding_id: string
  source_id: string
  source_name: string
  source_enabled: boolean
  enabled_subscription_count: number
  status: 'pending' | 'ready' | 'disabled'
  binding_version: number
  preferred_candidate_id: string | null
  last_known_good_candidate_id: string | null
  last_success_at: string | null
  verification: {
    state: 'ready' | 'eligible' | 'blocked' | 'disabled'
    proof_kind: 'deterministic' | 'settled_probe' | null
    reason: string | null
  }
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
  metrics?: {
    marketplace_hits: number
    revision_checks: number
    wrong_actor_type: number
    preflight_blocked: number
    route_relevant: number
    static_ready: number
    sample_required: number
    system_usable: number
  }
}

export type ActorOpsV2ReplacementProgress = {
  verified_bindings: number
  required_bindings: number
  completed_attempts: number
  attempt_count: number
  pending_attempts: number
}

export type ActorOpsV2ReplacementCostSummary = {
  finalized_usd: number
  pending: boolean
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
  phase?: 'schema_analysis' | 'sample_required' | 'dataset_read' | 'dataset_adapting' | 'dataset_revalidating' | 'cost_reconciliation' | 'proof_complete'
  progress?: ActorOpsV2ReplacementProgress
  cost_summary?: ActorOpsV2ReplacementCostSummary
  candidate: ActorOpsV2Candidate
}

export type ActorOpsV2Workflow = {
  discovery: ActorOpsV2Discovery | null
  replacement: ActorOpsV2ReplacementPlan | null
}

export type ActorOpsV2DiscoveryStart = {
  route_id: string
  discovery_id: string
  created: boolean
  queued: true
}

export type ActorOpsV2RouteDetail = ActorOpsV2RouteTransport & {
  candidates: ActorOpsV2Candidate[]
  bindings: ActorOpsV2Binding[]
  attempts: ActorOpsV2Attempt[]
  discoveries: ActorOpsV2Discovery[]
  replacements: ActorOpsV2ReplacementPlan[]
  repairs?: Array<{
    repair_id: string
    source_id: string
    origin_job_id: string | null
    trigger_code: string
    status: string
    candidate_id: string | null
    error_code: string | null
    updated_at: string
  }>
  freshness_summary?: Record<'neutral' | 'suspected_stale' | 'source_stale' | 'confirmed_no_change', number>
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
  kind?: 'execution' | 'operation'
  root_job_id?: string | null
  route_id?: string | null
  candidate_id?: string | null
  repair_id?: string | null
  phase?: string
  reason_code?: string | null
  counts?: Record<string, number>
  final_cost_usd?: number | null
  service?: string
  category?: string
  route?: string
  method?: string
  status_code?: number
}

export type ActorOpsV2OperationEvents = {
  schema_version: 2 | 3
  availability: 'available' | 'empty' | 'unavailable'
  events: ActorOpsV2OperationEvent[]
  returned: number
  truncated: boolean
  next_cursor?: string | null
  completeness?: 'complete' | 'partial' | 'not_recorded'
  window: { from: string; to: string }
}
