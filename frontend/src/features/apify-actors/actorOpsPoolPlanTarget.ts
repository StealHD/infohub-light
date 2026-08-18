import type { ApifyActorWorkflow } from '../../api/actorOpsWorkflowTypes'
import type { ApifyActorPoolCandidates, ApifyActorPoolGoal, ApifyActorRouteDetail } from '../../api/types'

export function actorOpsPoolPlanTarget(
  candidates: ApifyActorPoolCandidates | undefined,
  workflow: ApifyActorWorkflow | undefined,
  detail: Pick<ApifyActorRouteDetail, 'discovery_run_id'> | undefined,
): { runId: string | null; goal: ApifyActorPoolGoal } {
  if (candidates?.run_id) return { runId: candidates.run_id, goal: candidates.goal }
  return {
    runId: workflow?.run_id || detail?.discovery_run_id || null,
    goal: workflow?.goal || 'initial_pool',
  }
}
