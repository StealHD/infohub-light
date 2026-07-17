import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { CatalogSource, Job, SourceHealthItem, SourceTypeDefinition, Subscription, TaxonomyOptions } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  Button,
  Card,
  Chip,
  Icons,
  SearchField,
  Skeleton,
  Tabs,
} from '../../design-system'
import { describeFeedJob } from '../jobs/jobModel'
import {
  canEditSource,
  canMutateSubscriptions,
  effectiveSubscriptionChannel,
  groupSourcesByChannel,
  healthMatches,
  isSourceSubscribed,
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

function Group({ id, title, description, children, forceOpen = false }: { id: string; title: string; description: string; children: React.ReactNode; forceOpen?: boolean }) {
  const [collapsed, setCollapsed] = useState(false)
  const open = forceOpen || !collapsed
  return <section aria-labelledby={id} className="grid gap-3"><div className="flex items-center justify-between gap-3"><div><h2 id={id} className="text-lg font-semibold">{title}</h2><p className="mt-1 text-sm text-muted">{description}</p></div><Button size="sm" variant="ghost" aria-label={`${open ? '收起' : '展开'} ${title}`} aria-expanded={open} onPress={() => setCollapsed((value) => !value)}>{open ? '收起' : '展开'}</Button></div>{open && children}</section>
}

function SourceCard({ source, subscription, health, editable, canEdit, busy, onFetch, onEditSubscription, onEditSource }: {
  source: CatalogSource; subscription: Subscription; health?: SourceHealthItem; editable: boolean; canEdit: boolean; busy: boolean
  onFetch: () => void; onEditSubscription: () => void; onEditSource: () => void
}) {
  return <Card variant="secondary" className="p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><Card.Title>{source.display_name}</Card.Title><div className="mt-2 flex flex-wrap gap-2"><Chip size="sm" variant="soft"><Chip.Label>{sourceTypeLabel(source.type)}</Chip.Label></Chip><Chip size="sm" variant="soft"><Chip.Label>{sourceScopeLabel(source.scope)}</Chip.Label></Chip><Chip size="sm" color={health?.status === 'healthy' ? 'success' : health?.status === 'failing' ? 'danger' : 'default'} variant="soft"><Chip.Label>{healthLabel[health?.status ?? 'unknown']}</Chip.Label></Chip></div></div></div><Card.Description className="mt-3">优先级 {subscription.priority ?? 0} · {health?.last_fetched_count ?? 0} 条最近结果 · {subscription.schedule?.enabled ? `下次 ${formatTime(subscription.schedule.next_run_at)}` : '单源自动获取已关闭'}</Card.Description>{health?.last_issue && <div className="mt-3"><HeroNotice title={health.last_issue.message || '最近一次抓取出现问题。'} status="warning" role="status" /></div>}<div className="mt-4 flex flex-wrap gap-2"><Button size="sm" variant="ghost" aria-label={`配置 ${source.display_name} 订阅`} onPress={onEditSubscription}>{editable ? '订阅设置' : '查看订阅'}</Button>{editable && <Button size="sm" aria-label={`${busy ? '获取中' : '立即获取'} ${source.display_name}`} isDisabled={busy} onPress={onFetch}><Icons.RefreshCw size={14} />{busy ? '获取中' : '立即获取'}</Button>}{canEdit && <Button size="sm" variant="ghost" aria-label={`编辑 ${source.display_name} 来源`} onPress={onEditSource}>编辑来源</Button>}</div></Card>
}

export function HeroSubscriptionsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
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
  const [pageError, setPageError] = useState('')
  const initiated = useRef(new Set<string>())

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
  const scheduleMutation = useMutation({ mutationFn: (patch: { enabled: boolean; interval_minutes: number }) => api.updateFeedSchedule(patch), onMutate: () => feedback.begin('feed-schedule', 'global'), onSuccess: () => { feedback.succeed('feed-schedule', 'global'); return queryClient.invalidateQueries({ queryKey: queryKeys.feedSchedule(user.id) }) }, onError: (caught) => feedback.fail('feed-schedule', 'global', mutationError(caught)) })
  const subscribeMutation = useMutation({ mutationFn: (sourceId: string) => api.subscribe(sourceId), onMutate: (id) => feedback.begin('subscribe', id), onSuccess: (_result, id) => { feedback.succeed('subscribe', id); return invalidate() }, onError: (caught, id) => feedback.fail('subscribe', id, mutationError(caught)) })
  const unsubscribeMutation = useMutation({ mutationFn: (id: string) => api.unsubscribe(id), onMutate: (id) => feedback.begin('unsubscribe', id), onSuccess: (_result, id) => { feedback.succeed('unsubscribe', id); return invalidate() }, onError: (caught, id) => feedback.fail('unsubscribe', id, mutationError(caught)) })
  const retryMutation = useMutation({ mutationFn: (id: string) => api.retryJob(id), onSuccess: () => invalidate() })
  const fetchMutation = useMutation({
    mutationFn: async ({ source, subscription }: { source: CatalogSource; subscription: Subscription }) => {
      const schedule = await scheduleQuery.refetch()
      if (schedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。')
      return api.createSourceFetch(source.id, subscription.id)
    },
    onMutate: ({ source }) => { setPageError(''); feedback.begin('source-fetch', source.id) },
    onSuccess: (job, { source }) => { initiated.current.add(job.id); feedback.advance('source-fetch', source.id, 'queued'); queryClient.setQueryData(queryKeys.jobs(user.id), (previous: { jobs: Job[] } | undefined) => ({ jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)] })); return invalidate() },
    onError: (caught, { source }) => { const message = mutationError(caught); setPageError(message); feedback.fail('source-fetch', source.id, message) },
  })

  const sources = useMemo(() => sourcesQuery.data?.sources ?? [], [sourcesQuery.data])
  const definitions = typesQuery.data?.source_types ?? []
  const subscriptions = subscriptionsQuery.data?.subscriptions ?? []
  const taxonomy: TaxonomyOptions = configQuery.data?.taxonomy ?? { channels: [], topics: Array.isArray(configQuery.data?.config.tags) ? configQuery.data.config.tags.filter((topic): topic is string => typeof topic === 'string') : [] }
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources])
  const healthMap = useMemo(() => new Map((healthQuery.data?.items ?? []).map((health) => [health.subscription_id, health])), [healthQuery.data])
  const normalized = search.trim().toLocaleLowerCase()
  const matchesSource = (source: CatalogSource) => (typeFilter === 'all' || source.type === typeFilter) && (scopeFilter === 'all' || source.scope === scopeFilter) && (!normalized || [source.display_name, source.description, source.default_channel, ...(source.default_topics ?? [])].some((value) => String(value ?? '').toLocaleLowerCase().includes(normalized)))
  const entries = subscriptions.filter((subscription) => healthMatches(healthMap.get(subscription.id), healthFilter)).map((subscription): SubscriptionEntry => { const source = sourceForSubscription(subscription, sourceMap.get(subscription.source_id)); return { source, subscription, health: healthMap.get(subscription.id), channel: effectiveSubscriptionChannel(subscription, source) } }).filter(({ source }) => matchesSource(source))
  const filteredSources = sources.filter(matchesSource)
  const subscriptionGroups = groupSourcesByChannel(entries, (entry) => entry.channel, taxonomy.channels)
  const sourceGroups = groupSourcesByChannel(filteredSources, (source) => source.default_channel, taxonomy.channels)
  const activeDefinition = definitions.find((definition) => definition.type === (editingSource?.type || createType))
  const loadError = sourcesQuery.error || typesQuery.error || subscriptionsQuery.error || healthQuery.error || scheduleQuery.error || jobsQuery.error || configQuery.error
  const loading = sourcesQuery.isLoading || typesQuery.isLoading || subscriptionsQuery.isLoading || healthQuery.isLoading || configQuery.isLoading

  async function createJob(kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) {
    if (kind === 'test') await api.createSourceTest(sourceId, subscriptionId)
    else { const schedule = await scheduleQuery.refetch(); if (schedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。'); await api.createSourceFetch(sourceId, subscriptionId) }
    await invalidate()
  }

  return <div className="h-full overflow-y-auto"><div className="mx-auto grid w-full max-w-[1440px] gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader title="订阅与来源" description="选择要持续关注的来源，并查看每次更新发生了什么。" actions={editable && <Button size="sm" onPress={() => setCreateOpen(true)}><Icons.Plus size={15} />新增来源</Button>} />
    {loadError && <HeroNotice title="订阅数据加载失败，请刷新页面后重试。" />}
    {pageError && <HeroNotice title={pageError} />}
    <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(String(key))}>
      <Tabs.List aria-label="订阅与来源页面"><Tabs.Tab id="subscriptions">我的订阅<Tabs.Indicator /></Tabs.Tab><Tabs.Tab id="library">来源库<Tabs.Indicator /></Tabs.Tab><Tabs.Tab id="jobs">运行记录<Tabs.Indicator /></Tabs.Tab></Tabs.List>
      <Tabs.Panel id="subscriptions" className="grid gap-5 pt-5">
        <AdminSection title="自动更新信息流" description="按设定周期从全部已启用订阅抓取、去重并更新信息流，不会修改订阅设置。"><div className="flex flex-col gap-3 min-[720px]:flex-row min-[720px]:items-end"><div className="flex-1 text-sm text-muted">{scheduleQuery.data?.enabled ? `下次计划：${formatTime(scheduleQuery.data.next_run_at)}` : '自动更新当前已关闭。'} · {scheduleQuery.data?.worker_status === 'ready' ? '后台服务正常' : '后台服务不可用'}</div><HeroSelect label="更新周期" value={String(scheduleQuery.data?.interval_minutes ?? 360)} onChange={(value) => scheduleMutation.mutate({ enabled: scheduleQuery.data?.enabled ?? false, interval_minutes: Number(value) })} isDisabled={!editable} options={(scheduleQuery.data?.allowed_intervals ?? [60, 180, 360, 720, 1440]).map((value) => ({ id: String(value), label: value < 60 ? `每 ${value} 分钟` : `每 ${value / 60} 小时` }))} /><Button isDisabled={!editable || scheduleMutation.isPending} onPress={() => scheduleMutation.mutate({ enabled: !(scheduleQuery.data?.enabled ?? false), interval_minutes: scheduleQuery.data?.interval_minutes ?? 360 })}>{scheduleQuery.data?.enabled ? '关闭自动更新' : '开启自动更新'}</Button></div></AdminSection>
        <div className="grid gap-3 min-[760px]:grid-cols-4"><SearchField aria-label="搜索来源" value={search} onChange={setSearch} fullWidth><SearchField.Group><SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon><SearchField.Input placeholder="搜索来源" /><SearchField.ClearButton /></SearchField.Group></SearchField><HeroSelect label="来源类型" value={typeFilter} onChange={setTypeFilter} options={[{ id: 'all', label: '全部类型' }, ...definitions.map((definition) => ({ id: definition.type, label: definition.label || sourceTypeLabel(definition.type) }))]} /><HeroSelect label="健康状态" value={healthFilter} onChange={(value) => setHealthFilter(value as HealthFilter)} options={[{ id: 'all', label: '全部健康状态' }, { id: 'healthy', label: '正常' }, { id: 'degraded', label: '需关注' }, { id: 'failing', label: '连续失败' }, { id: 'unknown', label: '尚未抓取' }]} /><HeroSelect label="可见范围" value={scopeFilter} onChange={setScopeFilter} options={[{ id: 'all', label: '全部范围' }, { id: 'public', label: '公共来源' }, { id: 'workspace', label: '团队来源' }, { id: 'private', label: '我的私有来源' }]} /></div>
        {loading && <Skeleton className="h-40 rounded-2xl" />}{!loading && subscriptionGroups.map((group) => <Group key={group.channel} id={`subscription-${group.channel}`} title={group.channel} description="按个人频道覆盖和来源默认频道归类。" forceOpen={Boolean(normalized)}><div className="grid gap-3 min-[680px]:grid-cols-2 min-[1180px]:grid-cols-3">{group.items.map(({ source, subscription, health }) => { const activeJob = (jobsQuery.data?.jobs ?? []).find((job) => job.job_type === 'source_fetch' && job.subscription_id === subscription.id && ['queued', 'running'].includes(job.status)); const busy = Boolean(activeJob) || ['pending', 'queued', 'running'].includes(feedback.phase('source-fetch', source.id) ?? ''); return <SourceCard key={subscription.id} source={source} subscription={subscription} health={health} editable={editable} canEdit={Boolean(definitions.find((definition) => definition.type === source.type)) && canEditSource(user, source)} busy={busy} onFetch={() => fetchMutation.mutate({ source, subscription })} onEditSubscription={() => setEditingSubscription({ source, subscription })} onEditSource={() => setEditingSource(source)} /> })}</div></Group>)}{!loading && !entries.length && <Card variant="transparent" className="p-6 text-center"><Card.Title>没有匹配的订阅</Card.Title><Card.Description className="mt-1">调整筛选，或前往来源库选择要关注的来源。</Card.Description></Card>}
      </Tabs.Panel>
      <Tabs.Panel id="library" className="grid gap-5 pt-5">
        <div className="grid gap-3 min-[760px]:grid-cols-3"><SearchField aria-label="搜索来源" value={search} onChange={setSearch} fullWidth><SearchField.Group><SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon><SearchField.Input placeholder="搜索来源" /><SearchField.ClearButton /></SearchField.Group></SearchField><HeroSelect label="来源类型" value={typeFilter} onChange={setTypeFilter} options={[{ id: 'all', label: '全部类型' }, ...definitions.map((definition) => ({ id: definition.type, label: definition.label || sourceTypeLabel(definition.type) }))]} /><HeroSelect label="可见范围" value={scopeFilter} onChange={setScopeFilter} options={[{ id: 'all', label: '全部范围' }, { id: 'public', label: '公共来源' }, { id: 'workspace', label: '团队来源' }, { id: 'private', label: '我的私有来源' }]} /></div>
        {sourceGroups.map((group) => <Group key={group.channel} id={`library-${group.channel}`} title={group.channel} description="按来源默认频道归类；范围与类型作为标签。" forceOpen={Boolean(normalized)}><div className="grid gap-3 min-[680px]:grid-cols-2 min-[1180px]:grid-cols-3">{group.items.map((source) => { const subscribed = isSourceSubscribed(source.id, subscriptions); const subscription = subscriptions.find((item) => item.source_id === source.id); return <Card key={source.id} variant="secondary" className="p-4"><Card.Title>{source.display_name}</Card.Title><Card.Description className="mt-2">{source.description || '该来源尚未填写说明。'}</Card.Description><div className="mt-2 flex gap-2"><Chip size="sm" variant="soft"><Chip.Label>{sourceTypeLabel(source.type)}</Chip.Label></Chip><Chip size="sm" variant="soft"><Chip.Label>{sourceScopeLabel(source.scope)}</Chip.Label></Chip></div><div className="mt-4 flex gap-2">{subscribed ? <Button size="sm" variant="ghost" isDisabled={!editable || !subscription} onPress={() => subscription && unsubscribeMutation.mutate(subscription.id)}>取消订阅</Button> : <Button size="sm" isDisabled={!editable} onPress={() => subscribeMutation.mutate(source.id)}>订阅</Button>}{canEditSource(user, source) && <Button size="sm" variant="ghost" onPress={() => setEditingSource(source)}>编辑来源</Button>}</div></Card> })}</div></Group>)}{!loading && !filteredSources.length && <Card variant="transparent" className="p-6 text-center"><Card.Title>{sources.length ? '没有匹配的来源' : '来源库还是空的'}</Card.Title></Card>}
      </Tabs.Panel>
      <Tabs.Panel id="jobs" className="grid gap-3 pt-5">
        <p className="text-sm text-muted">任务类型和状态使用中文展示；仅管理员可展开技术详情。</p>{(jobsQuery.data?.jobs ?? []).filter((job) => job.user_id === user.id).slice(0, 20).map((job) => { const presented = presentJob(job, sourceMap); const feedActivity = job.job_type === 'user_feed_refresh' ? describeFeedJob(job, scheduleQuery.data?.worker_status) : undefined; return <Card key={job.id} variant="secondary" className="p-4"><div className="flex flex-wrap items-center gap-2"><Card.Title>{presented.title}</Card.Title><Chip size="sm" variant="soft"><Chip.Label>{presented.statusLabel}</Chip.Label></Chip></div><Card.Description className="mt-2">{presented.sourceName ? `${presented.sourceName} · ` : ''}{feedActivity?.message || presented.resultLabel} · {formatTime(job.finished_at || job.started_at || job.created_at)}</Card.Description>{presented.detail && <p className="mt-2 text-sm text-muted">{presented.detail}</p>}{isAdmin && <details className="mt-3"><summary className="cursor-pointer text-xs text-muted">技术详情</summary><pre className="mt-2 overflow-wrap-anywhere whitespace-pre-wrap text-xs">{JSON.stringify({ id: job.id, job_type: job.job_type, status: job.status, error_code: job.error_code }, null, 2)}</pre></details>}{!['queued', 'running'].includes(job.status) && <HeroResponseSchemaDetails job={job} sourceNames={sourceMap} />}{editable && job.retryable && <Button size="sm" variant="ghost" className="mt-3" onPress={() => retryMutation.mutate(job.id)}>重试</Button>}</Card> })}{!jobsQuery.isLoading && !(jobsQuery.data?.jobs ?? []).some((job) => job.user_id === user.id) && <Card variant="transparent" className="p-6 text-center"><Card.Title>还没有运行记录</Card.Title></Card>}
      </Tabs.Panel>
    </Tabs>
  </div>

  <HeroDialog isOpen={Boolean(editingSubscription)} onOpenChange={(open) => !open && setEditingSubscription(null)} title={editingSubscription ? `${editingSubscription.source.display_name} · 订阅设置` : '订阅设置'}>{editingSubscription && <SubscriptionForm {...editingSubscription} readonly={!editable} taxonomy={taxonomy} onDone={() => { void invalidate(); setEditingSubscription(null) }} onJob={createJob} />}</HeroDialog>
  <HeroDialog isOpen={Boolean(editingSource)} onOpenChange={(open) => !open && setEditingSource(null)} title={editingSource ? `${editingSource.display_name} · 来源设置` : '来源设置'}>{editingSource && activeDefinition && <SourceForm definition={activeDefinition} source={editingSource} secrets={secretsQuery.data?.secrets ?? []} allowSecret={isAdmin && sourceUsesSecret(activeDefinition)} scopes={sourceScopesForUser(user)} taxonomy={taxonomy} submitLabel="保存来源" onSubmit={async (payload) => { await api.updateSource(editingSource.id, payload); await invalidate(); setEditingSource(null) }} />}</HeroDialog>
  <HeroDialog isOpen={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (!open) setCreateType('') }} title="新增来源"><div className="grid gap-4"><HeroSelect label="来源类型" value={createType} onChange={setCreateType} options={[{ id: '', label: '请选择来源类型' }, ...definitions.map((definition: SourceTypeDefinition) => ({ id: definition.type, label: definition.label || definition.display_name || sourceTypeLabel(definition.type) }))]} />{activeDefinition && <SourceForm definition={activeDefinition} secrets={secretsQuery.data?.secrets ?? []} allowSecret={isAdmin && sourceUsesSecret(activeDefinition)} scopes={sourceScopesForUser(user)} taxonomy={taxonomy} submitLabel="创建来源" onSubmit={async (payload) => { await api.createSource(payload); await invalidate(); setCreateOpen(false); setCreateType('') }} />}</div></HeroDialog>
  </div>
}
