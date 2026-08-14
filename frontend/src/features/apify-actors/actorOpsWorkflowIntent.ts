import type { ApifyActorPoolGoal, ApifyActorSlotName } from '../../api/types'
import type { ApifyActorWorkflow } from '../../api/actorOpsWorkflowTypes'
import { routeWorkflowPresentation } from './actorOpsPresentation'

export type ActorOpsSlotOperation = {
  goal: 'add_slot' | 'replace_slot'
  targetSlot: ApifyActorSlotName
}

export function actorOpsWorkflowIntent(
  workflow: ApifyActorWorkflow | undefined,
  slotOperation: ActorOpsSlotOperation | null,
  minimumActors: number,
): {
  candidateGoal: ApifyActorPoolGoal
  candidateTargetSlot: ApifyActorSlotName | undefined
  next: ReturnType<typeof routeWorkflowPresentation>
} {
  const candidateGoal = slotOperation?.goal || workflow?.goal || 'initial_pool'
  const candidateTargetSlot = slotOperation?.targetSlot
    ?? (['add_slot', 'replace_slot'].includes(candidateGoal)
      ? workflow?.operation_slot ?? undefined
      : undefined)
  return {
    candidateGoal,
    candidateTargetSlot,
    next: routeWorkflowPresentation(
      workflow?.kind || '', minimumActors, workflow?.operation_slot,
    ),
  }
}
