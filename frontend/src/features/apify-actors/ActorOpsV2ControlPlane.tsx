import { useState, type ReactNode } from 'react'

import { Card, StatusIndicator } from '../../design-system'
import { ActorOpsV2ActorChip } from './ActorOpsV2ActorChip'
import { ActorOpsV2RouteDetailPanel, ActorOpsV2RouteDetailTrigger } from './ActorOpsV2RouteDetail'
import { type ActorOpsV2CandidateView, type ActorOpsV2RouteView } from './actorOpsV2RouteModel'

export type { ActorOpsV2RouteView } from './actorOpsV2RouteModel'

type CandidateView = ActorOpsV2CandidateView

const healthTone = { healthy: 'success', degraded: 'warning', unavailable: 'danger' } as const
const healthLabel = { healthy: '健康', degraded: '降级可用', unavailable: '不可用' } as const

export function ActorOpsV2ControlPlane({ routes, focusedRouteKey, renderRouteActions }: {
  routes: ActorOpsV2RouteView[]
  focusedRouteKey?: string
  renderRouteActions?: (route: ActorOpsV2RouteView) => ReactNode
}) {
  const [expandedRouteId, setExpandedRouteId] = useState<string | null>(null)
  return <div className="grid gap-5" data-testid="actorops-v2-control-plane">
    <section className="grid gap-1" aria-labelledby="actorops-v2-routes-heading">
      <h2 id="actorops-v2-routes-heading" className="type-page-title">ActorOps v2 路由</h2>
      <p className="type-body text-muted">商城标价只作参考；费用上限和替换都需要单独确认。</p>
    </section>
    <div className="grid gap-3">
      {routes.map((route) => <RouteCard
        key={route.route_id}
        route={route}
        isFocused={Boolean(focusedRouteKey && route.route_key.startsWith(focusedRouteKey))}
        open={expandedRouteId === route.route_id}
        onOpenChange={(open) => setExpandedRouteId(open ? route.route_id : null)}
      >{renderRouteActions?.(route)}</RouteCard>)}
    </div>
  </div>
}

function RouteCard({ route, children, isFocused, open, onOpenChange }: {
  route: ActorOpsV2RouteView
  children?: ReactNode
  isFocused: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return <Card data-actorops-route-card={route.platform} data-actorops-route-key={route.route_key} data-actorops-route-focused={isFocused || undefined} variant="secondary" className={`gap-0 border border-separator bg-surface-secondary p-0 ${isFocused ? 'ring-2 ring-focus' : ''}`}>
    <Card.Header className="flex min-w-0 flex-row items-start justify-between gap-3 px-4 py-2.5">
      <div className="min-w-0"><Card.Title className="type-control">{routeTitle(route.platform)}</Card.Title><Card.Description className="type-meta mt-0.5 text-muted">{modeLabel(route.runtime_mode)}</Card.Description></div>
      <StatusIndicator label={healthLabel[route.health]} tone={healthTone[route.health]} />
    </Card.Header>
    <Card.Content className="grid gap-1.5 px-4 pb-2.5 pt-0">
      <div className="grid min-w-0 gap-1.5 min-[768px]:grid-cols-2 min-[768px]:gap-x-6">
        <CandidateSlot label="主用" candidate={route.active_candidate} />
        {route.standby_candidates.map((candidate, index) => <CandidateSlot key={candidate.candidate_id} label={`备用 ${index + 1}`} candidate={candidate} />)}
      </div>
      {route.degraded_reason && <p className="type-meta text-muted">{reasonLabel(route.degraded_reason, route.binding_summary.pending_count)}</p>}
    </Card.Content>
    <Card.Footer className="flex min-w-0 flex-row flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-t border-separator px-4 py-2">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 type-meta text-muted">
        <RecentSuccess candidate={route.last_known_good} />
        <span>已核验 {route.binding_summary.ready_count} 条</span><span>上限 ${route.per_run_cap_usd.toFixed(2)}</span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1"><ActorOpsV2RouteDetailTrigger open={open} onOpenChange={onOpenChange} />{children}</div>
    </Card.Footer>
    {open && <div className="px-4 pb-3"><ActorOpsV2RouteDetailPanel route={route} open={open} /></div>}
  </Card>
}

function CandidateSlot({ label, candidate }: { label: string; candidate: CandidateView | null }) {
  return <div className="grid min-w-0 grid-cols-[3rem_minmax(0,1fr)] items-center gap-2">
    <span className="type-label whitespace-nowrap text-muted">{label}</span>
    <ActorOpsV2ActorChip candidate={candidate} />
  </div>
}

function RecentSuccess({ candidate }: { candidate: CandidateView | null }) {
  return <span className="min-w-0 truncate">最近成功：{candidate?.store_metadata?.display_name || '未记录'}</span>
}

function modeLabel(mode: ActorOpsV2RouteView['runtime_mode']) {
  return mode === 'active' ? 'v2 获取中' : 'ActorOps 已停用'
}

function routeTitle(platform: string) {
  const titles: Record<string, string> = { instagram: 'Instagram 更新', x: 'X 动态', youtube: 'YouTube 视频更新' }
  return titles[platform] || '订阅更新'
}

function reasonLabel(reason: string, pendingBindings: number) {
  const labels: Record<string, string> = {
    actorops_v2_route_disabled: '当前路线停用，不会回退到旧 ActorOps。',
    actorops_v2_route_migration_required: '当前路线需要完成单轨迁移后才能启用。',
    actorops_v2_no_runnable_candidate: '没有可运行的已验证 Actor。',
    actorops_v2_single_runnable_candidate: '当前只有 1 个可运行 Actor，仍可获取。',
  }
  return reason === 'actorops_v2_binding_not_ready' ? `有 ${pendingBindings} 条来源尚未完成 v2 核验。` : labels[reason] || '当前路线需要处理后才能继续。'
}
