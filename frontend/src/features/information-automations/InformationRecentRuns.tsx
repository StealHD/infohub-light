import { useQuery } from '@tanstack/react-query'
import { Button } from '../../design-system'
import { judgmentLabels, notificationLabel } from './informationRuleModel'
import { useInformationContext } from './useInformationContext'

export function InformationRecentRuns({ ruleId, onViewAll }: { ruleId: string; onViewAll: () => void }) {
  const { api, userId } = useInformationContext()
  const query = useQuery({ queryKey: ['information-runs', userId, ruleId, 'recent'],
    queryFn: ({ signal }) => api.informationRuns(ruleId, 0, signal), refetchInterval: 15000 })
  const runs = query.data?.items.slice(0, 3) || []
  return <section className="grid gap-3 border-t border-separator pt-4" aria-label="最近运行">
    <div className="flex items-center gap-2"><h3 className="type-section-title min-w-0 flex-1">最近运行</h3>
      <Button size="sm" variant="ghost" onPress={onViewAll}>查看全部</Button></div>
    {query.isPending && <p role="status" className="type-meta text-muted">正在读取最近运行…</p>}
    {query.isError && <p role="alert" className="type-meta">最近运行读取失败，请在运行记录中重试。</p>}
    {!query.isPending && !query.isError && !runs.length && <p className="type-meta text-muted">暂无运行。启动后只处理新增内容。</p>}
    {runs.length > 0 && <ul className="grid gap-2" aria-label="最近三次运行">
      {runs.map((run) => <li key={run.id} className="grid gap-1 border-b border-separator pb-2 last:border-b-0 last:pb-0">
        <time className="type-meta text-muted">{new Date(run.created_at).toLocaleString()}</time>
        <p className="type-body break-words">{judgmentLabels[run.status]} · {notificationLabel(run)}</p>
      </li>)}
    </ul>}
  </section>
}
