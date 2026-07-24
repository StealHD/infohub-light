import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { CatalogSource, FeedSchedule, Job, SourceHealthItem, SourceTypeDefinition, SourceUsage, Subscription, TaxonomyOptions } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  actionToast,
  anchoredTooltipProps,
  Button,
  Card,
  Chip,
  Icons,
  LoadingState,
  Modal,
  PageFrame,
  SearchField,
  Tabs,
  Tooltip,
  TooltipTriggerButton,
} from '../../design-system'
import { describeFeedJob } from '../jobs/jobModel'
import { useWorkbenchAgentContext } from '../workbench-live/workbenchAgentContext'
import {
  canEditSource,
  canMutateSubscriptions,
  effectiveSubscriptionChannel,
  groupSourcesByChannel,
  healthMatches,
  isPublicSubscriptionScope,
  isSourceSubscribed,
  presentSourceHealthIssue,
  presentJob,
  sourceForSubscription,
  sourceScopesForUser,
  sourceScopeLabel,
  sourceTypeLabel,
  sourceUsesSecret,
  type HealthFilter,
} from '../subscriptions/subscriptionModel'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'
import { HeroResponseSchemaDetails } from './HeroResponseSchemaDetails'
import { HeroDialog, SourceForm, SubscriptionForm } from './HeroSubscriptionDialogs'

type SubscriptionEntry = { source: CatalogSource; subscription: Subscription; health?: SourceHealthItem; channel: string }
const adminRole = (role: string) => role === 'owner' || role === 'admin'
const healthLabel: Record<string, string> = { healthy: '正常', degraded: '需关注', failing: '连续失败', unknown: '尚未抓取' }
const formatTime = (value?: string | null) => {
  if (!value) return '时间未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间未知' : parsed.toLocaleString('zh-CN')
}

const healthOptions = [{ id: 'all', label: '全部健康状态' }, { id: 'healthy', label: '正常' }, { id: 'degraded', label: '需关注' }, { id: 'failing', label: '连续失败' }, { id: 'unknown', label: '尚未抓取' }]
const scopeOptions = [{ id: 'all', label: '全部范围' }, { id: 'public', label: '公共订阅' }, { id: 'private', label: '私人订阅' }]

function SourceFilters({ search, onSearchChange, definitions, typeFilter, onTypeChange, scopeFilter, onScopeChange, healthFilter, onHealthChange, includeHealth }: {
  search: string
  onSearchChange: (value: string) => void
  definitions: SourceTypeDefinition[]
  typeFilter: string
  onTypeChange: (value: string) => void
  scopeFilter: string
  onScopeChange: (value: string) => void
  healthFilter: HealthFilter
  onHealthChange: (value: HealthFilter) => void
  includeHealth: boolean
}) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const activeCount = Number(typeFilter !== 'all') + Number(scopeFilter !== 'all') + Number(includeHealth && healthFilter !== 'all')
  const typeOptions = [{ id: 'all', label: '全部类型' }, ...definitions.map((definition) => ({ id: definition.type, label: definition.label || sourceTypeLabel(definition.type) }))]
  const clear = () => {
    onTypeChange('all')
    onScopeChange('all')
    if (includeHealth) onHealthChange('all')
  }
  const searchField = <SearchField aria-label="搜索来源" value={search} onChange={onSearchChange} fullWidth><SearchField.Group><SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon><SearchField.Input placeholder="搜索来源" /><SearchField.ClearButton /></SearchField.Group></SearchField>

  return <>
    <div data-mobile-source-filters className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 min-[768px]:hidden">
      {searchField}
      <Modal isOpen={mobileOpen} onOpenChange={setMobileOpen}>
        <Button type="button" variant="secondary" aria-label={`筛选来源，已启用 ${activeCount} 项`}><Icons.SlidersHorizontal size={15} />筛选{activeCount > 0 ? ` ${activeCount}` : ''}</Button>
        <Modal.Backdrop>
          <Modal.Container placement="bottom" size="lg">
            <Modal.Dialog>
              <Modal.Header><Modal.Heading>筛选来源</Modal.Heading></Modal.Header>
              <Modal.Body className="grid gap-4">
                <HeroSelect label="来源类型" value={typeFilter} onChange={onTypeChange} options={typeOptions} />
                {includeHealth && <HeroSelect label="健康状态" value={healthFilter} onChange={(value) => onHealthChange(value as HealthFilter)} options={healthOptions} />}
                <HeroSelect label="可见范围" value={scopeFilter} onChange={onScopeChange} options={scopeOptions} />
              </Modal.Body>
              <Modal.Footer>
                <Button type="button" variant="ghost" isDisabled={activeCount === 0} onPress={clear}>清除筛选</Button>
                <Button type="button" onPress={() => setMobileOpen(false)}>关闭筛选</Button>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </div>
    <div data-desktop-source-filters className={`hidden gap-3 min-[768px]:grid ${includeHealth ? 'min-[768px]:grid-cols-4' : 'min-[768px]:grid-cols-3'}`}>
      {searchField}
      <HeroSelect label="来源类型" value={typeFilter} onChange={onTypeChange} options={typeOptions} />
      {includeHealth && <HeroSelect label="健康状态" value={healthFilter} onChange={(value) => onHealthChange(value as HealthFilter)} options={healthOptions} />}
      <HeroSelect label="可见范围" value={scopeFilter} onChange={onScopeChange} options={scopeOptions} />
    </div>
  </>
}

