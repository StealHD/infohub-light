import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type { ApifyActorPoolGoal, ApifyActorSlotName } from '../../api/types'
import { useAppContext } from '../../app/AppContext'

type PoolCandidateParams = {
  routeId: string
  goal: ApifyActorPoolGoal
  targetSlot: ApifyActorSlotName | undefined
  queryEnabled: boolean
  pickerOpen: boolean
  selectedCandidateIds: string[] | null
}

export function useActorOpsPoolCandidates({
  routeId,
  goal,
  targetSlot,
  queryEnabled,
  pickerOpen,
  selectedCandidateIds,
}: PoolCandidateParams) {
  const { api, user } = useAppContext()
  const candidatesQuery = useQuery({
    queryKey: queryKeys.apifyActorPoolCandidates(user.id, routeId, goal, targetSlot),
    queryFn: ({ signal }) => targetSlot
      ? api.apifyActorPoolCandidates(routeId, goal, signal, targetSlot)
      : api.apifyActorPoolCandidates(routeId, goal, signal),
    enabled: queryEnabled && pickerOpen && Boolean(routeId),
    retry: false,
  })
  const preferredCandidateIds = goal === 'upgrade_legacy' && pickerOpen
    ? (candidatesQuery.data?.candidates ?? [])
      .filter((candidate) => candidate.selectable && candidate.existing_actor_upgrade)
      .slice(0, candidatesQuery.data?.required_selection_count ?? 3)
      .map((candidate) => candidate.candidate_id)
    : []
  return {
    candidatesQuery,
    preferredCandidateIds,
    hasPreferredActorUpgrades: preferredCandidateIds.length > 0,
    activeSelectedCandidateIds: selectedCandidateIds ?? preferredCandidateIds,
    selectableCandidateCount: candidatesQuery.data
      ? candidatesQuery.data.candidates.filter((candidate) => candidate.selectable).length
      : null,
  }
}
