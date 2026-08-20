import { useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { ApifyActorRouteDetail, ApifyActorSlotName } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { actionToast } from '../../design-system'
import { safeActorActionError } from './apifyActorModel'
import type { HumanActorError } from './actorOpsPresentation'
import type { ActorOpsPoolTarget } from './ActorOpsPoolManagementControls'

type PoolSlotOperation = {
  goal: 'add_slot' | 'replace_slot'
  targetSlot: ApifyActorSlotName
}

type PoolManagementParams = {
  detail: ApifyActorRouteDetail | undefined
  setCandidatePickerOpen: Dispatch<SetStateAction<boolean>>
  setSelectedCandidateIds: Dispatch<SetStateAction<string[] | null>>
  setCandidateError: Dispatch<SetStateAction<HumanActorError | null>>
  refreshSelected: () => void
}

export function useActorOpsPoolManagement({
  detail,
  setCandidatePickerOpen,
  setSelectedCandidateIds,
  setCandidateError,
  refreshSelected,
}: PoolManagementParams) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [slotOperation, setSlotOperation] = useState<PoolSlotOperation | null>(null)
  const [removeTarget, setRemoveTarget] = useState<ActorOpsPoolTarget | null>(null)
  const slotOperationTriggerRef = useRef<HTMLButtonElement | null>(null)
  const slotOperationSlotRef = useRef<ApifyActorSlotName | null>(null)
  const removeTriggerRef = useRef<HTMLButtonElement | null>(null)
  const restoreFocus = () => window.requestAnimationFrame(() => removeTriggerRef.current?.focus())
  const focusSlot = (slot: ApifyActorSlotName) => document.querySelector<HTMLButtonElement>(
    `[data-actorops-slot="${slot}"] button:not([disabled])`,
  )?.focus()
  const restoreSlotFocus = (slot: ApifyActorSlotName) => window.requestAnimationFrame(() => focusSlot(slot))
  const restoreSlotOperationFocus = () => window.requestAnimationFrame(() => {
    if (slotOperationTriggerRef.current?.isConnected) {
      slotOperationTriggerRef.current.focus()
      return
    }
    const slot = slotOperationSlotRef.current
    if (!slot) return
    focusSlot(slot)
  })
  const removePoolSlot = useMutation({
    mutationFn: (target: ActorOpsPoolTarget) => {
      if (!detail) throw new Error('route unavailable')
      return api.removeApifyActorRouteActivePoolSlot(detail.route_id, {
        target_slot: target.slot,
        expected_generation: detail.generation,
        confirmation: '确认移出 Actor 主备池',
      })
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      setRemoveTarget(null)
      restoreFocus()
      actionToast.success('已移出 Actor，剩余主备已自动前压')
    },
    onError: (caught) => {
      if (caught instanceof ApiError && [
        'apify_actor_route_generation_conflict',
        'apify_actor_pool_stage_active',
        'apify_actor_pool_remove_inflight',
      ].includes(caught.code)) {
        setRemoveTarget(null)
        restoreFocus()
        refreshSelected()
      }
      actionToast.danger('未能移出 Actor', {
        description: safeActorActionError(caught, '当前 Actor 池保持不变，请刷新后重试。'),
      })
    },
  })
  return {
    slotOperation,
    clearSlotOperation() {
      setSlotOperation(null)
    },
    removeTarget,
    removePoolSlot,
    startSlotOperation(
      goal: PoolSlotOperation['goal'],
      targetSlot: ApifyActorSlotName,
      trigger: HTMLButtonElement | null,
    ) {
      slotOperationTriggerRef.current = trigger
      slotOperationSlotRef.current = targetSlot
      setSlotOperation({ goal, targetSlot })
      setSelectedCandidateIds([])
      setCandidateError(null)
      setCandidatePickerOpen(true)
    },
    restoreSlotOperationFocus,
    restoreSlotFocus,
    openRemoveDialog(target: ActorOpsPoolTarget, trigger: HTMLButtonElement | null) {
      removeTriggerRef.current = trigger
      setRemoveTarget(target)
    },
    closeRemoveDialog() {
      setRemoveTarget(null)
      restoreFocus()
    },
  }
}
