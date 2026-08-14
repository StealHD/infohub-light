import type { ApifyActorSlotName } from '../../api/types'
import type { WorkflowPresentation } from './actorOpsPresentation'

const slotLabels: Record<ApifyActorSlotName, string> = {
  primary: '主用',
  backup_1: '备用 1',
  backup_2: '备用 2',
}

export function slotWorkflowPresentation(
  kind: string,
  operationSlot: ApifyActorSlotName | null | undefined,
): WorkflowPresentation | null {
  const matched = /^(add_slot|replace_slot)_(discovery_required|candidate_selection_required|canary_approval_required|canary_running|activation_approval_required)$/.exec(kind)
  if (!matched || !operationSlot) return null
  const [goal, phase] = [matched[1], matched[2]]
  const label = slotLabels[operationSlot]
  const add = goal === 'add_slot'
  const action = add ? `添加${label} Actor` : `替换${label} Actor`
  const candidateTitle = add
    ? `${label} Actor 的新增候选`
    : `${label} Actor 的替换候选`
  if (phase === 'discovery_required') {
    return {
      title: `${candidateTitle}不足`,
      description: '最近一轮候选没有产生可安全验证的 Actor。可免费重新检查；当前主备保持不变。',
      status: '待候选', tone: 'warning', action: 'start_discovery', cta: '免费更新候选',
    }
  }
  if (phase === 'candidate_selection_required') {
    return {
      title: `选择${candidateTitle}`,
      description: '仅此槽会在完成付费验证和来源检查后原子变更；当前主备不会提前切换。',
      status: '待选择', tone: 'warning', action: 'select_candidates', cta: `选择${action}`,
    }
  }
  if (phase === 'canary_approval_required') {
    return {
      title: `${action}候选已就绪`,
      description: '第一步：确认一次限额付费验证。验证期间现有主备保持不变。',
      status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认付费验证',
    }
  }
  if (phase === 'canary_running') {
    return {
      title: `正在验证${action}候选`,
      description: 'Route 与已启用来源正在串行验证；系统不会提前变更当前主备或自动重试。',
      status: '验证中', tone: 'warning', action: 'none',
    }
  }
  return {
    title: `${action}验证通过`,
    description: '第二步：确认后才原子应用这一槽，运行中的任务继续使用原 generation。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认生效',
  }
}
