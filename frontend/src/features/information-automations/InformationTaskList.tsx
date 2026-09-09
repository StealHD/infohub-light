import { useState } from 'react'
import type { InformationRule } from '../../api/informationAutomationService'
import { Button, Card, EmptyState, Icons, SearchField, StatusIndicator } from '../../design-system'
import { ruleStateLabels, triggerLabel } from './informationRuleModel'
import { informationTestStatusLabel, type InformationTestSession } from './useInformationTests'

const filters = [ ['all', '全部'], ['active', '已开启'], ['paused', '已暂停'], ['draft', '草稿'], ['archived', '已归档'] ] as const

export function InformationTaskList({ rules, selected, onSelect, loading, hasMore, testStatuses = {} }: {
  rules: InformationRule[]; selected: string | null; onSelect: (id: string) => void; loading: boolean; hasMore: boolean
  testStatuses?: Record<string, InformationTestSession['phase']>
}) {
  const [filter, setFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const visible = rules.filter((rule) => (filter === 'all' || rule.state === filter)
    && `${rule.config.name} ${rule.config.requirement} ${rule.source_names?.join(' ') || ''}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  return <div className="grid min-w-0 gap-4">
    <div role="group" aria-label="任务状态筛选" className="flex flex-wrap gap-1">
      {filters.map(([id, label]) => <Button key={id} size="sm" variant={filter === id ? 'secondary' : 'ghost'}
        aria-pressed={filter === id} onPress={() => setFilter(id)}>{label}</Button>)}
    </div>
    <SearchField aria-label="搜索已安排任务" value={search} onChange={setSearch} fullWidth>
      <SearchField.Group><SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon>
        <SearchField.Input id="information-task-search" placeholder="搜索任务名称、描述或来源" /><SearchField.ClearButton aria-label="清除任务搜索" />
      </SearchField.Group>
    </SearchField>
    {hasMore && <p className="type-meta text-muted">搜索与筛选当前已加载任务；可加载更多以继续查找。</p>}
    <ul aria-label="自动化任务" className="grid min-w-0 gap-2">
      {visible.map((rule) => <li key={rule.id} className="min-w-0"><Card variant="secondary" className="p-0">
        <button id={`information-task-${rule.id}`} type="button" aria-label={`查看与编辑 ${rule.config.name}`} aria-expanded={selected === rule.id}
          onClick={() => onSelect(rule.id)} className={`flex min-w-0 w-full items-center gap-3 rounded-[var(--inteliscope-radius-card)] p-4 text-left focus-visible:outline focus-visible:outline-accent ${selected === rule.id ? 'bg-default' : 'hover:bg-default'}`}>
          <StatusIndicator iconOnly withTooltip={false} tone={rule.state === 'active' ? 'success' : 'neutral'} label={ruleStateLabels[rule.state]} />
          <span className="min-w-0 flex-1"><span className="type-control block break-words [overflow-wrap:anywhere]">{rule.config.name}</span>
            <span className="type-meta mt-1 block break-words text-muted">{ruleStateLabels[rule.state]} · {triggerLabel(rule.config.trigger)}
              {rule.next_due ? ` · 下次处理 ${new Date(rule.next_due).toLocaleString()}` : ''}</span>
            {testStatuses[rule.id] && testStatuses[rule.id] !== 'idle' && <span className={`type-meta mt-1 block ${['failed', 'submission_unknown'].includes(testStatuses[rule.id] || '') ? 'text-danger' : 'text-accent'}`}>
              {informationTestStatusLabel(testStatuses[rule.id] as InformationTestSession['phase'])}
            </span>}
          </span><Icons.ChevronRight size={15} className="shrink-0 text-muted" aria-hidden="true" />
        </button>
      </Card></li>)}
    </ul>
    {!loading && !visible.length && <EmptyState title={rules.length ? '没有匹配的任务' : '还没有自动化任务'}
      description={rules.length ? '试试其他状态或搜索词。' : '点击“新建自动化”，描述任务、选择来源和频率。保存草稿后，再确认启用。'} />}
  </div>
}
