import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { ActorOpsV2OperationEvent } from '../../api/actorOpsV2Types'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { Button, LoadingState, StatusIndicator, StatusNotice } from '../../design-system'

type OperationPresentation = { title: string; scope: string }

const operationLabels: Record<string, OperationPresentation> = {
  actorops_v2_candidate_promote: { title: '已调整主用 Actor', scope: 'Actor 路由' },
  actorops_v2_binding_verify: { title: '已核验来源 Binding', scope: '来源 Binding' },
  actorops_v2_binding_enable: { title: '已启用来源 Binding', scope: '来源 Binding' },
  actorops_v2_discovery_create: { title: '已创建候选发现任务', scope: '候选发现' },
  actorops_v2_discovery: { title: '已创建候选发现任务', scope: '候选发现' },
  actorops_v2_metadata_refresh: { title: '已刷新商城信息', scope: '商城信息' },
  actorops_v2_price_cap: { title: '已更新 Route 费用上限', scope: 'Route 费用' },
  actorops_v2_replacement_preview: { title: '已创建替换预览', scope: '替换计划' },
  actorops_v2_replacement_authorize: { title: '已授权替换计划', scope: '替换计划' },
  actorops_v2_replacement_apply: { title: '已应用替换计划', scope: '替换计划' },
  actorops_v2_replacement_cancel: { title: '已取消替换计划', scope: '替换计划' },
  actorops_v2_replacement: { title: '已更新替换计划', scope: '替换计划' },
  actorops_v2_workspace_maintenance_policy_update: { title: '已更新工作区维护策略', scope: '工作区维护' },
  actorops_v2_route_maintenance_policy_update: { title: '已更新 Route 维护策略', scope: 'Route 维护' },
  actorops_v2_execution_trace: { title: 'ActorOps 安全执行记录', scope: '执行轨迹' },
}

export function ActorOpsV2OperationEvents({ jobId }: { jobId?: string }) {
  const { api, user } = useAppContext()
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null)
  const events = useQuery({
    queryKey: queryKeys.actorOpsV2Events(user.id, jobId || ''),
    queryFn: ({ signal }) => api.actorOpsV2Events(jobId ? { job_id: jobId } : {}, signal),
    retry: false,
  })
  if (events.isPending) return <LoadingState label="正在读取 ActorOps v2 操作记录" rows={2} />
  if (events.isError || !events.data) return <StatusNotice title="ActorOps v2 操作记录读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void events.refetch()}>刷新日志</Button>
  </StatusNotice>
  if (events.data.availability === 'unavailable') return <StatusNotice title="ActorOps v2 操作记录当前不可用" status="warning">当前不会读取旧诊断记录；请稍后刷新日志。</StatusNotice>
  if (!events.data.events.length) return <p className="type-meta text-muted">{jobId ? '该任务尚无可显示的安全执行记录。' : '尚无可显示的 v2 管理操作记录。'}</p>
  return <ol className="grid gap-2" aria-label={jobId ? 'ActorOps 安全执行记录' : 'ActorOps v2 操作记录'}>
    {events.data.events.map((event) => <OperationEventRow
      key={event.event_id}
      event={event}
      open={expandedEventId === event.event_id}
      onOpenChange={(open) => setExpandedEventId(open ? event.event_id : null)}
    />)}
  </ol>
}

function OperationEventRow({ event, open, onOpenChange }: { event: ActorOpsV2OperationEvent; open: boolean; onOpenChange: (open: boolean) => void }) {
  const presentation = operationLabels[event.action]
  const outcome = outcomePresentation(event.outcome)
  return <li className="rounded-control border border-separator bg-surface-secondary p-3">
    <div className="grid min-w-0 gap-2 min-[640px]:grid-cols-[minmax(0,1fr)_auto] min-[640px]:items-center">
      <div className="min-w-0"><p className="type-control">{presentation?.title || '未识别管理操作'}</p><p className="mt-0.5 type-meta text-muted">{presentation?.scope || '安全管理记录'}</p></div>
      <div className="flex flex-wrap items-center justify-between gap-2 min-[640px]:justify-end"><StatusIndicator label={outcome.label} tone={outcome.tone} /><time className="type-meta text-muted">{formatTime(event.timestamp)}</time><Button size="sm" variant="ghost" onPress={() => onOpenChange(!open)} aria-expanded={open}>{open ? '收起详情' : '查看详情'}</Button></div>
    </div>
    {open && <OperationEventDetails event={event} unknownAction={!presentation} />}
  </li>
}

function OperationEventDetails({ event, unknownAction }: { event: ActorOpsV2OperationEvent; unknownAction: boolean }) {
  const entries = [
    event.phase ? ['阶段', safeText(event.phase)] : null,
    event.changed_fields?.length ? ['变更字段', '已记录管理字段'] : null,
    countLabel(event.counts),
    typeof event.final_cost_usd === 'number' ? ['最终费用', `$${event.final_cost_usd.toFixed(2)}`] : null,
    event.error_code ? ['错误码', safeCode(event.error_code)] : null,
    requestLabel(event),
    unknownAction ? ['安全 action code', safeActionCode(event.action)] : null,
  ].filter((entry): entry is [string, string] => Boolean(entry))
  if (!entries.length) return <p className="mt-2 type-meta text-muted">该记录没有更多可安全显示的详情。</p>
  return <dl className="mt-2 grid gap-x-4 gap-y-1 border-t border-separator pt-2 type-meta min-[640px]:grid-cols-2">
    {entries.map(([label, value]) => <div key={label} className="flex min-w-0 gap-2"><dt className="shrink-0 text-muted">{label}</dt><dd className="min-w-0 break-words">{value}</dd></div>)}
  </dl>
}

function outcomePresentation(value: string) {
  const labels: Record<string, { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' }> = {
    succeeded: { label: '已完成', tone: 'success' }, ok: { label: '已保存', tone: 'success' }, queued: { label: '已排队', tone: 'neutral' },
    failed: { label: '未完成', tone: 'danger' }, denied: { label: '已拒绝', tone: 'warning' }, unavailable: { label: '暂不可用', tone: 'warning' },
  }
  return labels[value] || { label: '状态已更新', tone: 'neutral' as const }
}

function countLabel(counts: ActorOpsV2OperationEvent['counts']): [string, string] | null {
  if (!counts) return null
  const count = Object.values(counts).filter((value) => Number.isFinite(value) && value >= 0).reduce((total, value) => total + value, 0)
  return ['数量', String(count)]
}

function requestLabel(event: ActorOpsV2OperationEvent): [string, string] | null {
  const method = event.method && /^(GET|POST|PATCH|PUT|DELETE)$/i.test(event.method) ? event.method.toUpperCase() : ''
  const status = typeof event.status_code === 'number' && event.status_code >= 100 && event.status_code <= 599 ? String(event.status_code) : ''
  return method || status ? ['请求结果', [method, status].filter(Boolean).join(' · ')] : null
}

function safeText(value: string) {
  return value.replace(/[^a-zA-Z0-9_\-/. ]/g, '').slice(0, 80) || '已记录'
}

function safeCode(value: string) {
  return /^[a-zA-Z0-9_:-]{1,120}$/.test(value) ? value : '已记录安全错误码'
}

function safeActionCode(value: string) {
  return /^actorops_v2_[a-z0-9_]{1,100}$/.test(value) ? value : 'actorops_v2_unknown'
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未记录' : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}
