import type { ReactNode } from 'react'

import { Card, StatusIndicator } from '../../design-system'
import { actorOpsV2CandidateLabel, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

export type ActorOpsV2RouteView = {
  actorops_version: 2
  route_id: string
  route_generation: number
  route_key: string
  platform: string
  health: 'healthy' | 'degraded' | 'unavailable'
  runtime_mode: 'disabled' | 'shadow' | 'active'
  active_candidate: CandidateView | null
  standby_candidates: CandidateView[]
  last_known_good: CandidateView | null
  last_success_at: string | null
  degraded_reason: string | null
  binding_summary: BindingSummaryView
}

type CandidateView = ActorOpsV2CandidateView

type BindingSummaryView = {
  ready_count: number
  pending_count: number
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
  renderRouteActions,
}: {
  routes: ActorOpsV2RouteView[]
  operationsContent?: ReactNode
  renderRouteActions?: (route: ActorOpsV2RouteView) => ReactNode
}) {
  return <div className="grid gap-5" data-testid="actorops-v2-control-plane">
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div>
        <Card.Title>ActorOps v2 路由</Card.Title>
        <Card.Description className="mt-1">只显示当前实际获取会用到的主备和来源状态。切换主用或核验来源不会启动 Actor，也不会产生费用。</Card.Description>
      </div>
      <div className="grid gap-3 min-[720px]:grid-cols-2 min-[1100px]:grid-cols-3">
        {routes.map((route) => <RouteCard key={route.route_id} route={route}>{renderRouteActions?.(route)}</RouteCard>)}
      </div>
    </Card>
    {operationsContent}
  </div>
}

function RouteCard({ route, children }: { route: ActorOpsV2RouteView; children?: ReactNode }) {
  const active = route.active_candidate
  const standby = route.standby_candidates
  return <Card className="grid min-w-0 gap-3 p-4">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0"><Card.Title className="break-words">{routeTitle(route.platform)}</Card.Title><Card.Description className="mt-1">{modeLabel(route.runtime_mode)}</Card.Description></div>
      <StatusIndicator label={healthLabel[route.health]} tone={healthTone[route.health]} />
    </div>
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 type-meta">
      <RouteValue label="主用" value={actorOpsV2CandidateLabel(active)} />
      <RouteValue label="备用" value={standby.length ? standby.map(actorOpsV2CandidateLabel).join('、') : '未配置'} />
      <RouteValue label="已核验来源" value={`${route.binding_summary.ready_count} 条`} />
      <RouteValue label="最近新增" value={formatDate(route.last_success_at)} />
    </dl>
    {route.degraded_reason && <Card.Description className="break-words">{reasonLabel(route.degraded_reason, route.binding_summary.pending_count)}</Card.Description>}
    {children}
  </Card>
}

function RouteValue({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-muted">{label}</dt><dd className="mt-0.5 break-words type-control">{value}</dd></div>
}

function modeLabel(mode: ActorOpsV2RouteView['runtime_mode']) {
  return mode === 'active' ? '已启用 v2 获取' : mode === 'shadow' ? '正在旁路核验' : '仍使用现役获取'
}

function routeTitle(platform: string) {
  const titles: Record<string, string> = {
    instagram: 'Instagram 更新', x: 'X 动态', youtube: 'YouTube 视频更新',
  }
  return titles[platform] || '订阅更新'
}

function formatDate(value: string | null) {
  if (!value) return '还没有新增内容'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '已记录'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

function reasonLabel(reason: string, pendingBindings: number) {
  const labels: Record<string, string> = {
    actorops_v2_route_disabled: '此路线还未切到 v2，当前订阅仍会走现役获取。',
    actorops_v2_no_runnable_candidate: '没有可运行的已验证 Actor；不会尝试抓取。',
    actorops_v2_single_runnable_candidate: '当前只有 1 个可运行 Actor，仍可获取；建议后续补充备用。',
  }
  if (reason === 'actorops_v2_binding_not_ready') return `有 ${pendingBindings} 条来源尚未完成 v2 核验；核验前不会由 v2 获取。`
  return labels[reason] || '当前路线需要处理后才能继续。'
}
