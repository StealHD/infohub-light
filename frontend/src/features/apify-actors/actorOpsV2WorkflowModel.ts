import type { ActorOpsV2Discovery, ActorOpsV2ReplacementPlan, ActorOpsV2Workflow } from '../../api/actorOpsV2Types'

const ACTIVE_DISCOVERY = new Set(['queued', 'running', 'retry_wait'])
const OPEN_REPLACEMENT = new Set(['previewed', 'authorized', 'running', 'ready'])

export const discoveryStages = ['store_search', 'metadata', 'validation', 'mapping', 'ranking', 'persist'] as const

export const emptyActorOpsV2Workflow: ActorOpsV2Workflow = { discovery: null, replacement: null }

export function actorOpsV2WorkflowActive(workflow: ActorOpsV2Workflow | undefined) {
  workflow ||= emptyActorOpsV2Workflow
  return Boolean(
    (workflow.discovery && ACTIVE_DISCOVERY.has(workflow.discovery.status))
    || (workflow.replacement && OPEN_REPLACEMENT.has(workflow.replacement.status)),
  )
}

export function actorOpsV2WorkflowActionLabel(workflow: ActorOpsV2Workflow | undefined) {
  workflow ||= emptyActorOpsV2Workflow
  const replacement = actionableReplacement(workflow.replacement)
  if (replacement?.status === 'ready') return '确认替换'
  if (replacement) return '查看替换进度'
  if (workflow.discovery && ACTIVE_DISCOVERY.has(workflow.discovery.status)) return '查看搜索进度'
  return '管理 Actor'
}

export function actionableReplacement(plan: ActorOpsV2ReplacementPlan | null) {
  return plan && !['applied', 'cancelled'].includes(plan.status) ? plan : null
}

export function discoveryStagePosition(discovery: ActorOpsV2Discovery) {
  const index = discoveryStages.indexOf(discovery.stage as typeof discoveryStages[number])
  return Math.max(0, index) + 1
}

export function discoveryStageLabel(stage: string) {
  const labels: Record<string, string> = {
    store_search: '搜索商城',
    metadata: '读取 Actor 与 Build',
    validation: '免费预检',
    mapping: '分析字段合同',
    ranking: '质量排序',
    persist: '保存候选',
  }
  return labels[stage] || '准备搜索'
}

export function replacementPhaseLabel(plan: ActorOpsV2ReplacementPlan) {
  if (plan.status === 'previewed') return '等待授权实测'
  if (plan.status === 'ready') return '实测完成，等待应用'
  if (plan.status === 'failed') return '替换未完成'
  const labels: Record<string, string> = {
    schema_analysis: '检查固定 Build 与字段合同',
    sample_required: '逐来源实测',
    dataset_read: '读取本次 Dataset',
    dataset_adapting: '自动适配 Dataset 字段',
    dataset_revalidating: '零新增 Run 重验 Dataset',
    cost_reconciliation: '核对费用事实',
    proof_complete: '来源证明完成',
  }
  return labels[plan.phase || ''] || '准备实测'
}
