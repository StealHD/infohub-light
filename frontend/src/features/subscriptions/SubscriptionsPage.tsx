import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { CatalogSource, Job, SourceHealthItem, SourceTypeDefinition, Subscription, TaxonomyOptions } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  EmptyState,
  MenuItem,
  Skeleton,
  Stack,
  Status,
  Surface,
  Tab,
  Tabs,
  TextField,
  Typography,
  useMediaQuery,
} from '../../ui'
import { AddRounded, ErrorOutlineRounded, ExpandMoreRounded, RefreshRounded, SettingsRounded } from '../../ui/icons'
import { SubscriptionEditor, SourceForm } from './SubscriptionDialogs'
import { ResponseSchemaDetails } from './ResponseSchemaDetails'
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
} from './subscriptionModel'

type SubscriptionEntry = {
  scope: CatalogSource['scope']
  channel: string
  source: CatalogSource
  subscription: Subscription
  health?: SourceHealthItem
}

const healthCopy = {
  healthy: { label: '正常', tone: 'positive' },
  degraded: { label: '需关注', tone: 'warning' },
  failing: { label: '连续失败', tone: 'critical' },
  unknown: { label: '尚未抓取', tone: 'neutral' },
} as const

const roleIsAdmin = (role: string) => role === 'owner' || role === 'admin'

function formatTime(value?: string | null): string {
  if (!value) return '时间未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间未知' : parsed.toLocaleString('zh-CN')
}

function workerCopy(status?: string) {
  if (status === 'ready') return { label: '后台服务正常', tone: 'positive' as const }
  if (status === 'stale') return { label: '后台服务不可用', tone: 'critical' as const }
  return { label: '正在检查后台服务', tone: 'neutral' as const }
}

function GroupHeading({ id, title, description, count, collapsed, onToggle }: {
  id: string
  title: string
  description: string
  count: number
  collapsed?: boolean
  onToggle?: () => void
}) {
  return <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1.5, alignItems: { xs: 'flex-start', sm: 'center' } }}>
    <Box sx={{ flex: 1 }}>
      <Typography id={id} component="h2" variant="h3">{title}</Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>{description}</Typography>
    </Box>
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
      <Status label={`${count} 个来源`} />
      {onToggle && <Button
        size="small"
        aria-label={`${collapsed ? '展开' : '收起'} ${title}`}
        aria-expanded={!collapsed}
        onClick={onToggle}
        startIcon={<ExpandMoreRounded sx={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform 120ms' }} />}
      >{collapsed ? '展开' : '收起'}</Button>}
    </Stack>
  </Stack>
}

function CardGrid({ children }: { children: React.ReactNode }) {
  return <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 310px), 1fr))', gap: 1.5 }}>{children}</Box>
}

