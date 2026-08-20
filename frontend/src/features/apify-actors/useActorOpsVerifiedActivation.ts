import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type {
  ApifyActorPoolCandidates,
  ApifyActorPoolGoal,
  ApifyActorRouteDetail,
  ApifyActorSlotName,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { actionToast } from '../../design-system'
import { humanActorError, type HumanActorError } from './actorOpsPresentation'

export type VerifiedActivationTarget = {
  routeId: string
  goal: ApifyActorPoolGoal
  actorLabels: string[]
  currentSlotCount: number
  targetSlotCount: 1 | 2 | 3
  payload: {
    run_id: string
    goal: ApifyActorPoolGoal
    candidate_ids: string[]
    expected_generation: number
    target_slot_count: 1 | 2 | 3
    target_slot?: ApifyActorSlotName
    apply_id: string
    confirmation: '确认启用 Actor 主备'
  }
}

type Options = {
  candidates: ApifyActorPoolCandidates | undefined
  selectedCandidateIds: string[]
  detail: ApifyActorRouteDetail | undefined
  candidateGoal: ApifyActorPoolGoal
  targetSlot: ApifyActorSlotName | undefined
  onActivated: (updated: ApifyActorRouteDetail) => void
  onClosed: () => void
  onStale: () => void
}

export function useActorOpsVerifiedActivation(options: Options) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [target, setTarget] = useState<VerifiedActivationTarget | null>(null)
  const [error, setError] = useState<HumanActorError | null>(null)
  const mutation = useMutation({
    mutationFn: (value: VerifiedActivationTarget) => (
      api.activateVerifiedApifyActorPool(value.routeId, value.payload)
    ),
    onSuccess: (updated) => {
      setTarget(null)
      setError(null)
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.apifyActorPoolCandidates(
          user.id, updated.route_id, options.candidateGoal, options.targetSlot,
        ),
      })
      options.onActivated(updated)
      actionToast.success('已启用已验证 Actor', {
        description: '没有重新触发 Canary，也没有新增费用。',
      })
    },
    onError: (caught) => {
      const failure = humanActorError(caught, '已验证证据发生变化，请刷新 Actor 库后重试。')
      setError(failure)
      actionToast.danger('未能启用已验证 Actor', {
        description: `${failure.reason}；没有重新启动 Actor，也没有新增费用。`,
      })
      if (caught instanceof ApiError && [
        'apify_actor_route_generation_conflict',
        'apify_actor_verified_candidate_stale',
      ].includes(caught.code)) {
        setTarget(null)
        options.onStale()
        options.onClosed()
      }
    },
  })

  function prepare() {
    const candidates = options.candidates
    if (!candidates?.run_id || options.selectedCandidateIds.length !== candidates.required_selection_count) return
    const selected = options.selectedCandidateIds.map((candidateId) => (
      candidates.candidates.find((candidate) => candidate.candidate_id === candidateId)
    ))
    if (selected.some((candidate) => !candidate?.already_validated)) return
    const currentSlotCount = options.detail?.slots.filter((slot) => Boolean(slot.revision_id)).length ?? 0
    const targetSlotCount = (
      candidates.goal === 'compatibility_single' ? 1
        : candidates.goal === 'add_slot' ? currentSlotCount + 1
          : candidates.goal === 'replace_slot' ? currentSlotCount
            : candidates.goal === 'initial_pool' ? candidates.required_selection_count : 3
    ) as 1 | 2 | 3
    setError(null)
    setTarget({
      routeId: candidates.route_id, goal: candidates.goal,
      actorLabels: selected.map((candidate) => candidate?.actor_public_name || '已验证 Actor'),
      currentSlotCount, targetSlotCount,
      payload: {
        run_id: candidates.run_id, goal: candidates.goal,
        candidate_ids: [...options.selectedCandidateIds],
        expected_generation: candidates.generation,
        target_slot_count: targetSlotCount,
        ...(candidates.target_slot ? { target_slot: candidates.target_slot } : {}),
        apply_id: crypto.randomUUID(), confirmation: '确认启用 Actor 主备',
      },
    })
  }

  return {
    target,
    error,
    isPending: mutation.isPending,
    prepare,
    confirm: () => { if (target) mutation.mutate(target) },
    cancel: () => { if (!mutation.isPending) { setTarget(null); setError(null); options.onClosed() } },
  }
}
