import type { ApifyActorPoolCandidate, ApifyActorPoolGoal } from '../../api/types'

export function actorPickerCandidates(
  candidates: ApifyActorPoolCandidate[],
  goal: ApifyActorPoolGoal,
): {
  visibleCandidates: ApifyActorPoolCandidate[]
} {
  void goal
  return {
    // A missing value is not proof.  The server only projects fully proven
    // revisions, and this client guard keeps a stale or mixed response from
    // ever rendering an untested Actor as a selectable candidate.
    visibleCandidates: candidates.filter(
      (candidate) => candidate.selectable && candidate.already_validated === true,
    ),
  }
}
