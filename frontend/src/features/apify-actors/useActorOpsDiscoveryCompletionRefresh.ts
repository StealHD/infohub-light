import { useEffect } from 'react'
import type { QueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type { ApifyActorPoolGoal, ApifyActorSlotName } from '../../api/types'

type CompletionRefresh = {
  queryClient: QueryClient
  userId: string
  routeId: string
  goal: ApifyActorPoolGoal
  targetSlot: ApifyActorSlotName | undefined
  submittedRunId: string
  trackedRunId: string
  terminal: boolean
}

export function useActorOpsDiscoveryCompletionRefresh(options: CompletionRefresh) {
  const {
    queryClient, userId, routeId, goal, targetSlot,
    submittedRunId, trackedRunId, terminal,
  } = options
  useEffect(() => {
    if (!routeId || !submittedRunId || trackedRunId !== submittedRunId || !terminal) return
    void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(userId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(userId, routeId) })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.apifyActorPoolCandidates(userId, routeId, goal, targetSlot),
    })
  }, [goal, queryClient, routeId, submittedRunId, targetSlot, terminal, trackedRunId, userId])
}