export function SubscriptionsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const mobile = useMediaQuery('(max-width:767px)')
  const [params, setParams] = useSearchParams()
  const filter = (params.get('health') ?? 'all') as HealthFilter
  const editable = canMutateSubscriptions(user)
  const isAdmin = roleIsAdmin(user.role)
  const [tab, setTab] = useState(0)
  const [editingSubscription, setEditingSubscription] = useState<{ subscription: Subscription; source: CatalogSource }>()
  const [editingSource, setEditingSource] = useState<CatalogSource>()
  const [createOpen, setCreateOpen] = useState(false)
  const [createType, setCreateType] = useState('')
  const [sourceSearch, setSourceSearch] = useState('')
  const [sourceTypeFilter, setSourceTypeFilter] = useState('all')
  const [scopeFilter, setScopeFilter] = useState('all')
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  const seenTerminalJobs = useRef(new Set<string>())
  const initiatedJobs = useRef(new Map<string, { action: string; entity: string; label: string }>())

  const sourcesQuery = useQuery({ queryKey: queryKeys.sources(user.id), queryFn: ({ signal }) => api.sources(isAdmin, signal) })
  const sourceTypesQuery = useQuery({ queryKey: queryKeys.sourceTypes(user.id), queryFn: ({ signal }) => api.sourceTypes(signal) })
  const subscriptionsQuery = useQuery({ queryKey: queryKeys.subscriptions(user.id), queryFn: ({ signal }) => api.subscriptions(signal) })
  const healthQuery = useQuery({ queryKey: queryKeys.sourceHealth(user.id), queryFn: ({ signal }) => api.sourceHealth(signal) })
  const scheduleQuery = useQuery({ queryKey: queryKeys.feedSchedule(user.id), queryFn: ({ signal }) => api.feedSchedule(signal) })
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs(user.id),
    queryFn: ({ signal }) => api.jobs(signal),
    refetchInterval: (query) => query.state.data?.jobs.some((job) => job.user_id === user.id && ['queued', 'running'].includes(job.status)) ? 2000 : false,
  })
  const configQuery = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal) })
  const secretsQuery = useQuery({ queryKey: queryKeys.secrets(user.id), queryFn: ({ signal }) => api.secrets(signal), enabled: isAdmin })

  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.sources(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.subscriptions(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.jobs(user.id) }),
    queryClient.invalidateQueries({ queryKey: ['user', user.id, 'feed'] }),
    queryClient.invalidateQueries({ queryKey: queryKeys.history(user.id) }),
  ])
  const errorMessage = (caught: unknown) => caught instanceof ApiError || caught instanceof Error ? caught.message : '操作失败，请稍后重试。'
  const scheduleMutation = useMutation({
    mutationFn: (patch: { enabled: boolean; interval_minutes: number }) => api.updateFeedSchedule(patch),
    onMutate: () => feedback.begin('feed-schedule', 'global'),
    onSuccess: () => { feedback.succeed('feed-schedule', 'global'); return queryClient.invalidateQueries({ queryKey: queryKeys.feedSchedule(user.id) }) },
    onError: (caught) => feedback.fail('feed-schedule', 'global', errorMessage(caught)),
  })
  const subscribeMutation = useMutation({
    mutationFn: (sourceId: string) => api.subscribe(sourceId),
    onMutate: (sourceId) => feedback.begin('subscribe', sourceId),
    onSuccess: (_result, sourceId) => { feedback.succeed('subscribe', sourceId); return invalidate() },
    onError: (caught, sourceId) => feedback.fail('subscribe', sourceId, errorMessage(caught)),
  })
  const unsubscribeMutation = useMutation({
    mutationFn: (subscriptionId: string) => api.unsubscribe(subscriptionId),
    onMutate: (subscriptionId) => feedback.begin('unsubscribe', subscriptionId),
    onSuccess: (_result, subscriptionId) => { feedback.succeed('unsubscribe', subscriptionId); return invalidate() },
    onError: (caught, subscriptionId) => feedback.fail('unsubscribe', subscriptionId, errorMessage(caught)),
  })
  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.createSource(payload),
    onMutate: () => feedback.begin('source-save', 'new'),
    onSuccess: () => feedback.succeed('source-save', 'new'),
    onError: (caught) => feedback.fail('source-save', 'new', errorMessage(caught)),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) => api.updateSource(id, payload),
    onMutate: ({ id }) => feedback.begin('source-save', id),
    onSuccess: (_result, { id }) => feedback.succeed('source-save', id),
    onError: (caught, { id }) => feedback.fail('source-save', id, errorMessage(caught)),
  })
  const retryMutation = useMutation({
    mutationFn: (jobId: string) => api.retryJob(jobId),
    onMutate: (jobId) => feedback.begin('job-retry', jobId),
    onSuccess: (_result, jobId) => { feedback.succeed('job-retry', jobId, '重试任务已排队。'); return invalidate() },
    onError: (caught, jobId) => feedback.fail('job-retry', jobId, errorMessage(caught)),
  })
  async function requireReadyWorker() {
    const currentSchedule = await scheduleQuery.refetch()
    if (currentSchedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。')
  }
  const fetchMutation = useMutation({
    mutationFn: async ({ source, subscription }: { source: CatalogSource; subscription: Subscription }) => {
      await requireReadyWorker()
      return api.createSourceFetch(source.id, subscription.id)
    },
    onMutate: ({ source }) => feedback.begin('source-fetch', source.id),
    onSuccess: (job, { source }) => {
      initiatedJobs.current.set(job.id, { action: 'source-fetch', entity: source.id, label: source.display_name })
      feedback.advance('source-fetch', source.id, 'queued')
      queryClient.setQueryData(queryKeys.jobs(user.id), (previous: { jobs: Job[] } | undefined) => ({
        jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)],
      }))
      return invalidate()
    },
    onError: (caught, { source }) => feedback.fail('source-fetch', source.id, errorMessage(caught)),
  })

  const sources = useMemo(() => sourcesQuery.data?.sources ?? [], [sourcesQuery.data])
  const definitions = sourceTypesQuery.data?.source_types ?? []
  const subscriptions = subscriptionsQuery.data?.subscriptions ?? []
  const taxonomy: TaxonomyOptions = configQuery.data?.taxonomy ?? {
    channels: [],
    topics: Array.isArray(configQuery.data?.config.tags) ? configQuery.data.config.tags.filter((topic): topic is string => typeof topic === 'string') : [],
  }
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources])
  const healthMap = useMemo(() => new Map((healthQuery.data?.items ?? []).map((item) => [item.subscription_id, item])), [healthQuery.data])
  const normalizedSearch = sourceSearch.trim().toLocaleLowerCase()
  const matchesFilters = (source: CatalogSource) => {
    if (sourceTypeFilter !== 'all' && source.type !== sourceTypeFilter) return false
    if (scopeFilter !== 'all' && source.scope !== scopeFilter) return false
    if (!normalizedSearch) return true
    return [source.display_name, source.description, source.default_channel, ...(source.default_topics ?? [])]
      .some((value) => String(value ?? '').toLocaleLowerCase().includes(normalizedSearch))
  }
  const subscriptionEntries = subscriptions
    .filter((subscription) => healthMatches(healthMap.get(subscription.id), filter))
    .map((subscription): SubscriptionEntry => {
      const source = sourceForSubscription(subscription, sourceMap.get(subscription.source_id))
      return { scope: source.scope, channel: effectiveSubscriptionChannel(subscription, source), source, subscription, health: healthMap.get(subscription.id) }
    })
    .filter(({ source }) => matchesFilters(source))
  const filteredSources = sources.filter(matchesFilters)
  const subscriptionGroups = groupSourcesByChannel(subscriptionEntries, (entry) => entry.channel, taxonomy.channels)
  const sourceGroups = groupSourcesByChannel(filteredSources, (source) => source.default_channel, taxonomy.channels)
  const activeCreateDefinition = definitions.find((definition) => definition.type === createType)
  const activeEditDefinition = definitions.find((definition) => definition.type === editingSource?.type)
  const worker = workerCopy(scheduleQuery.data?.worker_status)
  const loading = sourcesQuery.isLoading || sourceTypesQuery.isLoading || subscriptionsQuery.isLoading || healthQuery.isLoading || configQuery.isLoading
  const queryError = sourcesQuery.error || sourceTypesQuery.error || subscriptionsQuery.error || healthQuery.error || scheduleQuery.error || jobsQuery.error || configQuery.error

  useEffect(() => {
    const terminalJobs = (jobsQuery.data?.jobs ?? []).filter((job) => job.user_id === user.id && job.job_type === 'source_fetch' && ['succeeded', 'partial', 'failed'].includes(job.status))
    for (const job of terminalJobs) {
      const key = `${job.id}:${job.status}`
      if (seenTerminalJobs.current.has(key)) continue
      seenTerminalJobs.current.add(key)
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) })
      void queryClient.invalidateQueries({ queryKey: ['user', user.id, 'feed'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.history(user.id) })
      const initiated = initiatedJobs.current.get(job.id)
      if (initiated) {
        initiatedJobs.current.delete(job.id)
        const count = Number((job.result ?? job.result_json)?.item_count ?? 0)
        if (job.status === 'succeeded') feedback.succeed(initiated.action, initiated.entity, `${initiated.label} 获取完成，共 ${count} 条。`)
        else if (job.status === 'partial') feedback.advance(initiated.action, initiated.entity, 'partial', `${initiated.label} 部分完成，请查看运行记录。`)
        else feedback.fail(initiated.action, initiated.entity, job.error_message || `${initiated.label} 获取失败。`)
      }
    }
    for (const job of (jobsQuery.data?.jobs ?? []).filter((entry) => initiatedJobs.current.has(entry.id))) {
      const initiated = initiatedJobs.current.get(job.id)!
      if (job.status === 'running') feedback.advance(initiated.action, initiated.entity, 'running')
    }
  }, [feedback, jobsQuery.data, queryClient, user.id])

  async function createJob(kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) {
    if (kind === 'test') await api.createSourceTest(sourceId, subscriptionId)
    else {
      await requireReadyWorker()
      await api.createSourceFetch(sourceId, subscriptionId)
    }
    await invalidate()
  }

  function selectHealth(next: HealthFilter) {
    setParams(next === 'all' ? {} : { health: next })
  }

  return <Box sx={{ height: '100%', minHeight: 0, overflowY: 'auto' }}>
    <Box sx={{ width: 'min(100%, 1180px)', mx: 'auto', px: { xs: 2, md: 3 }, py: { xs: 2.5, md: 4 } }}>
      <Stack component="header" direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { xs: 'stretch', sm: 'center' }, justifyContent: 'space-between' }}>
        <Box>
          <Typography component="h1" variant="h1">订阅与来源</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>选择要持续关注的来源，并查看每次更新发生了什么。</Typography>
        </Box>
        {editable && <Button variant="contained" startIcon={<AddRounded />} onClick={() => setCreateOpen(true)}>新增来源</Button>}
      </Stack>

      <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} aria-label="订阅与来源页面" sx={{ mt: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="我的订阅" />
        <Tab label="来源库" />
        <Tab label="运行记录" />
      </Tabs>

      {tab !== 2 && <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25} sx={{ mt: 2, alignItems: { xs: 'stretch', md: 'center' } }}>
        <TextField
          size="small"
          label="搜索来源"
          value={sourceSearch}
          onChange={(event) => setSourceSearch(event.target.value)}
          sx={{ minWidth: { md: 280 }, flex: 1 }}
        />
        <TextField select size="small" label="来源类型" value={sourceTypeFilter} onChange={(event) => setSourceTypeFilter(event.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="all">全部类型</MenuItem>
          {definitions.map((definition) => <MenuItem key={definition.type} value={definition.type}>{definition.label || sourceTypeLabel(definition.type)}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="可见范围" value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="all">全部范围</MenuItem>
          <MenuItem value="public">公共来源</MenuItem>
          <MenuItem value="workspace">团队来源</MenuItem>
          <MenuItem value="private">我的私有来源</MenuItem>
        </TextField>
      </Stack>}

      {queryError && <Alert severity="error" sx={{ mt: 2 }}>订阅数据加载失败，请刷新页面后重试。</Alert>}

      {tab === 0 && <Stack role="tabpanel" aria-label="我的订阅" spacing={3} sx={{ mt: 3 }}>
        <Surface component="section" sx={{ p: { xs: 2, md: 2.5 }, border: 1, borderColor: 'divider' }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { xs: 'stretch', md: 'center' } }}>
            <Box sx={{ flex: 1 }}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography component="h2" variant="h3">自动更新信息流</Typography>
                <Status label={worker.label} tone={worker.tone} />
              </Stack>
              <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75 }}>
                按设定周期从全部已启用订阅抓取、去重并更新信息流，不会修改你的订阅设置。
              </Typography>
              <Typography variant="body2" sx={{ mt: 0.75 }}>
                {scheduleQuery.data?.enabled
                  ? `下次计划：${scheduleQuery.data.next_run_at ? formatTime(scheduleQuery.data.next_run_at) : '等待调度'}`
                  : '自动更新当前已关闭。'}
              </Typography>
            </Box>
            <TextField
              select
              size="small"
              label="更新周期"
              value={scheduleQuery.data?.interval_minutes ?? 360}
              disabled={!editable || feedback.isPending('feed-schedule', 'global')}
              onChange={(event) => scheduleMutation.mutate({ enabled: scheduleQuery.data?.enabled ?? false, interval_minutes: Number(event.target.value) })}
              sx={{ minWidth: 150 }}
            >{(scheduleQuery.data?.allowed_intervals ?? [60, 180, 360, 720, 1440]).map((value) => <MenuItem key={value} value={value}>{value < 60 ? `每 ${value} 分钟` : `每 ${value / 60} 小时`}</MenuItem>)}</TextField>
            <Button
              variant={scheduleQuery.data?.enabled ? 'outlined' : 'contained'}
              disabled={!editable || feedback.isPending('feed-schedule', 'global')}
              onClick={() => scheduleMutation.mutate({ enabled: !(scheduleQuery.data?.enabled ?? false), interval_minutes: scheduleQuery.data?.interval_minutes ?? 360 })}
            >{feedback.isPending('feed-schedule', 'global') ? '保存中…' : scheduleQuery.data?.enabled ? '关闭自动更新' : '开启自动更新'}</Button>
          </Stack>
        </Surface>

        <Box component="section" aria-labelledby="source-health-heading">
          <Typography id="source-health-heading" component="h2" variant="h3">来源健康</Typography>
          <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1.5, flexWrap: 'wrap' }}>
            <Chip label={`全部 ${healthQuery.data?.summary.total ?? 0}`} color={filter === 'all' ? 'primary' : 'default'} onClick={() => selectHealth('all')} />
            <Chip label={`正常 ${healthQuery.data?.summary.healthy ?? 0}`} color={filter === 'healthy' ? 'primary' : 'default'} onClick={() => selectHealth('healthy')} />
            <Chip label={`需关注 ${healthQuery.data?.summary.degraded ?? 0}`} color={filter === 'degraded' ? 'primary' : 'default'} onClick={() => selectHealth('degraded')} />
            <Chip label={`连续失败 ${healthQuery.data?.summary.failing ?? 0}`} color={filter === 'failing' ? 'primary' : 'default'} onClick={() => selectHealth('failing')} />
            <Chip label={`尚未抓取 ${healthQuery.data?.summary.unknown ?? 0}`} color={filter === 'unknown' ? 'primary' : 'default'} onClick={() => selectHealth('unknown')} />
          </Stack>
        </Box>

        {loading && <Stack spacing={1.5}>{[0, 1, 2].map((value) => <Skeleton key={value} variant="rounded" height={160} />)}</Stack>}
        {!loading && subscriptionGroups.map((group) => {
          const groupKey = `subscriptions:${group.channel}`
          const collapsed = !normalizedSearch && collapsedGroups.has(groupKey)
          return <Box component="section" aria-labelledby={`subscriptions-${group.channel}`} key={group.channel}>
          <GroupHeading
            id={`subscriptions-${group.channel}`}
            title={group.channel}
            description="按个人频道覆盖和来源默认频道归类。"
            count={group.items.length}
            collapsed={collapsed}
            onToggle={() => setCollapsedGroups((current) => {
              const next = new Set(current)
              if (next.has(groupKey)) next.delete(groupKey); else next.add(groupKey)
              return next
            })}
          />
          {!collapsed && <CardGrid>{group.items.map(({ source, subscription, health }) => {
            const healthState = healthCopy[health?.status ?? 'unknown']
            const definition = definitions.find((item) => item.type === source.type)
            const activeJob = (jobsQuery.data?.jobs ?? []).find((job) => job.user_id === user.id && job.job_type === 'source_fetch' && job.subscription_id === subscription.id && ['queued', 'running'].includes(job.status))
            const fetchPhase = feedback.phase('source-fetch', source.id)
            const isSubmittingFetch = fetchPhase === 'pending'
            const fetchLabel = isSubmittingFetch
              ? '提交中'
              : fetchPhase === 'running'
                ? '获取中'
                : fetchPhase === 'queued'
                  ? '已排队'
              : activeJob?.status === 'running'
                ? '获取中'
                : activeJob?.status === 'queued'
                  ? '已排队'
                  : '立即获取'
            return <Surface component="article" radius="card" key={subscription.id} sx={{ p: 2.25, border: 1, borderColor: 'divider' }}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography component="h3" variant="h3" noWrap>{source.display_name}</Typography>
                  <Stack direction="row" spacing={0.75} useFlexGap sx={{ mt: 1, flexWrap: 'wrap' }}>
                    <Status label={sourceTypeLabel(source.type)} />
                    <Status label={sourceScopeLabel(source.scope)} />
                    <Status label={healthState.label} tone={healthState.tone} />
                  </Stack>
                </Box>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>优先级 {subscription.priority ?? 0} · {health?.last_fetched_count ?? 0} 条最近结果</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{subscription.schedule?.enabled ? `单源下次获取：${formatTime(subscription.schedule.next_run_at)}` : '单源自动获取已关闭'}</Typography>
              {health?.last_issue && <Alert severity="warning" sx={{ mt: 1.5 }}>{health.last_issue.message || '最近一次抓取出现问题。'}</Alert>}
              <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 2, flexWrap: 'wrap' }}>
                <Button size="small" variant="outlined" aria-label={`配置 ${source.display_name} 订阅`} onClick={() => setEditingSubscription({ subscription, source })}>{editable ? '订阅设置' : '查看订阅'}</Button>
                {editable && <Button
                  size="small"
                  startIcon={<RefreshRounded />}
                  aria-label={`${fetchLabel} ${source.display_name}`}
                  disabled={Boolean(activeJob) || Boolean(fetchPhase && ['pending', 'queued', 'running'].includes(fetchPhase))}
                  onClick={() => fetchMutation.mutate({ source, subscription })}
                >{fetchLabel}</Button>}
                {definition && canEditSource(user, source) && <Button size="small" startIcon={<SettingsRounded />} aria-label={`编辑 ${source.display_name} 来源`} onClick={() => setEditingSource(source)}>编辑来源</Button>}
              </Stack>
            </Surface>
          })}</CardGrid>}
        </Box>})}
        {!loading && subscriptionEntries.length === 0 && <Surface><EmptyState title="没有匹配的订阅" description={filter === 'all' ? '可以前往来源库选择要关注的来源。' : '当前健康筛选下没有订阅。'} actionLabel={filter === 'all' ? '打开来源库' : '清除筛选'} onAction={() => filter === 'all' ? setTab(1) : selectHealth('all')} /></Surface>}
      </Stack>}

      {tab === 1 && <Stack role="tabpanel" aria-label="来源库" spacing={3} sx={{ mt: 3 }}>
        <Typography color="text.secondary">公共和团队来源由管理员维护；成员可以订阅或取消订阅，并单独配置自己的阅读偏好。</Typography>
        {loading && <Stack spacing={1.5}>{[0, 1, 2].map((value) => <Skeleton key={value} variant="rounded" height={140} />)}</Stack>}
        {!loading && sourceGroups.map((group) => {
          const groupKey = `library:${group.channel}`
          const collapsed = !normalizedSearch && collapsedGroups.has(groupKey)
          return <Box component="section" aria-labelledby={`library-${group.channel}`} key={group.channel}>
          <GroupHeading
            id={`library-${group.channel}`}
            title={group.channel}
            description="按来源默认频道归类；可见范围和来源类型保留为标签。"
            count={group.items.length}
            collapsed={collapsed}
            onToggle={() => setCollapsedGroups((current) => {
              const next = new Set(current)
              if (next.has(groupKey)) next.delete(groupKey); else next.add(groupKey)
              return next
            })}
          />
          {!collapsed && <CardGrid>{group.items.map((source) => {
            const subscribed = isSourceSubscribed(source.id, subscriptions)
            const subscription = subscriptions.find((item) => item.source_id === source.id)
            const definition = definitions.find((item) => item.type === source.type)
            return <Surface component="article" radius="card" key={source.id} sx={{ p: 2.25, border: 1, borderColor: 'divider' }}>
              <Typography component="h3" variant="h3">{source.display_name}</Typography>
              <Stack direction="row" spacing={0.75} useFlexGap sx={{ mt: 1, flexWrap: 'wrap' }}><Status label={sourceTypeLabel(source.type)} /><Status label={sourceScopeLabel(source.scope)} /></Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25, minHeight: 40 }}>{source.description || '该来源尚未填写说明。'}</Typography>
              <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 2, flexWrap: 'wrap' }}>
                {subscribed
                  ? <Button size="small" variant="outlined" disabled={!editable || !subscription || Boolean(subscription && feedback.isPending('unsubscribe', subscription.id))} onClick={() => subscription && unsubscribeMutation.mutate(subscription.id)}>{subscription && feedback.isPending('unsubscribe', subscription.id) ? '提交中…' : '取消订阅'}</Button>
                  : <Button size="small" variant="contained" disabled={!editable || feedback.isPending('subscribe', source.id)} onClick={() => subscribeMutation.mutate(source.id)}>{feedback.isPending('subscribe', source.id) ? '提交中…' : '订阅'}</Button>}
                {definition && canEditSource(user, source) && <Button size="small" startIcon={<SettingsRounded />} aria-label={`编辑 ${source.display_name} 来源`} onClick={() => setEditingSource(source)}>编辑来源</Button>}
              </Stack>
            </Surface>
          })}</CardGrid>}
        </Box>})}
        {!loading && filteredSources.length === 0 && <Surface><EmptyState title={sources.length ? '没有匹配的来源' : '来源库还是空的'} description={sources.length ? '请调整搜索或筛选条件。' : editable ? '新增一个来源后即可开始订阅。' : '请联系管理员添加可订阅来源。'} actionLabel={!sources.length && editable ? '新增来源' : undefined} onAction={!sources.length && editable ? () => setCreateOpen(true) : undefined} /></Surface>}
      </Stack>}

      {tab === 2 && <Stack role="tabpanel" aria-label="运行记录" spacing={1.5} sx={{ mt: 3 }}>
        <Typography color="text.secondary">这里记录信息流更新、单源抓取和连接测试，按最新任务优先显示。</Typography>
        {(jobsQuery.data?.jobs ?? []).filter((job) => job.user_id === user.id).slice(0, 20).map((job: Job) => {
          const presented = presentJob(job, sourceMap)
          return <Surface component="article" radius="card" key={job.id} sx={{ p: 2, border: 1, borderColor: 'divider' }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ alignItems: { xs: 'flex-start', sm: 'center' } }}>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                  <Typography component="h3" variant="h3">{presented.title}</Typography>
                  <Status label={presented.statusLabel} tone={presented.tone} />
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{presented.sourceName ? `${presented.sourceName} · ` : ''}{presented.resultLabel} · {formatTime(job.finished_at || job.started_at || job.created_at)}</Typography>
                {presented.detail && <Typography variant="body2" color={job.status === 'failed' ? 'error.main' : 'text.secondary'} sx={{ mt: 0.75 }}>{presented.detail}</Typography>}
                {isAdmin && <Box component="details" sx={{ mt: 1 }}>
                  <Typography component="summary" variant="caption" color="text.secondary" sx={{ cursor: 'pointer' }}>技术详情</Typography>
                  <Typography component="pre" variant="caption" sx={{ mt: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify({ id: job.id, job_type: job.job_type, status: job.status, error_code: job.error_code }, null, 2)}</Typography>
                </Box>}
                {!['queued', 'running'].includes(job.status) && <ResponseSchemaDetails job={job} sourceNames={sourceMap} />}
              </Box>
              <Stack direction="row" spacing={1}>
                {job.source_id && <Button size="small" onClick={() => setTab(1)}>查看来源</Button>}
                {editable && job.retryable && <Button size="small" variant="outlined" startIcon={<RefreshRounded />} disabled={feedback.isPending('job-retry', job.id)} onClick={() => retryMutation.mutate(job.id)}>{feedback.isPending('job-retry', job.id) ? '重试中…' : '重试'}</Button>}
              </Stack>
            </Stack>
          </Surface>
        })}
        {!jobsQuery.isLoading && (jobsQuery.data?.jobs ?? []).filter((job) => job.user_id === user.id).length === 0 && <Surface><EmptyState icon={<ErrorOutlineRounded />} title="还没有运行记录" description="更新信息流或测试来源后，任务结果会显示在这里。" /></Surface>}
      </Stack>}
    </Box>

    <Dialog open={Boolean(editingSubscription)} onClose={() => setEditingSubscription(undefined)} fullScreen={mobile} fullWidth maxWidth="sm">
      <DialogTitle>{editingSubscription ? `${editingSubscription.source.display_name} · 订阅设置` : '订阅设置'}</DialogTitle>
      <DialogContent dividers>{editingSubscription && <SubscriptionEditor
        subscription={editingSubscription.subscription}
        source={editingSubscription.source}
        readonly={!editable}
        taxonomy={taxonomy}
        onDone={() => { void invalidate(); setEditingSubscription(undefined) }}
        onJob={createJob}
      />}</DialogContent>
      <DialogActions><Button onClick={() => setEditingSubscription(undefined)}>关闭</Button></DialogActions>
    </Dialog>

    <Dialog open={Boolean(editingSource)} onClose={() => setEditingSource(undefined)} fullScreen={mobile} fullWidth maxWidth="sm">
      <DialogTitle>{editingSource ? `${editingSource.display_name} · 来源设置` : '来源设置'}</DialogTitle>
      <DialogContent dividers>{editingSource && activeEditDefinition && <SourceForm
        definition={activeEditDefinition}
        source={editingSource}
        secrets={secretsQuery.data?.secrets ?? []}
        scopes={sourceScopesForUser(user)}
        taxonomy={taxonomy}
        allowSecret={isAdmin && sourceUsesSecret(activeEditDefinition)}
        submitLabel="保存来源"
        onSubmit={async (payload) => {
          await updateMutation.mutateAsync({ id: editingSource.id, payload })
          await invalidate()
          setEditingSource(undefined)
        }}
      />}</DialogContent>
      <DialogActions><Button onClick={() => setEditingSource(undefined)}>关闭</Button></DialogActions>
    </Dialog>

    <Dialog open={createOpen} onClose={() => setCreateOpen(false)} fullScreen={mobile} fullWidth maxWidth="sm">
      <DialogTitle>新增来源</DialogTitle>
      <DialogContent dividers>
        <TextField select fullWidth size="small" label="来源类型" value={createType} onChange={(event) => setCreateType(event.target.value)} sx={{ mt: 1 }}>
          <MenuItem value="">请选择来源类型</MenuItem>
          {definitions.map((definition: SourceTypeDefinition) => <MenuItem key={definition.type} value={definition.type}>{definition.label || definition.display_name || sourceTypeLabel(definition.type)}</MenuItem>)}
        </TextField>
        {activeCreateDefinition && <SourceForm
          definition={activeCreateDefinition}
          secrets={secretsQuery.data?.secrets ?? []}
          scopes={sourceScopesForUser(user)}
          taxonomy={taxonomy}
          allowSecret={isAdmin && sourceUsesSecret(activeCreateDefinition)}
          submitLabel="创建来源"
          onSubmit={async (payload) => {
            await createMutation.mutateAsync(payload)
            await invalidate()
            setCreateOpen(false)
            setCreateType('')
          }}
        />}
      </DialogContent>
      <DialogActions><Button onClick={() => setCreateOpen(false)}>关闭</Button></DialogActions>
    </Dialog>
  </Box>
}
