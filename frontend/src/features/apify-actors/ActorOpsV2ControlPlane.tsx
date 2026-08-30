import { useState, type ReactNode } from 'react'

import { Card, StatusIndicator } from '../../design-system'
import { ActorOpsV2ActorChip } from './ActorOpsV2ActorChip'
import { ActorOpsV2RouteDetailPanel, ActorOpsV2RouteDetailTrigger } from './ActorOpsV2RouteDetail'
import { ActorOpsV2RouteWorkflowSummary } from './ActorOpsV2WorkflowProgress'
import { orderedActorOpsV2StandbyCandidates, type ActorOpsV2CandidateView, type ActorOpsV2RouteView } from './actorOpsV2RouteModel'

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
  const routeReason = visibleRouteReason(route)
  return <Card data-actorops-route-card={route.platform} data-actorops-route-key={route.route_key} data-actorops-route-focused={isFocused || undefined} variant="secondary" className={`gap-0 border border-separator bg-surface-secondary p-0 ${isFocused ? 'ring-2 ring-focus' : ''}`}>
    <Card.Header className="flex min-w-0 flex-row items-center justify-between gap-3 px-4 py-2.5">
      <div data-actorops-route-heading className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"><Card.Title className="type-control">{routeTitle(route.platform)}</Card.Title><Card.Description className="type-meta text-muted">{modeLabel(route.runtime_mode)}</Card.Description></div>
      <StatusIndicator label={healthLabel[route.health]} tone={healthTone[route.health]} />
    </Card.Header>
    <Card.Content className="grid gap-1.5 px-4 pb-2.5 pt-0">
      <div className="grid min-w-0 gap-1.5 min-[768px]:grid-cols-2 min-[768px]:gap-x-6">
        <CandidateSlot label="主用" candidate={route.active_candidate} />
        {[1, 2].map((priority) => <CandidateSlot key={`standby-${priority}`} label={`备用 ${priority}`} candidate={standbyCandidate(route, priority)} />)}
      </div>
      {routeReason && <p className="type-meta text-muted">{reasonLabel(routeReason, route.binding_summary.pending_count)}</p>}
      <ActorOpsV2RouteWorkflowSummary workflow={route.workflow} />
    </Card.Content>
    <Card.Footer className="grid min-w-0 gap-x-4 gap-y-2 border-t border-separator px-4 py-2 min-[768px]:grid-cols-[minmax(0,1fr)_auto] min-[768px]:items-center">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 type-meta text-muted">
        <RecentSuccess candidate={route.last_known_good} />
        <span>稳定路径 {route.stable_candidate_count}</span>
        {route.cooling_candidate_count > 0 && <span>冷却 {route.cooling_candidate_count}</span>}
        {route.at_risk_source_count > 0 && <span>风险来源 {route.at_risk_source_count}</span>}
        {route.fallback_source_count > 0 && <span>原生降级 {route.fallback_source_count}</span>}
        <span>已核验 {route.binding_summary.ready_count} 条</span><span>上限 ${route.per_run_cap_usd.toFixed(2)}</span>
      </div>
      <div data-actorops-route-actions className="flex min-w-0 flex-wrap items-center justify-end gap-1"><ActorOpsV2RouteDetailTrigger open={open} onOpenChange={onOpenChange} />{children}</div>
    </Card.Footer>
    {open && <div className="px-4 pb-3"><ActorOpsV2RouteDetailPanel route={route} open={open} /></div>}
  </Card>
}

function standbyCandidate(route: ActorOpsV2RouteView, priority: number) {
  return orderedActorOpsV2StandbyCandidates(route.standby_candidates).find(
    (candidate, index) => (candidate.priority ?? index + 1) === priority,
  ) || null
}

function visibleRouteReason(route: ActorOpsV2RouteView) {
  const controlReasons = new Set([
    'actorops_v2_route_disabled',
    'actorops_v2_route_migration_required',
    'actorops_v2_binding_not_ready',
  ])
  if (route.degraded_reason && controlReasons.has(route.degraded_reason)) return route.degraded_reason
  return route.health_reason || route.degraded_reason
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
    all_sources_redundant: '全部就绪来源都有至少两条稳定 Actor 路径。',
    insufficient_stable_paths: '仍可获取，但至少一个来源缺少稳定冗余，维护任务会继续补池。',
    source_fallback_only: '至少一个来源当前只能使用免费原生降级，Actor 路径正在修复。',
    source_unavailable: '至少一个来源既没有可运行 Actor，也没有可信免费降级。',
  }
  return reason === 'actorops_v2_binding_not_ready' ? `有 ${pendingBindings} 条来源尚未完成 v2 核验。` : labels[reason] || '当前路线需要处理后才能继续。'
}
