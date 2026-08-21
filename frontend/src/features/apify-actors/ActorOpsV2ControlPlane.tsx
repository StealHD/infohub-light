import type { ReactNode } from 'react'

import { Card, StatusIndicator } from '../../design-system'
import { ActorOpsV2ActorChip } from './ActorOpsV2ActorChip'
import { type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

export type ActorOpsV2RouteView = {
  actorops_version: 2
  route_id: string
  route_generation: number
  route_key: string
  platform: string
  health: 'healthy' | 'degraded' | 'unavailable'
  runtime_mode: 'disabled' | 'shadow' | 'active'
  per_run_cap_usd: number
  active_candidate: CandidateView | null
  standby_candidates: CandidateView[]
  last_known_good: CandidateView | null
  last_success_at: string | null
  degraded_reason: string | null
  binding_summary: BindingSummaryView
}

type CandidateView = ActorOpsV2CandidateView
type BindingSummaryView = { ready_count: number; pending_count: number }

const healthTone = { healthy: 'success', degraded: 'warning', unavailable: 'danger' } as const
const healthLabel = { healthy: '健康', degraded: '降级可用', unavailable: '不可用' } as const

export function ActorOpsV2ControlPlane({ routes, operationsContent, renderRouteActions }: {
  routes: ActorOpsV2RouteView[]
  operationsContent?: ReactNode
  renderRouteActions?: (route: ActorOpsV2RouteView) => ReactNode
}) {
  return <div className="grid gap-5" data-testid="actorops-v2-control-plane">
    <Card variant="secondary" className="overflow-hidden border border-separator">
      <div className="border-b border-separator px-4 py-4"><Card.Title>ActorOps v2 路由</Card.Title><Card.Description className="mt-1">商城标价只作参考；费用上限和替换都需要单独确认。</Card.Description></div>
      <div className="divide-y divide-separator">
        {routes.map((route) => <RouteRow key={route.route_id} route={route}>{renderRouteActions?.(route)}</RouteRow>)}
      </div>
    </Card>
    {operationsContent}
  </div>
}

function RouteRow({ route, children }: { route: ActorOpsV2RouteView; children?: ReactNode }) {
  return <section className="grid gap-3 px-4 py-4 min-[768px]:grid-cols-[minmax(132px,0.72fr)_minmax(0,1.5fr)_auto] min-[768px]:items-center min-[768px]:gap-x-5 min-[1200px]:grid-cols-[minmax(145px,0.8fr)_minmax(270px,1.7fr)_auto]">
    <div className="flex min-w-0 items-center justify-between gap-3 min-[768px]:row-span-2 min-[768px]:grid min-[768px]:gap-1">
      <div><h3 className="type-control">{routeTitle(route.platform)}</h3><p className="mt-0.5 type-meta text-muted">{modeLabel(route.runtime_mode)}</p></div>
      <StatusIndicator label={healthLabel[route.health]} tone={healthTone[route.health]} />
    </div>
    <div className="grid min-w-0 gap-1.5"><CandidateSlot label="主用" candidate={route.active_candidate} />{route.standby_candidates.map((candidate, index) => <CandidateSlot key={candidate.candidate_id} label={`备用 ${index + 1}`} candidate={candidate} />)}</div>
    <div className="flex items-center justify-between gap-3 min-[768px]:row-span-2 min-[768px]:justify-self-end">
      <div className="flex flex-wrap gap-x-4 gap-y-1 type-meta text-muted"><span>已核验 {route.binding_summary.ready_count} 条</span><span>上限 ${route.per_run_cap_usd.toFixed(2)}</span></div>
      <div className="shrink-0">{children}</div>
    </div>
    {route.degraded_reason && <p className="min-[768px]:col-span-3 type-meta text-muted">{reasonLabel(route.degraded_reason, route.binding_summary.pending_count)}</p>}
  </section>
}

function CandidateSlot({ label, candidate }: { label: string; candidate: CandidateView | null }) {
  return <div className="grid min-w-0 grid-cols-[3rem_minmax(0,1fr)] items-center gap-2">
    <span className="type-label whitespace-nowrap text-muted">{label}</span>
    <ActorOpsV2ActorChip candidate={candidate} />
  </div>
}

function modeLabel(mode: ActorOpsV2RouteView['runtime_mode']) {
  return mode === 'active' ? 'v2 获取中' : mode === 'shadow' ? '旁路核验' : '现役获取中'
}

function routeTitle(platform: string) {
  const titles: Record<string, string> = { instagram: 'Instagram 更新', x: 'X 动态', youtube: 'YouTube 视频更新' }
  return titles[platform] || '订阅更新'
}

function reasonLabel(reason: string, pendingBindings: number) {
  const labels: Record<string, string> = {
    actorops_v2_route_disabled: '当前仍走现役获取。',
    actorops_v2_no_runnable_candidate: '没有可运行的已验证 Actor。',
    actorops_v2_single_runnable_candidate: '当前只有 1 个可运行 Actor，仍可获取。',
  }
  return reason === 'actorops_v2_binding_not_ready' ? `有 ${pendingBindings} 条来源尚未完成 v2 核验。` : labels[reason] || '当前路线需要处理后才能继续。'
}
