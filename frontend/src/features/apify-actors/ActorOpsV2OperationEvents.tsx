import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { Button, LoadingState, StatusNotice } from '../../design-system'

const actionLabels: Record<string, string> = {
  actorops_v2_candidate_promote: '已调整主用 Actor',
  actorops_v2_binding_verify: '已核验来源 Binding',
  actorops_v2_discovery: '已创建候选发现任务',
  actorops_v2_metadata_refresh: '已刷新商城元数据',
  actorops_v2_replacement: '已更新替换计划',
}

export function ActorOpsV2OperationEvents() {
  const { api, user } = useAppContext()
  const events = useQuery({
    queryKey: queryKeys.actorOpsV2Events(user.id),
    queryFn: ({ signal }) => api.actorOpsV2Events({}, signal),
    retry: false,
  })
  if (events.isPending) return <LoadingState label="正在读取 ActorOps v2 操作记录" rows={2} />
  if (events.isError || !events.data) return <StatusNotice title="ActorOps v2 操作记录读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void events.refetch()}>重试此区域</Button>
  </StatusNotice>
  if (events.data.availability === 'unavailable') return <StatusNotice title="ActorOps v2 操作记录当前不可用" status="warning">当前不会读取旧诊断记录；请稍后重试此区域。</StatusNotice>
  if (!events.data.events.length) return <p className="type-meta text-muted">尚无可显示的 v2 管理操作记录。</p>
  return <ol className="grid gap-2" aria-label="ActorOps v2 操作记录">
    {events.data.events.map((event) => <li key={event.event_id} className="rounded-control border border-separator bg-surface-secondary p-3">
      <p className="type-control">{actionLabels[event.action] || 'ActorOps v2 管理操作'}</p>
      <p className="mt-1 type-meta text-muted">{outcomeLabel(event.outcome)} · {formatTime(event.timestamp)}</p>
    </li>)}
  </ol>
}

function outcomeLabel(value: string) {
  const labels: Record<string, string> = { succeeded: '已完成', ok: '已保存', queued: '已排队', failed: '未完成', denied: '已拒绝', unavailable: '暂不可用' }
  return labels[value] || '状态已更新'
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未记录' : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}
