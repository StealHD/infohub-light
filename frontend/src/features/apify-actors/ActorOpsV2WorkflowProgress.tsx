import type { ActorOpsV2Discovery, ActorOpsV2ReplacementPlan, ActorOpsV2Workflow } from '../../api/actorOpsV2Types'
import { StatusIndicator, StatusNotice } from '../../design-system'
import { actorOpsV2CandidateLabel } from './actorOpsV2RouteModel'
import { actionableReplacement, discoveryStageLabel, discoveryStagePosition, replacementPhaseLabel } from './actorOpsV2WorkflowModel'

export function ActorOpsV2WorkflowSteps({ plan }: { plan: ActorOpsV2ReplacementPlan | null }) {
  const current = !plan ? 1 : plan.status === 'previewed' ? 2 : plan.status === 'ready' || plan.status === 'applied' ? 4 : 3
  const labels = ['搜索与选择', '免费预检', '实测与适配', '确认应用']
  return <ol className="mb-4 grid grid-cols-2 gap-2 min-[420px]:grid-cols-4" aria-label="Actor 管理步骤">
    {labels.map((label, index) => <li key={label} className={`rounded-lg border px-2 py-1.5 type-meta ${index + 1 === current ? 'border-focus text-foreground' : index + 1 < current ? 'border-success/30 text-success' : 'border-separator text-muted'}`} aria-current={index + 1 === current ? 'step' : undefined}>{index + 1}. {label}</li>)}
  </ol>
}

export function ActorOpsV2RouteWorkflowSummary({ workflow = { discovery: null, replacement: null } }: { workflow?: ActorOpsV2Workflow }) {
  const replacement = actionableReplacement(workflow.replacement)
  if (replacement) {
    const active = ['previewed', 'authorized', 'running'].includes(replacement.status)
    const tone = replacement.status === 'failed' ? 'danger' : replacement.status === 'ready' ? 'warning' : 'accent'
    return <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-separator bg-surface px-3 py-2">
      <StatusIndicator label={replacement.status === 'ready' ? '待确认' : replacement.status === 'failed' ? '未完成' : '处理中'} tone={tone} />
      <span className="type-meta text-muted">{replacementPhaseLabel(replacement)} · {replacement.progress?.verified_bindings || 0}/{replacement.progress?.required_bindings ?? replacement.binding_count} 个来源{active && replacement.cost_summary?.pending ? ' · 费用待对账' : ''}</span>
    </div>
  }
  const discovery = workflow.discovery
  if (!discovery) return null
  const active = ['queued', 'running', 'retry_wait'].includes(discovery.status)
  const tone = discovery.status === 'failed' ? 'danger' : active ? 'accent' : 'success'
  const label = discovery.status === 'failed' ? '搜索失败' : active ? '搜索中' : '最近搜索'
  return <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-separator bg-surface px-3 py-2">
    <StatusIndicator label={label} tone={tone} />
    <span className="type-meta text-muted">{active ? discoveryStageLabel(discovery.stage) : discoveryResultText(discovery)}</span>
  </div>
}

export function ActorOpsV2DiscoveryProgress({ discovery }: { discovery: ActorOpsV2Discovery | null }) {
  if (!discovery) return null
  const active = ['queued', 'running', 'retry_wait'].includes(discovery.status)
  if (active) return <StatusNotice title="正在搜索候选" status="info">
    <p>{discoveryStageLabel(discovery.stage)} · 步骤 {discoveryStagePosition(discovery)}/6</p>
    <p className="mt-1 type-meta text-muted">完成后会自动刷新候选列表；不会启动 Actor。</p>
  </StatusNotice>
  if (discovery.status === 'failed') return <StatusNotice title="候选搜索未完成" status="danger">
    当前停止在“{discoveryStageLabel(discovery.stage)}”；未启动 Actor。可以重新搜索。
  </StatusNotice>
  return <StatusNotice title="候选搜索完成" status="success">
    <p>{discoveryResultText(discovery)}</p>
    <p className="mt-1 type-meta text-muted">系统可用 {discovery.metrics?.system_usable || 0} · 可实测 {discovery.metrics?.static_ready || 0} · 需要样本 {discovery.metrics?.sample_required || 0}</p>
  </StatusNotice>
}

export function ActorOpsV2ReplacementProgress({ plan }: { plan: ActorOpsV2ReplacementPlan }) {
  const cost = plan.cost_summary || { finalized_usd: 0, pending: false }
  const progress = plan.progress || { verified_bindings: plan.status === 'ready' ? plan.binding_count : 0, required_bindings: plan.binding_count, completed_attempts: 0, attempt_count: 0, pending_attempts: 0 }
  return <div className="grid gap-2 rounded-xl border border-separator bg-surface-secondary p-3" aria-label="替换进度">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="type-control">{replacementPhaseLabel(plan)}</span>
      <span className="type-meta text-muted">来源 {progress.verified_bindings}/{progress.required_bindings}</span>
    </div>
    <p className="type-meta text-muted">候选：{actorOpsV2CandidateLabel(plan.candidate)} · 已结算 ${cost.finalized_usd.toFixed(4)} / 上限 ${plan.total_cap_usd.toFixed(2)}{cost.pending ? ' · 仍有费用待对账' : ''}</p>
    {progress.attempt_count > 0 && <p className="type-meta text-muted">实测记录 {progress.completed_attempts}/{progress.attempt_count}{progress.pending_attempts ? ` · 待完成 ${progress.pending_attempts}` : ''}</p>}
  </div>
}

function discoveryResultText(discovery: ActorOpsV2Discovery) {
  const metrics = discovery.metrics
  return `商城命中 ${metrics?.marketplace_hits || 0} · 相关候选 ${metrics?.route_relevant || discovery.candidate_count} · 排除错类型 ${metrics?.wrong_actor_type || 0} · 预检阻断 ${metrics?.preflight_blocked || 0}`
}
