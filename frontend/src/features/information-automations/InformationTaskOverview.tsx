import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRule, InformationRuleConfig } from '../../api/informationAutomationService'
import { Card, Icons, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import { queryKeys } from '../../api/queryKeys'
import { useInformationContext } from './useInformationContext'
import { informationSourceLabel } from './informationSourceLabel'
import { triggerLabel } from './informationRuleModel'
import { InformationRecentRuns } from './InformationRecentRuns'

export function InformationTaskOverview({ rule, config, dirty, onViewRuns }: { rule: InformationRule; config: InformationRuleConfig; dirty: boolean; onViewRuns: () => void }) {
  const { api, userId } = useInformationContext()
  const [expanded, setExpanded] = useState(false)
  const sources = useQuery({ queryKey: queryKeys.subscriptions(userId), queryFn: ({ signal }) => api.subscriptions(signal) })
  const targets = useQuery({ queryKey: queryKeys.notificationServices(userId), queryFn: ({ signal }) => api.notificationServices(signal) })
  const selectedSources = config.source_ids.map((id) => sources.data?.subscriptions.find((source) => source.source_id === id)).filter(Boolean) as NonNullable<typeof sources.data>['subscriptions']
  const sourceSummary = selectedSources.length
    ? `${selectedSources.slice(0, 2).map(informationSourceLabel).join('、')}${selectedSources.length > 2 ? `，另有 ${selectedSources.length - 2} 个` : ''}`
    : config.source_ids.length ? `${config.source_ids.length} 个订阅源` : '尚未选择'
  const target = targets.data?.services.find((item) => item.id === config.target_id)?.name || (config.target_id ? '已选通知目标' : '尚未选择')
  return <div className="grid gap-4">
    {dirty && <p role="status" className="type-meta text-warning">有未保存修改；概览显示当前草稿。</p>}
    <Card variant="secondary" className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 p-4"><p className={`type-body whitespace-pre-wrap break-words ${expanded ? '' : 'line-clamp-4'}`}>{config.requirement || '尚未填写任务描述'}</p>
      {config.requirement && <Tooltip delay={250}><TooltipTriggerButton aria-label={expanded ? '收起完整描述' : '展开完整描述'} aria-expanded={expanded}
        className="size-8 shrink-0 rounded-[var(--inteliscope-radius-control)] text-muted hover:bg-default" onClick={() => setExpanded((value) => !value)}>
        {expanded ? <Icons.ChevronUp size={16} aria-hidden="true" /> : <Icons.ChevronDown size={16} aria-hidden="true" />}
      </TooltipTriggerButton><Tooltip.Content {...topAnchoredTooltipProps}>{expanded ? '收起描述' : '展开完整描述'}</Tooltip.Content></Tooltip>}
    </Card>
    <dl className="grid gap-3">
      <SummaryRow label="订阅源" value={sourceSummary} />
      <SummaryRow label="模型" value={config.model?.id || '尚未选择'} />
      <SummaryRow label="触发" value={triggerLabel(config.trigger)} />
      <SummaryRow label="通知目标" value={target} />
      <SummaryRow label="最近更新" value={`${new Date(rule.updated_at).toLocaleString()} · 版本 ${rule.version}`} />
    </dl>
    <InformationRecentRuns ruleId={rule.id} onViewAll={onViewRuns} />
  </div>
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return <div className="grid gap-1 border-b border-separator pb-3"><dt className="type-meta text-muted">{label}</dt><dd className="type-body break-words [overflow-wrap:anywhere]">{value}</dd></div>
}
