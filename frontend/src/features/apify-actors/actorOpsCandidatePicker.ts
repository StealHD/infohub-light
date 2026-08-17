import type { ApifyActorPoolCandidate, ApifyActorPoolGoal } from '../../api/types'

export function actorPickerCandidates(
  candidates: ApifyActorPoolCandidate[],
  goal: ApifyActorPoolGoal,
): {
  visibleCandidates: ApifyActorPoolCandidate[]
  pendingCanaryCandidateCount: number
} {
  if (goal === 'upgrade_legacy') {
    return { visibleCandidates: candidates, pendingCanaryCandidateCount: 0 }
  }
  return {
    visibleCandidates: candidates.filter((candidate) => candidate.selectable && candidate.already_validated !== false),
    pendingCanaryCandidateCount: candidates.filter((candidate) => candidate.selectable && candidate.already_validated === false).length,
  }
}
