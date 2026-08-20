import { useEffect, type Dispatch, type SetStateAction } from 'react'

import { actionToast } from '../../design-system'
import type { HumanActorError } from './actorOpsPresentation'

type AutoPoolRun = {
  status: string
  error_code?: string | null
}

type AutoPoolCompletionOptions = {
  run: AutoPoolRun | undefined
  clearSlotOperation: () => void
  refreshSelected: () => void
  setRunId: Dispatch<SetStateAction<string>>
  setError: Dispatch<SetStateAction<HumanActorError | null>>
  setCandidatePickerOpen: Dispatch<SetStateAction<boolean>>
  setSelectedCandidateIds: Dispatch<SetStateAction<string[] | null>>
}

export function useActorOpsAutoPoolCompletion({
  run,
  clearSlotOperation,
  refreshSelected,
  setRunId,
  setError,
  setCandidatePickerOpen,
  setSelectedCandidateIds,
}: AutoPoolCompletionOptions) {
  useEffect(() => {
    if (!run || !['succeeded', 'budget_exhausted', 'failed'].includes(run.status)) return
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      if (run.status === 'succeeded') {
        setRunId('')
        setError(null)
        clearSlotOperation()
        setCandidatePickerOpen(false)
        setSelectedCandidateIds([])
        refreshSelected()
        actionToast.success('已自动完成 Actor 替换', {
          description: '免费搜索、付费验证与生效已自动走完，当前线路已更新。',
        })
        return
      }
      if (run.status === 'budget_exhausted' || run.status === 'failed') {
        setError({
          reason: run.status === 'budget_exhausted'
            ? '本轮自动替换已用尽 $0.50 预算，仍未找到通过付费验证的候选。'
            : '自动替换流程失败，请刷新后重试。',
          impact: '现有线路保持不变，没有被自动切换。',
          next: '刷新状态后可重新发起自动替换，或改为手动逐项验证。',
          diagnostic: run.error_code ?? undefined,
        })
        setRunId('')
      }
    })
    return () => { cancelled = true }
  }, [
    clearSlotOperation,
    refreshSelected,
    run,
    setCandidatePickerOpen,
    setError,
    setRunId,
    setSelectedCandidateIds,
  ])
}