function FeedScheduleControls({ schedule, editable, pending, onUpdate }: {
  schedule?: FeedSchedule
  editable: boolean
  pending: boolean
  onUpdate: (patch: { enabled: boolean; interval_minutes: number }) => void
}) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const interval = schedule?.interval_minutes ?? 360
  const intervalOptions = (schedule?.allowed_intervals ?? [60, 180, 360, 720, 1440]).map((value) => ({ id: String(value), label: value < 60 ? `每 ${value} 分钟` : `每 ${value / 60} 小时` }))
  const status = `${schedule?.enabled ? `已开启 · ${interval < 60 ? `每 ${interval} 分钟` : `每 ${interval / 60} 小时`}` : '已关闭'} · ${schedule?.worker_status === 'ready' ? '后台服务正常' : '后台服务不可用'}`
  const controls = <div className="flex flex-col gap-3 min-[720px]:flex-row min-[720px]:items-end">
    <div className="type-body flex-1 text-muted">{schedule?.enabled ? `下次计划：${formatTime(schedule.next_run_at)}` : '自动更新当前已关闭。'} · {schedule?.worker_status === 'ready' ? '后台服务正常' : '后台服务不可用'}</div>
    <HeroSelect label="更新周期" value={String(interval)} onChange={(value) => onUpdate({ enabled: schedule?.enabled ?? false, interval_minutes: Number(value) })} isDisabled={!editable || pending} options={intervalOptions} />
    <Button aria-label={pending ? '更新中 自动更新' : undefined} isDisabled={!editable || pending} onPress={() => onUpdate({ enabled: !(schedule?.enabled ?? false), interval_minutes: interval })}>{pending ? '更新中' : schedule?.enabled ? '关闭自动更新' : '开启自动更新'}</Button>
  </div>

  return <>
    <Card data-mobile-schedule variant="transparent" className="p-3 min-[768px]:hidden">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0"><Card.Title>自动更新信息流</Card.Title><Card.Description className="mt-1 truncate">{status}</Card.Description></div>
        <Button size="sm" variant="ghost" aria-expanded={mobileOpen} onPress={() => setMobileOpen((open) => !open)}>{mobileOpen ? '收起自动更新' : '管理自动更新'}</Button>
      </div>
      {mobileOpen && <div className="mt-4 border-t border-separator pt-4">{controls}</div>}
    </Card>
    <div data-desktop-schedule className="hidden min-[768px]:block"><AdminSection title="自动更新信息流" description="按设定周期从全部已启用订阅抓取、去重并更新信息流，不会修改订阅设置。">{controls}</AdminSection></div>
  </>
}

function Group({ id, title, description, children, forceOpen = false }: { id: string; title: string; description: string; children: React.ReactNode; forceOpen?: boolean }) {
  const [collapsed, setCollapsed] = useState(false)
  const open = forceOpen || !collapsed
  return <section aria-labelledby={id} className="grid gap-3"><div className="flex items-center justify-between gap-3"><div><h2 id={id} className="type-section-title">{title}</h2><p className="type-body mt-1 text-muted">{description}</p></div><Button size="sm" variant="ghost" aria-label={`${open ? '收起' : '展开'} ${title}`} aria-expanded={open} onPress={() => setCollapsed((value) => !value)}>{open ? '收起' : '展开'}</Button></div>{open && children}</section>
}

function SourceIssueDetails({ health, canRetry, canEdit }: { health: SourceHealthItem; canRetry: boolean; canEdit: boolean }) {
  const issue = health.last_issue
  if (!issue) return null
  const presentation = presentSourceHealthIssue(health, { canRetry, canEdit })
  return <div className="type-body grid gap-3">
    <div><span className="type-label text-muted">原因</span><p className="mt-1">{presentation.reason}</p></div>
    <div><span className="type-label text-muted">影响</span><p className="mt-1 text-muted">{presentation.impact}</p></div>
    <div><span className="type-label text-muted">建议操作</span><p className="mt-1 text-muted">{presentation.action}</p></div>
    {canEdit && <details>
      <summary className="type-meta cursor-pointer text-muted">技术详情</summary>
      <dl className="type-meta mt-2 grid gap-1 [overflow-wrap:anywhere]">
        <div><dt className="inline text-muted">阶段：</dt><dd className="inline">{issue.stage || '未知'}</dd></div>
        <div><dt className="inline text-muted">代码：</dt><dd className="inline">{issue.code || '未知'}</dd></div>
        <div><dt className="inline text-muted">可重试：</dt><dd className="inline">{issue.retryable ? '是' : '否'}</dd></div>
        <div><dt className="inline text-muted">原始信息：</dt><dd className="inline">{issue.message || '未提供'}</dd></div>
      </dl>
    </details>}
  </div>
}

