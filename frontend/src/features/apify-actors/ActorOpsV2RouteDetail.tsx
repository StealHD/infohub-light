import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import type { ActorOpsV2RouteDetail as RouteDetail } from '../../api/actorOpsV2Types'
import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { Button, LoadingState, StatusNotice } from '../../design-system'
import { actorOpsV2CandidateLabel, actorOpsV2PriceLabel, type ActorOpsV2RouteView } from './actorOpsV2RouteModel'

export function ActorOpsV2RouteDetailTrigger({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <Button size="sm" variant="ghost" onPress={() => onOpenChange(!open)} aria-expanded={open}>
    {open ? '收起运行详情' : '查看运行详情'}
  </Button>
}

export function ActorOpsV2RouteDetailPanel({ route, open }: { route: ActorOpsV2RouteView; open: boolean }) {
  const { api, user } = useAppContext()
  const detail = useQuery({
    queryKey: queryKeys.actorOpsV2Route(user.id, route.route_id),
    queryFn: ({ signal }) => api.actorOpsV2Route(route.route_id, signal),
    enabled: open,
    retry: false,
  })
  return open ? <section aria-label={`${route.platform} 运行详情`} className="mt-3 grid gap-3 rounded-xl border border-separator bg-surface-secondary p-3">
      {detail.isPending && <LoadingState label="正在读取 v2 运行详情" rows={2} />}
      {detail.isError && <StatusNotice title={detailErrorTitle(detail.error)} status="warning">
        {isRetiredDetailError(detail.error) ? '请从当前 v2 Route、Binding、Discovery 或 Replacement 控制面继续操作。' : <Button size="sm" variant="ghost" onPress={() => void detail.refetch()}>重试此区域</Button>}
      </StatusNotice>}
      {detail.data && <RouteDetailPanel detail={detail.data} />}
    </section> : null
}

function detailErrorTitle(error: unknown) {
  return isRetiredDetailError(error)
    ? '旧 ActorOps 详情已退役'
    : 'ActorOps v2 运行详情读取失败'
}

function isRetiredDetailError(error: unknown) {
  return error instanceof ApiError && error.code === 'actorops_v1_retired'
}

function RouteDetailPanel({ detail }: { detail: RouteDetail }) {
  return <>
    <DetailSection title="候选与商城信息">
      {detail.candidates.length
        ? detail.candidates.map((candidate) => <p key={candidate.candidate_id} className="type-meta text-muted">
          {actorOpsV2CandidateLabel(candidate)} · {candidate.assignment === 'active' ? '主用' : candidate.assignment === 'standby' ? '备用' : '未分配'} · {actorOpsV2PriceLabel(candidate)}
        </p>)
        : <Empty label="暂无可显示的 Candidate。" />}
    </DetailSection>
    <DetailSection title="来源 Binding">
      <p className="type-meta text-muted">已就绪 {detail.bindings.filter((item) => item.status === 'ready').length} 条；待核验 {detail.bindings.filter((item) => item.status === 'pending').length} 条；停用 {detail.bindings.filter((item) => item.status === 'disabled').length} 条。</p>
    </DetailSection>
    <DetailSection title="近期运行与费用">
      {detail.attempts.length
        ? detail.attempts.slice(0, 5).map((attempt) => <p key={attempt.attempt_id} className="type-meta text-muted">
          {attempt.kind} · {attempt.status} · {costLabel(attempt.actual_cost_usd, attempt.cost_final)}
        </p>)
        : <Empty label="尚无 v2 运行记录。" />}
    </DetailSection>
    <DetailSection title="发现与替换">
      {detail.discoveries.slice(0, 3).map((discovery) => <p key={discovery.discovery_id} className="type-meta text-muted">发现任务 · {discovery.status} · {discovery.stage} · 候选 {discovery.candidate_count}</p>)}
      {detail.replacements.slice(0, 3).map((plan) => <p key={plan.plan_id} className="type-meta text-muted">替换计划 · {plan.status} · {actorOpsV2CandidateLabel(plan.candidate)} · 上限 ${plan.total_cap_usd.toFixed(2)}</p>)}
      {detail.freshness_summary && <p className="type-meta text-muted">新鲜度 · 疑似旧数据 {detail.freshness_summary.suspected_stale} · 已来源级降级 {detail.freshness_summary.source_stale}</p>}
      {detail.repairs?.slice(0, 2).map((repair) => <p key={repair.repair_id} className="type-meta text-muted">自动修复 · {repair.status}{repair.error_code ? ` · ${repair.error_code}` : ''}</p>)}
      {!detail.discoveries.length && !detail.replacements.length && <Empty label="尚无 Discovery 或替换计划。" />}
    </DetailSection>
    <DetailSection title="维护预算">
      <p className="type-meta text-muted">{detail.maintenance_policy.authorized ? '维护已授权' : '维护默认停用'} · 已结算 ${detail.maintenance_policy.budget.spent_usd.toFixed(2)} · 预留 ${detail.maintenance_policy.budget.reserved_usd.toFixed(2)}</p>
    </DetailSection>
  </>
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="grid gap-1.5">
    <h4 className="type-label">{title}</h4>
    {children}
  </section>
}

function Empty({ label }: { label: string }) {
  return <p className="type-meta text-muted">{label}</p>
}

function costLabel(value: number | null, final: boolean) {
  if (value === null) return final ? '费用已结算' : '费用待对账'
  return `$${value.toFixed(2)}${final ? ' 已结算' : ' 待对账'}`
}
