import type { ReactNode } from 'react'

import { Card, StatusIndicator } from '../../design-system'

export type ActorOpsV2RouteView = {
  actorops_version: 2
  route_id: string
  route_key: string
  platform: string
  health: 'healthy' | 'degraded' | 'unavailable'
  runtime_mode: 'disabled' | 'shadow' | 'active'
  active_candidate: CandidateView | null
  standby_candidates: CandidateView[]
  last_known_good: CandidateView | null
  last_success_at: string | null
  degraded_reason: string | null
  maintenance_policy: MaintenancePolicyView
}

type CandidateView = {
  candidate_id: string
  actor_id: string
  publisher: string
  build_number: string | null
  lifecycle: string
  assignment: string
  priority: number | null
}

type MaintenancePolicyView = {
  authorized: boolean
  workspace: { enabled: boolean; monthly_budget_usd: number | null; generation: number }
  route: {
    enabled: boolean
    max_probe_usd: number | null
    max_probes_per_utc_day: number | null
    auto_add_standby: boolean | null
    auto_replace_non_last: boolean | null
    generation: number
  }
  budget: { spent_usd: number; reserved_usd: number; probe_count: number }
}

const healthTone = {
  healthy: 'success',
  degraded: 'warning',
  unavailable: 'danger',
} as const

const healthLabel = {
  healthy: '健康',
  degraded: '降级可用',
  unavailable: '不可用',
} as const

export function ActorOpsV2ControlPlane({
  routes,
  operationsContent,
}: {
  routes: ActorOpsV2RouteView[]
  operationsContent?: ReactNode
}) {
  return <div className="grid gap-5" data-testid="actorops-v2-control-plane">
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div>
        <Card.Title>ActorOps v2 路由</Card.Title>
        <Card.Description className="mt-1">展示稳定获取所需的健康、主备、LKG 与受限维护状态；历史批次和发现阶段不在此界面出现。</Card.Description>
      </div>
      <div className="grid gap-3 min-[720px]:grid-cols-2 min-[1100px]:grid-cols-3">
        {routes.map((route) => <RouteCard key={route.route_id} route={route} />)}
      </div>
    </Card>
    {operationsContent}
  </div>
}

function RouteCard({ route }: { route: ActorOpsV2RouteView }) {
  const maintenance = route.maintenance_policy
  const active = route.active_candidate
  const standby = route.standby_candidates
  return <Card className="grid min-w-0 gap-3 p-4">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0"><Card.Title className="break-words">{route.route_key}</Card.Title><Card.Description className="mt-1">模式：{modeLabel(route.runtime_mode)}</Card.Description></div>
      <StatusIndicator label={healthLabel[route.health]} tone={healthTone[route.health]} />
    </div>
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 type-meta">
      <RouteValue label="主用" value={candidateLabel(active)} />
      <RouteValue label="备用" value={standby.length ? standby.map(candidateLabel).join('、') : '未配置'} />
      <RouteValue label="LKG" value={candidateLabel(route.last_known_good)} />
      <RouteValue label="最近成功" value={route.last_success_at || '暂无'} />
      <RouteValue label="维护" value={maintenance.authorized ? '已授权' : '默认关闭'} />
      <RouteValue label="Probe" value={`${maintenance.budget.probe_count}/${maintenance.route.max_probes_per_utc_day ?? 0} · $${maintenance.budget.spent_usd.toFixed(2)}`} />
    </dl>
    {route.degraded_reason && <Card.Description className="break-words">安全原因：{route.degraded_reason}</Card.Description>}
  </Card>
}

function RouteValue({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-muted">{label}</dt><dd className="mt-0.5 break-words type-control">{value}</dd></div>
}

function candidateLabel(candidate: CandidateView | null) {
  return candidate ? candidate.actor_id : '未配置'
}

function modeLabel(mode: ActorOpsV2RouteView['runtime_mode']) {
  return mode === 'active' ? 'Active' : mode === 'shadow' ? 'Shadow' : 'Disabled'
}