function SourceHealthStatus({ health, canRetry, canEdit }: { health?: SourceHealthItem; canRetry: boolean; canEdit: boolean }) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const status = health?.status ?? 'unknown'
  const issue = health?.last_issue
  const presentation = health && issue ? presentSourceHealthIssue(health, { canRetry, canEdit }) : null
  const chip = <Chip size="sm" color={status === 'healthy' ? 'success' : status === 'failing' ? 'danger' : 'default'} variant="soft"><Chip.Label>{healthLabel[status]}</Chip.Label></Chip>

  if (!health || !issue || !presentation) return chip
  const failureCount = Math.max(health.consecutive_failures || 0, 1)
  return <>
    <Tooltip delay={250}>
      <TooltipTriggerButton
          ref={triggerRef}
          className="h-auto min-h-0 rounded-full p-0"
          aria-label={`查看 ${healthLabel[status]} 详情`}
          onClick={() => setDetailsOpen(true)}
        >{chip}</TooltipTriggerButton>
      <Tooltip.Content {...anchoredTooltipProps}>{`已连续 ${failureCount} 次失败：${presentation.reason}`}</Tooltip.Content>
    </Tooltip>
    <Modal isOpen={detailsOpen} onOpenChange={(open) => {
      setDetailsOpen(open)
      if (!open) window.requestAnimationFrame(() => triggerRef.current?.focus())
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开来源失败详情</Modal.Trigger>
      <Modal.Backdrop>
        <Modal.Container size="md">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>来源获取失败</Modal.Heading></Modal.Header>
            <Modal.Body><SourceIssueDetails health={health} canRetry={canRetry} canEdit={canEdit} /></Modal.Body>
            <Modal.Footer><Button onPress={() => setDetailsOpen(false)}>关闭</Button></Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </>
}

export function SourceCard({ source, subscription, health, editable, canEdit, canShare, fetchLabel, onFetch, onEditSubscription, onEditSource, onInspectUsage, onShare }: {
  source: CatalogSource; subscription: Subscription; health?: SourceHealthItem; editable: boolean; canEdit: boolean; fetchLabel: '提交中' | '已排队' | '获取中' | '立即获取'
  canShare: boolean; onFetch: () => void; onEditSubscription: () => void; onEditSource: () => void; onInspectUsage: () => void; onShare: () => void
}) {
  return <Card variant="secondary" className="p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><Card.Title>{source.display_name}</Card.Title><div className="mt-2 flex flex-wrap gap-2"><Chip size="sm" variant="soft"><Chip.Label>{sourceTypeLabel(source.type)}</Chip.Label></Chip><Chip size="sm" variant="soft"><Chip.Label>{sourceScopeLabel(source.scope)}</Chip.Label></Chip>{subscription.enabled && subscription.notify_on_new_items && subscription.analysis_mode !== 'personal_only' && <Chip size="sm" variant="soft"><Chip.Label>新内容通知</Chip.Label></Chip>}<SourceHealthStatus health={health} canRetry={editable} canEdit={canEdit} /></div></div></div><Card.Description className="mt-3">优先级 {subscription.priority ?? 0} · {health?.last_fetched_count ?? 0} 条最近结果 · {subscription.schedule?.enabled ? `下次 ${formatTime(subscription.schedule.next_run_at)}` : '单源自动获取已关闭'}</Card.Description><div className="mt-4 flex flex-wrap gap-2"><Button size="sm" variant="ghost" aria-label={`配置 ${source.display_name} 订阅`} onPress={onEditSubscription}>{editable ? '订阅设置' : '查看订阅'}</Button>{editable && <Button size="sm" aria-label={`${fetchLabel} ${source.display_name}`} isDisabled={fetchLabel !== '立即获取'} onPress={onFetch}><Icons.RefreshCw size={14} />{fetchLabel}</Button>}<Button size="sm" variant="ghost" aria-label={`查看 ${source.display_name} 引用人数`} onPress={onInspectUsage}><Icons.Users size={14} />查看引用</Button>{canShare && <Button size="sm" variant="ghost" aria-label={`分享 ${source.display_name}`} onPress={onShare}><Icons.Share2 size={14} />分享来源</Button>}{canEdit && <Button size="sm" variant="ghost" aria-label={`编辑 ${source.display_name} 来源`} onPress={onEditSource}>编辑来源</Button>}</div></Card>
}

export function HeroSubscriptionsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const agent = useWorkbenchAgentContext()
  const editable = canMutateSubscriptions(user)
  const isAdmin = adminRole(user.role)
  const [tab, setTab] = useState('subscriptions')
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [scopeFilter, setScopeFilter] = useState('all')
  const [healthFilter, setHealthFilter] = useState<HealthFilter>('all')
  const [editingSubscription, setEditingSubscription] = useState<{ source: CatalogSource; subscription: Subscription } | null>(null)
  const [editingSource, setEditingSource] = useState<CatalogSource | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createType, setCreateType] = useState('')
  const [usageSource, setUsageSource] = useState<CatalogSource | null>(null)
  const [shareSource, setShareSource] = useState<CatalogSource | null>(null)
  const seenTerminalJobs = useRef(new Set<string>())
  const initiatedJobs = useRef(new Map<string, { action: string; entity: string; label: string; subscriptionId: string }>())

  const sourcesQuery = useQuery({ queryKey: queryKeys.sources(user.id), queryFn: ({ signal }) => api.sources(isAdmin, signal) })
  const typesQuery = useQuery({ queryKey: queryKeys.sourceTypes(user.id), queryFn: ({ signal }) => api.sourceTypes(signal) })
  const subscriptionsQuery = useQuery({ queryKey: queryKeys.subscriptions(user.id), queryFn: ({ signal }) => api.subscriptions(signal) })
  const healthQuery = useQuery({ queryKey: queryKeys.sourceHealth(user.id), queryFn: ({ signal }) => api.sourceHealth(signal) })
  const scheduleQuery = useQuery({ queryKey: queryKeys.feedSchedule(user.id), queryFn: ({ signal }) => api.feedSchedule(signal) })
  const jobsQuery = useQuery({ queryKey: queryKeys.jobs(user.id), queryFn: ({ signal }) => api.jobs(signal), refetchInterval: (query) => query.state.data?.jobs.some((job) => job.user_id === user.id && ['queued', 'running'].includes(job.status)) ? 2000 : false })
  const configQuery = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal) })
  const secretsQuery = useQuery({ queryKey: queryKeys.secrets(user.id), queryFn: ({ signal }) => api.secrets(signal), enabled: isAdmin })

  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.sources(user.id) }), queryClient.invalidateQueries({ queryKey: queryKeys.subscriptions(user.id) }), queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }), queryClient.invalidateQueries({ queryKey: queryKeys.jobs(user.id) }), queryClient.invalidateQueries({ queryKey: ['user', user.id, 'feed'] }), queryClient.invalidateQueries({ queryKey: queryKeys.history(user.id) }),
  ])
  const mutationError = (caught: unknown) => caught instanceof ApiError || caught instanceof Error ? caught.message : '操作失败，请稍后重试。'
  const scheduleMutation = useMutation({
    mutationFn: (patch: { enabled: boolean; interval_minutes: number }) => api.updateFeedSchedule(patch),
    onMutate: () => feedback.begin('feed-schedule', 'global'),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.feedSchedule(user.id) })
      feedback.clear('feed-schedule', 'global')
      actionToast.success('自动更新设置已保存')
    },
    onError: (caught) => {
      feedback.clear('feed-schedule', 'global')
      actionToast.danger('自动更新设置保存失败', { description: mutationError(caught) })
    },
  })
  const subscribeMutation = useMutation({ mutationFn: (source: CatalogSource) => api.subscribe(source.id), onMutate: (source) => feedback.begin('subscribe', source.id), onSuccess: async (result, source) => { await invalidate(); feedback.clear('subscribe', source.id); const reused = result.subscription.reused_item_count ?? 0; actionToast.success(`${source.display_name} 订阅成功`, { description: reused > 0 ? `已复用 ${reused} 条已有内容，无需重复获取。` : undefined }) }, onError: (caught, source) => { feedback.clear('subscribe', source.id); actionToast.danger(`${source.display_name} 订阅失败`, { description: mutationError(caught) }) } })
  const unsubscribeMutation = useMutation({ mutationFn: ({ subscription }: { source: CatalogSource; subscription: Subscription }) => api.unsubscribe(subscription.id), onMutate: ({ source }) => feedback.begin('unsubscribe', source.id), onSuccess: async (_result, { source }) => { await invalidate(); feedback.clear('unsubscribe', source.id); actionToast.success(`${source.display_name} 已取消订阅`, { description: '其他成员的订阅和来源不会受到影响。' }) }, onError: (caught, { source }) => { feedback.clear('unsubscribe', source.id); actionToast.danger(`${source.display_name} 取消订阅失败`, { description: mutationError(caught) }) } })
  const usageMutation = useMutation<SourceUsage, Error, CatalogSource>({ mutationFn: (source) => api.sourceUsage(source.id) })
  const shareMutation = useMutation({
    mutationFn: ({ source, scope }: { source: CatalogSource; scope: 'workspace' | 'public' }) => api.shareSource(source.id, scope),
    onSuccess: async (result) => {
      await invalidate()
      setShareSource(null)
      actionToast.success('来源已分享', { description: result.notice })
    },
    onError: (caught) => actionToast.danger('来源分享失败', { description: mutationError(caught) }),
  })
  const retryMutation = useMutation({
    mutationFn: (job: Job) => api.retryJob(job.id),
    onMutate: (job) => feedback.begin('retry-job', job.id),
    onSuccess: async (_result, job) => {
      await invalidate()
      feedback.clear('retry-job', job.id)
      actionToast.success('重试任务已提交')
    },
    onError: (caught, job) => {
      feedback.clear('retry-job', job.id)
      actionToast.danger('重试任务提交失败', { description: mutationError(caught) })
    },
  })
  const retryJob = retryMutation.mutate
  const fetchMutation = useMutation({
    mutationFn: async ({ source, subscription }: { source: CatalogSource; subscription: Subscription }) => {
      const schedule = await scheduleQuery.refetch()
      if (schedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。')
      return api.createSourceFetch(source.id, subscription.id)
    },
    onMutate: ({ source }) => feedback.begin('source-fetch', source.id),
    onSuccess: (job, { source, subscription }) => { initiatedJobs.current.set(job.id, { action: 'source-fetch', entity: source.id, label: source.display_name, subscriptionId: subscription.id }); feedback.advance('source-fetch', source.id, 'queued'); queryClient.setQueryData(queryKeys.jobs(user.id), (previous: { jobs: Job[] } | undefined) => ({ jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)] })); return invalidate() },
    onError: (caught, { source }) => {
      feedback.clear('source-fetch', source.id)
      actionToast.danger(`${source.display_name} 获取失败`, { description: mutationError(caught) })
    },
  })

  const sources = useMemo(() => sourcesQuery.data?.sources ?? [], [sourcesQuery.data])
  const definitions = typesQuery.data?.source_types ?? []
  const subscriptions = subscriptionsQuery.data?.subscriptions ?? []
  const taxonomy: TaxonomyOptions = configQuery.data?.taxonomy ?? { channels: [], topics: Array.isArray(configQuery.data?.config.tags) ? configQuery.data.config.tags.filter((topic): topic is string => typeof topic === 'string') : [] }
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources])
  const healthMap = useMemo(() => new Map((healthQuery.data?.items ?? []).map((health) => [health.subscription_id, health])), [healthQuery.data])
  const normalized = search.trim().toLocaleLowerCase()
  const matchesSource = (source: CatalogSource) => (typeFilter === 'all' || source.type === typeFilter) && (scopeFilter === 'all' || (scopeFilter === 'public' ? isPublicSubscriptionScope(source.scope) : source.scope === 'private')) && (!normalized || [source.display_name, source.description, source.default_channel, ...(source.default_topics ?? [])].some((value) => String(value ?? '').toLocaleLowerCase().includes(normalized)))
  const entries = subscriptions.filter((subscription) => healthMatches(healthMap.get(subscription.id), healthFilter)).map((subscription): SubscriptionEntry => { const source = sourceForSubscription(subscription, sourceMap.get(subscription.source_id)); return { source, subscription, health: healthMap.get(subscription.id), channel: effectiveSubscriptionChannel(subscription, source) } }).filter(({ source }) => matchesSource(source))
  const filteredSources = sources.filter(matchesSource)
  const subscriptionGroups = groupSourcesByChannel(entries, (entry) => entry.channel, taxonomy.channels)
  const sourceGroups = groupSourcesByChannel(filteredSources, (source) => source.default_channel, taxonomy.channels)
  const activeDefinition = definitions.find((definition) => definition.type === (editingSource?.type || createType))
  const loadError = sourcesQuery.error || typesQuery.error || subscriptionsQuery.error || healthQuery.error || scheduleQuery.error || jobsQuery.error || configQuery.error
  const loading = sourcesQuery.isLoading || typesQuery.isLoading || subscriptionsQuery.isLoading || healthQuery.isLoading || configQuery.isLoading
  const schedulePending = feedback.isPending('feed-schedule', 'global')
  useEffect(() => {
    const jobs = jobsQuery.data?.jobs ?? []
    for (const job of jobs.filter((entry) => entry.user_id === user.id && entry.job_type === 'source_fetch' && ['succeeded', 'partial', 'failed', 'cancelled'].includes(entry.status))) {
      const key = `${job.id}:${job.status}`
      if (seenTerminalJobs.current.has(key)) continue
      seenTerminalJobs.current.add(key)
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs(user.id) })
      void queryClient.invalidateQueries({ queryKey: ['user', user.id, 'feed'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.history(user.id) })
      const initiated = initiatedJobs.current.get(job.id)
      if (!initiated) continue
      initiatedJobs.current.delete(job.id)
      const count = Number((job.result ?? job.result_json)?.item_count ?? 0)
      if (job.status === 'succeeded') {
        actionToast.success(`${initiated.label} 获取完成`, { description: `共 ${count} 条。` })
      } else if (job.status === 'partial') {
        actionToast.warning(`${initiated.label} 部分完成`, {
          description: '请查看运行记录。',
          onRetry: job.retryable ? () => retryJob(job) : undefined,
        })
      } else {
        const message = job.status === 'cancelled' ? '任务已取消。' : job.error_message || '请稍后重试。'
        const show = job.status === 'cancelled' ? actionToast.warning : actionToast.danger
        show(`${initiated.label} 获取${job.status === 'cancelled' ? '已取消' : '失败'}`, {
          description: message,
          onRetry: job.retryable ? () => retryJob(job) : undefined,
        })
      }
      feedback.clear(initiated.action, initiated.entity)
    }
    for (const job of jobs.filter((entry) => initiatedJobs.current.has(entry.id))) {
      const initiated = initiatedJobs.current.get(job.id)!
      if (job.status === 'running' && feedback.phase(initiated.action, initiated.entity) !== 'running') {
        feedback.advance(initiated.action, initiated.entity, 'running')
      }
    }
  }, [feedback, jobsQuery.data, queryClient, retryJob, user.id])

  async function createJob(kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) {
    if (kind === 'test') await api.createSourceTest(sourceId, subscriptionId)
    else {
      const schedule = await scheduleQuery.refetch()
      if (schedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。')
      const job = await api.createSourceFetch(sourceId, subscriptionId)
      const source = sourceMap.get(sourceId)
      initiatedJobs.current.set(job.id, { action: 'source-fetch', entity: sourceId, label: source?.display_name ?? '来源', subscriptionId })
      feedback.advance('source-fetch', sourceId, 'queued')
    }
    await invalidate()
  }

  function inspectUsage(source: CatalogSource) {
    usageMutation.reset()
    setUsageSource(source)
    usageMutation.mutate(source)
  }

  function beginShare(source: CatalogSource) {
    setShareSource(source)
  }

  function toggleJobContext(job: Job, title: string, sourceName: string | undefined, statusLabel: string, detail: string) {
    const articleId = `job:${job.id}`
    const alreadySelected = agent.draft.items.some((item) => item.articleId === articleId)
    agent.toggleItem({
      articleId,
      resourceType: 'job',
      jobId: job.id,
      title,
      ...(sourceName ? { sourceName } : {}),
      ...(job.finished_at || job.created_at ? { publishedAt: job.finished_at || job.created_at || undefined } : {}),
      statusLabel,
      detail,
    })
    if (!alreadySelected) {
      agent.openComposer()
    }
  }

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description="选择要持续关注的来源，并查看每次更新发生了什么。" actions={editable && <Button size="sm" onPress={() => setCreateOpen(true)}><Icons.Plus size={15} />新增来源</Button>} />
    {loadError && <HeroNotice title="订阅数据加载失败，请刷新页面后重试。" />}
    <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(String(key))}>
      <Tabs.List aria-label="订阅与来源页面" className="grid w-full grid-cols-3 min-[768px]:flex min-[768px]:w-fit"><Tabs.Tab id="subscriptions" className="min-w-0 justify-center px-2 min-[768px]:px-3">我的订阅<Tabs.Indicator /></Tabs.Tab><Tabs.Tab id="library" className="min-w-0 justify-center px-2 min-[768px]:px-3">来源库<Tabs.Indicator /></Tabs.Tab><Tabs.Tab id="jobs" className="min-w-0 justify-center px-2 min-[768px]:px-3">运行记录<Tabs.Indicator /></Tabs.Tab></Tabs.List>
      <Tabs.Panel id="subscriptions" className="grid gap-5 pt-5">
        <FeedScheduleControls schedule={scheduleQuery.data} editable={editable} pending={schedulePending} onUpdate={(patch) => scheduleMutation.mutate(patch)} />
        <SourceFilters search={search} onSearchChange={setSearch} definitions={definitions} typeFilter={typeFilter} onTypeChange={setTypeFilter} scopeFilter={scopeFilter} onScopeChange={setScopeFilter} healthFilter={healthFilter} onHealthChange={setHealthFilter} includeHealth />
        {loading && <LoadingState label="正在读取订阅" rows={1} />}{!loading && subscriptionGroups.map((group) => <Group key={group.channel} id={`subscription-${group.channel}`} title={group.channel} description="按个人频道覆盖和来源默认频道归类。" forceOpen={Boolean(normalized)}><div className="grid gap-3 min-[680px]:grid-cols-2 min-[1180px]:grid-cols-3">{group.items.map(({ source, subscription, health }) => { const activeJob = (jobsQuery.data?.jobs ?? []).find((job) => job.job_type === 'source_fetch' && job.subscription_id === subscription.id && ['queued', 'running'].includes(job.status)); const phase = feedback.phase('source-fetch', source.id); const fetchLabel = phase === 'pending' ? '提交中' : activeJob?.status === 'running' || phase === 'running' ? '获取中' : activeJob?.status === 'queued' || phase === 'queued' ? '已排队' : '立即获取'; return <SourceCard key={subscription.id} source={source} subscription={subscription} health={health} editable={editable} canEdit={Boolean(definitions.find((definition) => definition.type === source.type)) && canEditSource(user, source)} canShare={editable && source.scope === 'private' && source.owner_user_id === user.id} fetchLabel={fetchLabel} onFetch={() => fetchMutation.mutate({ source, subscription })} onEditSubscription={() => setEditingSubscription({ source, subscription })} onEditSource={() => setEditingSource(source)} onInspectUsage={() => inspectUsage(source)} onShare={() => beginShare(source)} /> })}</div></Group>)}{!loading && !entries.length && <Card variant="transparent" className="p-6 text-center"><Card.Title>没有匹配的订阅</Card.Title><Card.Description className="mt-1">调整筛选，或前往来源库选择要关注的来源。</Card.Description></Card>}
      </Tabs.Panel>
      <Tabs.Panel id="library" className="grid gap-5 pt-5">
        <SourceFilters search={search} onSearchChange={setSearch} definitions={definitions} typeFilter={typeFilter} onTypeChange={setTypeFilter} scopeFilter={scopeFilter} onScopeChange={setScopeFilter} healthFilter={healthFilter} onHealthChange={setHealthFilter} includeHealth={false} />
        {sourceGroups.map((group) => <Group key={group.channel} id={`library-${group.channel}`} title={group.channel} description="按来源默认频道归类；范围与类型作为标签。" forceOpen={Boolean(normalized)}><div className="grid gap-3 min-[680px]:grid-cols-2 min-[1180px]:grid-cols-3">{group.items.map((source) => { const subscribed = isSourceSubscribed(source.id, subscriptions); const subscription = subscriptions.find((item) => item.source_id === source.id); const subscribePending = feedback.isPending('subscribe', source.id); const unsubscribePending = feedback.isPending('unsubscribe', source.id); return <Card key={source.id} variant="secondary" className="p-4"><Card.Title>{source.display_name}</Card.Title><Card.Description className="mt-2">{source.description || '该来源尚未填写说明。'}</Card.Description><div className="mt-2 flex flex-wrap gap-2"><Chip size="sm" variant="soft"><Chip.Label>{sourceTypeLabel(source.type)}</Chip.Label></Chip><Chip size="sm" variant="soft"><Chip.Label>{sourceScopeLabel(source.scope)}</Chip.Label></Chip></div><div className="mt-4 flex flex-wrap gap-2">{subscribed ? <Button size="sm" variant="ghost" aria-label={`${unsubscribePending ? '取消中' : '取消订阅'} ${source.display_name}`} isDisabled={!editable || !subscription || unsubscribePending} onPress={() => subscription && unsubscribeMutation.mutate({ source, subscription })}>{unsubscribePending ? '取消中' : '取消订阅'}</Button> : <Button size="sm" aria-label={`${subscribePending ? '订阅中' : '订阅'} ${source.display_name}`} isDisabled={!editable || subscribePending} onPress={() => subscribeMutation.mutate(source)}>{subscribePending ? '订阅中' : '订阅'}</Button>}<Button size="sm" variant="ghost" aria-label={`查看 ${source.display_name} 引用人数`} onPress={() => inspectUsage(source)}><Icons.Users size={14} />查看引用</Button>{editable && source.scope === 'private' && source.owner_user_id === user.id && <Button size="sm" variant="ghost" aria-label={`分享 ${source.display_name}`} onPress={() => beginShare(source)}><Icons.Share2 size={14} />分享来源</Button>}{canEditSource(user, source) && <Button size="sm" variant="ghost" onPress={() => setEditingSource(source)}>编辑来源</Button>}</div></Card> })}</div></Group>)}{!loading && !filteredSources.length && <Card variant="transparent" className="p-6 text-center"><Card.Title>{sources.length ? '没有匹配的来源' : '来源库还是空的'}</Card.Title></Card>}
      </Tabs.Panel>
      <Tabs.Panel id="jobs" className="grid gap-3 pt-5">
        <p className="type-body text-muted">任务类型和状态使用中文展示；可加入 OpenClaw 分析，仅管理员可展开技术详情。</p>
        {(jobsQuery.data?.jobs ?? []).filter((job) => job.user_id === user.id).slice(0, 20).map((job) => {
          const presented = presentJob(job, sourceMap)
          const feedActivity = job.job_type === 'user_feed_refresh' ? describeFeedJob(job, scheduleQuery.data?.worker_status) : undefined
          const retryPending = feedback.isPending('retry-job', job.id)
          const contextId = `job:${job.id}`
          const inContext = agent.draft.items.some((item) => item.articleId === contextId)
          const resultDetail = feedActivity?.message || presented.detail || presented.resultLabel
          return <Card key={job.id} variant="secondary" className="p-4">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Card.Title className="min-w-0 flex-1">{presented.title}</Card.Title>
              <Chip size="sm" variant="soft"><Chip.Label>{presented.statusLabel}</Chip.Label></Chip>
              <Tooltip delay={600}>
                <TooltipTriggerButton
                  data-context-state={inContext ? 'selected' : 'idle'}
                  className="size-8 shrink-0 rounded-lg bg-transparent text-muted hover:bg-default hover:text-foreground data-[context-state=selected]:bg-accent/15 data-[context-state=selected]:text-accent data-[context-state=selected]:ring-1 data-[context-state=selected]:ring-accent/45 data-[context-state=selected]:hover:bg-accent/25 data-[context-state=selected]:hover:text-accent"
                  aria-pressed={inContext}
                  aria-label={`${inContext ? '移出' : '加入'} OpenClaw 上下文：${presented.title}`}
                  onClick={() => toggleJobContext(job, presented.title, presented.sourceName, presented.statusLabel, resultDetail)}
                ><Icons.Sparkles size={15} fill="currentColor" aria-hidden="true" /></TooltipTriggerButton>
                <Tooltip.Content {...anchoredTooltipProps}>{inContext ? '从 OpenClaw 上下文移除' : '加入 OpenClaw 分析'}</Tooltip.Content>
              </Tooltip>
            </div>
            <Card.Description className="type-body mt-2 grid gap-1">
              <span>{presented.sourceName ? `${presented.sourceName} · ` : ''}{feedActivity?.message || presented.resultLabel}</span>
              <span>{`创建：${formatTime(job.created_at)}`}</span>
              <span>{`完成：${job.finished_at ? formatTime(job.finished_at) : '尚未完成'}`}</span>
            </Card.Description>
            {presented.detail && <p className="type-body mt-2 text-muted">{presented.detail}</p>}
            {isAdmin && <details className="mt-3"><summary className="type-meta cursor-pointer text-muted">技术详情</summary><pre className="type-meta mt-2 overflow-wrap-anywhere whitespace-pre-wrap">{JSON.stringify({ id: job.id, job_type: job.job_type, status: job.status, error_code: job.error_code }, null, 2)}</pre></details>}
            {!['queued', 'running'].includes(job.status) && <HeroResponseSchemaDetails job={job} sourceNames={sourceMap} />}
            {editable && job.retryable && <Button size="sm" variant="ghost" className="mt-3" aria-label={retryPending ? `重试中 ${presented.title}` : undefined} isDisabled={retryPending} onPress={() => retryMutation.mutate(job)}>{retryPending ? '重试中' : '重试'}</Button>}
          </Card>
        })}
        {!jobsQuery.isLoading && !(jobsQuery.data?.jobs ?? []).some((job) => job.user_id === user.id) && <Card variant="transparent" className="p-6 text-center"><Card.Title>还没有运行记录</Card.Title></Card>}
      </Tabs.Panel>
    </Tabs>
  </PageFrame>

  <HeroDialog isOpen={Boolean(editingSubscription)} onOpenChange={(open) => !open && setEditingSubscription(null)} title={editingSubscription ? `${editingSubscription.source.display_name} · 订阅设置` : '订阅设置'}>{editingSubscription && <SubscriptionForm {...editingSubscription} readonly={!editable} taxonomy={taxonomy} onDone={() => { void invalidate(); setEditingSubscription(null) }} onJob={createJob} />}</HeroDialog>
  <HeroDialog isOpen={Boolean(editingSource)} onOpenChange={(open) => !open && setEditingSource(null)} title={editingSource ? `${editingSource.display_name} · 来源设置` : '来源设置'}>{editingSource && activeDefinition && <SourceForm definition={activeDefinition} source={editingSource} secrets={secretsQuery.data?.secrets ?? []} allowSecret={isAdmin && sourceUsesSecret(activeDefinition)} scopes={sourceScopesForUser(user)} taxonomy={taxonomy} submitLabel="保存来源" onSubmit={async (payload) => { await api.updateSource(editingSource.id, payload); await invalidate(); setEditingSource(null); actionToast.success('来源设置已保存') }} />}</HeroDialog>
  <HeroDialog isOpen={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (!open) setCreateType('') }} title="新增来源"><div className="grid gap-4"><HeroSelect label="来源类型" value={createType} onChange={setCreateType} options={[{ id: '', label: '请选择来源类型' }, ...definitions.map((definition: SourceTypeDefinition) => ({ id: definition.type, label: definition.label || definition.display_name || sourceTypeLabel(definition.type) }))]} />{activeDefinition && <SourceForm key={activeDefinition.type} definition={activeDefinition} secrets={secretsQuery.data?.secrets ?? []} allowSecret={isAdmin && sourceUsesSecret(activeDefinition)} scopes={sourceScopesForUser(user)} taxonomy={taxonomy} submitLabel="创建并订阅" onSubmit={async (payload) => { const created = await api.createSource(payload); try { const result = await api.subscribe(created.id); const reused = result.subscription.reused_item_count ?? 0; actionToast.success('来源已创建并订阅', { description: reused > 0 ? `已复用 ${reused} 条已有内容。` : undefined }) } catch (caught) { actionToast.danger('来源已创建，但订阅失败', { description: `${mutationError(caught)} 可在来源库中重试订阅。` }) } await invalidate(); setCreateOpen(false); setCreateType('') }} />}</div></HeroDialog>
  <HeroDialog isOpen={Boolean(usageSource)} onOpenChange={(open) => !open && setUsageSource(null)} title={usageSource ? `${usageSource.display_name} · 引用情况` : '来源引用情况'}>
    {usageMutation.isPending && <LoadingState label="正在统计引用" rows={1} />}
    {usageMutation.isError && <HeroNotice title="引用人数读取失败">{mutationError(usageMutation.error)}</HeroNotice>}
    {usageMutation.data && <div className="grid grid-cols-2 gap-3"><Card variant="secondary" className="p-4"><Card.Description>全部订阅用户</Card.Description><Card.Title className="mt-2">{usageMutation.data.subscriber_count}</Card.Title></Card><Card variant="secondary" className="p-4"><Card.Description>当前已启用</Card.Description><Card.Title className="mt-2">{usageMutation.data.enabled_subscriber_count}</Card.Title></Card></div>}
    <p className="type-body mt-3 text-muted">此数据只在你打开时计算，不会常驻刷新。</p>
  </HeroDialog>
  <HeroDialog isOpen={Boolean(shareSource)} onOpenChange={(open) => !open && setShareSource(null)} title={shareSource ? `分享 ${shareSource.display_name}` : '分享来源'}>
    <div className="grid gap-4">
      <HeroNotice title="分享后管理权将发生变化" status="warning">来源订阅地址和管理权会转交给工作区超级用户与管理员。你之后取消订阅只影响自己，不会删除其他成员正在使用的来源。</HeroNotice>
      <p className="type-body text-muted">分享后将成为公共订阅，所有成员都可以发现并订阅。</p>
      <Button isDisabled={shareMutation.isPending} onPress={() => shareSource && shareMutation.mutate({ source: shareSource, scope: 'public' })}>{shareMutation.isPending ? '分享中…' : '确认公开并转交管理权'}</Button>
    </div>
  </HeroDialog>
  </div>
}
