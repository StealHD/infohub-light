import type { ApifyActorPoolGoal, ApifyActorRevisionLifecycle, ApifyActorSlotName } from './types'

export type ApifyActorWorkflowKind =
  | 'setup_discovery_required'
  | 'setup_discovery_running'
  | 'setup_candidate_selection_required'
  | 'setup_canary_approval_required'
  | 'setup_canary_running'
  | 'setup_activation_approval_required'
  | 'backup_2_discovery_required'
  | 'backup_2_discovery_running'
  | 'backup_2_candidate_selection_required'
  | 'backup_2_canary_approval_required'
  | 'backup_2_canary_running'
  | 'backup_2_activation_approval_required'
  | 'legacy_discovery_required'
  | 'legacy_discovery_running'
  | 'legacy_candidate_selection_required'
  | 'legacy_canary_approval_required'
  | 'legacy_canary_running'
  | 'legacy_activation_approval_required'
  | 'compatibility_candidate_selection_available'
  | 'compatibility_discovery_required'
  | 'compatibility_discovery_running'
  | 'compatibility_candidate_selection_required'
  | 'compatibility_canary_approval_required'
  | 'compatibility_canary_running'
  | 'compatibility_activation_approval_required'
  | 'compatibility_operational'
  | 'compatibility_standard_discovery_running'
  | 'compatibility_standard_candidate_selection_required'
  | 'probation_observing'
  | 'source_validation_required'
  | 'runtime_degraded_monitoring'
  | 'blocked_unknown_start'
  | 'budget_blocked'
  | 'complete'

export type ApifyActorWorkflowFailure = {
  phase: 'route_validation' | 'source_validation'
  code: string
  actual_cost_usd: number | null
  cost_final: boolean
}

export type ApifyActorWorkflowProgress = Record<string, unknown> & {
  last_failure?: ApifyActorWorkflowFailure
}

export type ApifyActorWorkflow = {
  kind: ApifyActorWorkflowKind | string
  goal: ApifyActorPoolGoal | null
  stage_id?: string | null
  run_id?: string | null
  plan_hash?: string | null
  operation_slot?: ApifyActorSlotName | null
  progress: ApifyActorWorkflowProgress
  blockers: string[]
}

export type ApifyActorCertificationProgress = {
  auto_promotes: boolean
  lifecycle: ApifyActorRevisionLifecycle
  success_identities: { current: number; required: number }
  reference_targets: { current: number; required: number }
  valid_samples: { current: number; successful: number; required: number }
  success_rate: { current: number; required: number }
  observation_started_at: string | null
  eligible_at: string | null
  remaining_seconds: number | null
  blockers: string[]
}
