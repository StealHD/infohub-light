import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  ApifyActorSourceCapability,
  CatalogSource,
  FeedSchedule,
  Job,
  SourceTypeDefinition,
  Subscription,
  TaxonomyOptions,
} from '../../api/types'
import type { ActionToken } from '../../app/actionGeneration'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  actionToast,
  anchoredTooltipProps,
  Button,
  Card,
  Icons,
  LoadingState,
  PageFrame,
  StatusIndicator,
  Switch,
  Tabs,
  Tooltip,
  TooltipTriggerButton,
  ViewBar,
} from '../../design-system'
import { describeFeedJob, newItemCountOf } from '../jobs/jobModel'
import { useWorkbenchAgentContext } from '../workbench-live/workbenchAgentContext'
import {
  canEditSource,
  canMutateSubscriptions,
  channelViewGroupsByChannel,
  effectiveSourceType,
  healthMatches,
  isPublicSubscriptionScope,
  presentJob,
  resolveViewSelection,
  sourceForSubscription,
  sourceScopesForUser,
  sourceTypeLabel,
  sourceUsesSecret,
  type HealthFilter,
} from '../subscriptions/subscriptionModel'
import { AdminPageHeader, HeroNotice, HeroSelect } from './HeroAdminControls'
import { HeroResponseSchemaDetails } from './HeroResponseSchemaDetails'
import { HeroSoftDisclosure } from './HeroSoftDisclosure'
import {
  SourceLibraryChannelView,
  SourceFilterMenu,
  SourceSearchField,
  SubscriptionListView,
  type LibraryViewEntry,
  type SubscriptionViewEntry,
} from './HeroSubscriptionChannelViews'
import { HeroDialog, SourceForm, SubscriptionForm } from './HeroSubscriptionDialogs'

const adminRole = (role: string) => role === 'owner' || role === 'admin'
type JobsResponse = { jobs: Job[] }

function actorOpsSourceDefinition(
  definition: SourceTypeDefinition,
  capabilities: ApifyActorSourceCapability[],
  currentProfileId = '',
): SourceTypeDefinition {
  const actorCapabilities = capabilities.filter((item) => (
    item.storage_type === 'apify_social' && item.mode === 'primary'
  ))
  const options = actorCapabilities.map((item) => ({
    value: item.profile_id,
    label: `${item.platform.toUpperCase()} · ${item.target_type} · ${item.capability}`,
  }))
  if (
    currentProfileId
    && !options.some((option) => option.value === currentProfileId)
  ) {
    options.push({
      value: currentProfileId,
      label: `当前 Route · ${currentProfileId}`,
    })
  }
  return {
    ...definition,
    fields: definition.fields
      .filter((field) => !['platform', 'kind'].includes(field.name))
      .map((field) => field.name === 'profile_id'
        ? {
            ...field,
            required: true,
            default: currentProfileId || options[0]?.value || '',
            options,
            help: '只显示已认证且当前可运行的 Actor Route。',
          }
        : field),
  }
}

const isFeedJob = (job: Job) => (
  job.job_type === 'user_feed_refresh' || job.job_type === 'source_fetch'
)

const formatTime = (value?: string | null) => {
  if (!value) return '时间未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间未知' : parsed.toLocaleString('zh-CN')
}

const formatCompactTime = (value?: string | null) => {
  if (!value) return '尚未完成'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '时间未知'
    : parsed.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}


function FeedScheduleControls({ schedule, globalSubscriptionCount, customSubscriptionCount, editable, pending, loading, error, onRetry, onUpdate }: {
  schedule?: FeedSchedule
  globalSubscriptionCount: number
  customSubscriptionCount: number
  editable: boolean
  pending: boolean
  loading: boolean
  error: boolean
  onRetry: () => void
  onUpdate: (patch: { enabled: boolean; interval_minutes: number }) => void
}) {
  const interval = schedule?.interval_minutes ?? 360
  const intervalOptions = (schedule?.allowed_intervals ?? [60, 180, 360, 720, 1440]).map((value) => ({ id: String(value), label: value < 60 ? `每 ${value} 分钟` : `每 ${value / 60} 小时` }))
  const controlsDisabled = !editable || pending || loading || error || !schedule
  const coverageSummary = globalSubscriptionCount === 0
    ? '当前没有跟随全局的订阅'
    : schedule?.enabled
      ? `覆盖 ${globalSubscriptionCount} 个订阅${customSubscriptionCount > 0 ? ` · ${customSubscriptionCount} 个使用单源周期` : ''}`
      : schedule
        ? `已关闭 · ${globalSubscriptionCount} 个订阅等待全局开启`
        : `${globalSubscriptionCount} 个订阅跟随全局`
  const nextSchedule = schedule?.enabled && globalSubscriptionCount > 0
    ? schedule.next_run_at ? `下次 ${formatTime(schedule.next_run_at)}` : '等待下次更新'
    : null
  const serviceStatus = loading
    ? { label: '正在检查后台服务', tone: 'accent' as const, icon: <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> }
    : error
      ? { label: '自动更新状态读取失败', tone: 'warning' as const, icon: <Icons.TriangleAlert size={13} aria-hidden="true" /> }
      : schedule?.worker_status === 'ready'
        ? { label: '后台服务正常', tone: 'success' as const, icon: <Icons.CircleCheck size={13} aria-hidden="true" /> }
        : { label: '后台服务不可用', tone: 'danger' as const, icon: <Icons.CircleX size={13} aria-hidden="true" /> }

  return <Card data-feed-schedule variant="secondary" className="min-w-0 max-w-full border border-separator bg-surface-secondary p-3 shadow-none min-[640px]:p-4">
    <div className="grid min-w-0 gap-3">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
        <div className="min-w-0">
          <Card.Title>全局自动更新</Card.Title>
          <Card.Description className="mt-1 hidden min-[640px]:block">默认更新所有“跟随全局”的已启用订阅；单源独立周期不会重复抓取。</Card.Description>
        </div>
        <div className="justify-self-end">
          <Switch
            aria-label="全局自动更新"
            aria-busy={pending}
            isSelected={schedule?.enabled ?? false}
            isDisabled={controlsDisabled}
            onChange={(enabled) => onUpdate({ enabled, interval_minutes: interval })}
          >
            <Switch.Content className="gap-0">
              <Switch.Control><Switch.Thumb /></Switch.Control>
            </Switch.Content>
          </Switch>
          {pending && <span className="sr-only" role="status">正在保存自动更新设置</span>}
        </div>
      </div>
      <div className="grid min-w-0 gap-3 min-[480px]:grid-cols-[minmax(0,1fr)_auto] min-[480px]:items-end">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <StatusIndicator iconOnly role="status" label={serviceStatus.label} tone={serviceStatus.tone} icon={serviceStatus.icon} />
          <span className="type-body text-muted">{coverageSummary}</span>
          {!loading && !error && nextSchedule && <span className="type-meta text-muted">{nextSchedule}</span>}
          {error && <Button size="sm" variant="ghost" onPress={onRetry}>重试</Button>}
        </div>
        <HeroSelect
          label="更新周期"
          value={String(interval)}
          onChange={(value) => onUpdate({ enabled: schedule?.enabled ?? false, interval_minutes: Number(value) })}
          isDisabled={controlsDisabled}
          options={intervalOptions}
          className="w-40 max-w-full justify-self-end"
        />
      </div>
    </div>
  </Card>
}

export function HeroSubscriptionsPage() {
  const { api, user, reloadFeed, beginAction, isActionCurrent } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const agent = useWorkbenchAgentContext()
  const editable = canMutateSubscriptions(user)
  const isAdmin = adminRole(user.role)
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const tab = requestedTab === 'library' || requestedTab === 'jobs' ? requestedTab : 'subscriptions'
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [scopeFilter, setScopeFilter] = useState('all')
  const [healthFilter, setHealthFilter] = useState<HealthFilter>('all')
  const [libraryChannel, setLibraryChannel] = useState('')
  const [editingSubscription, setEditingSubscription] = useState<{ source: CatalogSource; subscription: Subscription } | null>(null)
  const [subscriptionDialogPending, setSubscriptionDialogPending] = useState(false)
  const [editingSource, setEditingSource] = useState<CatalogSource | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createType, setCreateType] = useState('')
  const [supportProfileId, setSupportProfileId] = useState('x/profile/items')
  const [shareSource, setShareSource] = useState<CatalogSource | null>(null)
  const editingSubscriptionReturnFocus = useRef<HTMLElement | null>(null)
  const editingSourceReturnFocus = useRef<HTMLElement | null>(null)
  const shareSourceReturnFocus = useRef<HTMLElement | null>(null)
  const initiatedJobs = useRef(new Map<string, { action: string; entity: string; label: string; subscriptionId: string; token: ActionToken }>())

  function rememberDialogTrigger(target: { current: HTMLElement | null }) {
    target.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }

  function closeEditingSubscription() {
    setEditingSubscription(null)
  }

  function closeEditingSource() {
    setEditingSource(null)
  }

  function closeShareSource() {
    setShareSource(null)
  }

  const sourcesQuery = useQuery({ queryKey: queryKeys.sources(user.id), queryFn: ({ signal }) => api.sources(isAdmin, signal), staleTime: queryStaleTime.catalog })
  const typesQuery = useQuery({ queryKey: queryKeys.sourceTypes(user.id), queryFn: ({ signal }) => api.sourceTypes(signal), staleTime: queryStaleTime.sourceTypes })
  const capabilitiesQuery = useQuery({
    queryKey: queryKeys.sourceCapabilities(user.id),
    queryFn: ({ signal }) => api.sourceCapabilities(signal),
    staleTime: queryStaleTime.catalog,
  })
  const supportProfiles = capabilitiesQuery.data?.support_profiles ?? []
  const selectedSupportProfile = supportProfiles.find(
    (profile) => profile.id === supportProfileId,
  ) ?? supportProfiles[0]
  const definitions = useMemo(() => {
    const rawDefinitions = typesQuery.data?.source_types ?? []
    const actorCapabilities = capabilitiesQuery.data?.capabilities ?? []
    return rawDefinitions
      .filter((definition) => (
        definition.type !== 'apify_social'
        || Boolean(editingSource)
        || actorCapabilities.some((capability) => (
          capability.storage_type === 'apify_social'
          && capability.mode === 'primary'
        ))
      ))
      .map((definition) => {
        if (definition.type !== 'apify_social') return definition
        const currentProfileId = String(
          editingSource?.config?.profile_id ?? '',
        ).trim()
        if (editingSource && !currentProfileId) return definition
        return actorOpsSourceDefinition(
          definition,
          actorCapabilities,
          currentProfileId,
        )
      })
  }, [capabilitiesQuery.data, editingSource, typesQuery.data])
  const activeDefinition = definitions.find((definition) => definition.type === (editingSource ? effectiveSourceType(editingSource) : createType))
  const subscriptionsQuery = useQuery({ queryKey: queryKeys.subscriptions(user.id), queryFn: ({ signal }) => api.subscriptions(signal), staleTime: queryStaleTime.catalog })
  const healthQuery = useQuery({ queryKey: queryKeys.sourceHealth(user.id), queryFn: ({ signal }) => api.sourceHealth(signal), staleTime: queryStaleTime.catalog })
  const scheduleQuery = useQuery({ queryKey: queryKeys.feedSchedule(user.id), queryFn: ({ signal }) => api.feedSchedule(signal), staleTime: queryStaleTime.catalog })
  const feedJobsQuery = useQuery({
    queryKey: queryKeys.feedJobs(user.id),
    queryFn: ({ signal }) => api.feedJobs(signal),
    enabled: false,
    staleTime: queryStaleTime.jobs,
  })
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs(user.id),
    queryFn: ({ signal }) => api.jobs(signal),
    enabled: tab === 'jobs',
    staleTime: queryStaleTime.jobs,
    refetchInterval: (query) => tab === 'jobs' && query.state.data?.jobs.some((job) => (
      job.user_id === user.id && ['queued', 'running'].includes(job.status)
    )) ? 2000 : false,
  })
  const configQuery = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal), staleTime: queryStaleTime.settings })
  const sourceDialogNeedsSecret = Boolean(
    isAdmin
    && activeDefinition
    && sourceUsesSecret(activeDefinition)
    && (editingSource || createOpen),
  )
  const secretsQuery = useQuery({
    queryKey: queryKeys.secrets(user.id),
    queryFn: ({ signal }) => api.secrets(signal),
    enabled: sourceDialogNeedsSecret,
  })

  useEffect(() => {
    initiatedJobs.current.clear()
  }, [user.id])

  useEffect(() => {
    const todayStart = healthQuery.data?.window?.today_start
    if (!todayStart) return
    const nextShanghaiMidnight = Date.parse(todayStart) + 24 * 60 * 60 * 1000
    if (!Number.isFinite(nextShanghaiMidnight)) return
    const timer = window.setTimeout(() => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.feedRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.historyRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.searchRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
      ])
    }, Math.max(0, nextShanghaiMidnight - Date.now() + 1_000))
    return () => window.clearTimeout(timer)
  }, [healthQuery.data?.window?.today_start, queryClient, user.id])

  const refreshCatalog = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.sources(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.subscriptions(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
  ])
  const refreshCatalogAndContent = () => Promise.all([
    refreshCatalog(),
    queryClient.invalidateQueries({ queryKey: queryKeys.feedRoot(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.historyRoot(user.id) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.searchRoot(user.id) }),
  ])
  const upsertJob = (job: Job) => {
    if (isFeedJob(job)) {
      queryClient.setQueryData(queryKeys.feedJobs(user.id), (previous: JobsResponse | undefined) => ({
        jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)].slice(0, 20),
      }))
    }
    queryClient.setQueryData(queryKeys.jobs(user.id), (previous: JobsResponse | undefined) => previous ? ({
      ...previous,
      jobs: [job, ...previous.jobs.filter((entry) => entry.id !== job.id)].slice(0, 100),
    }) : previous)
  }
  const mutationError = (caught: unknown) => caught instanceof ApiError || caught instanceof Error ? caught.message : '操作失败，请稍后重试。'
  const supportCheckMutation = useMutation({
    mutationFn: () => {
      if (!selectedSupportProfile) throw new Error('没有可用的 Actor Route Profile')
      return api.requestApifyActorSupportCheck({
        platform: selectedSupportProfile.platform,
        target_type: selectedSupportProfile.target_type,
        capability: selectedSupportProfile.capability,
        expected_generation: capabilitiesQuery.data?.generation ?? 0,
      })
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.sourceCapabilities(user.id),
      })
      actionToast.success(
        result.discovery_run_id ? 'Actor 支持检查已提交' : '该来源类型已经可用',
      )
    },
    onError: (caught) => actionToast.danger('Actor 支持检查提交失败', {
      description: mutationError(caught),
    }),
  })
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
  const subscribeMutation = useMutation({ mutationFn: (source: CatalogSource) => api.subscribe(source.id), onMutate: (source) => feedback.begin('subscribe', source.id), onSuccess: async (result, source) => { await refreshCatalogAndContent(); feedback.clear('subscribe', source.id); const reused = result.subscription.reused_item_count ?? 0; actionToast.success(`${source.display_name} 订阅成功`, { description: reused > 0 ? `已复用 ${reused} 条已有内容，无需重复获取。` : undefined }) }, onError: (caught, source) => { feedback.clear('subscribe', source.id); actionToast.danger(`${source.display_name} 订阅失败`, { description: mutationError(caught) }) } })
  const unsubscribeMutation = useMutation({ mutationFn: ({ subscription }: { source: CatalogSource; subscription: Subscription }) => api.unsubscribe(subscription.id), onMutate: ({ source }) => feedback.begin('unsubscribe', source.id), onSuccess: async (_result, { source }) => { await refreshCatalogAndContent(); feedback.clear('unsubscribe', source.id); actionToast.success(`${source.display_name} 已取消订阅`, { description: '其他成员的订阅和来源不会受到影响。' }) }, onError: (caught, { source }) => { feedback.clear('unsubscribe', source.id); actionToast.danger(`${source.display_name} 取消订阅失败`, { description: mutationError(caught) }) } })
  const shareMutation = useMutation({
    mutationFn: ({ source, scope }: { source: CatalogSource; scope: 'workspace' | 'public' }) => api.shareSource(source.id, scope),
    onSuccess: async (result) => {
      await refreshCatalogAndContent()
      closeShareSource()
      actionToast.success('来源已分享', { description: result.notice })
    },
    onError: (caught) => actionToast.danger('来源分享失败', { description: mutationError(caught) }),
  })
  const retryMutation = useMutation({
    mutationFn: (job: Job) => api.retryJob(job.id),
    onMutate: (job) => feedback.begin('retry-job', job.id),
    onSuccess: (result, job) => {
      queryClient.removeQueries({ queryKey: queryKeys.job(user.id, job.id) })
      upsertJob(result)
      feedback.clear('retry-job', job.id)
      actionToast.success('重试任务已提交')
    },
    onError: (caught, job) => {
      feedback.clear('retry-job', job.id)
      actionToast.danger('重试任务提交失败', { description: mutationError(caught) })
    },
  })
  const retryJob = retryMutation.mutate
  const notificationMutation = useMutation({
    mutationFn: ({ subscription, enabled }: { source: CatalogSource; subscription: Subscription; enabled: boolean }) => (
      api.updateSubscription(subscription.id, { notify_on_new_items: enabled })
    ),
    onMutate: async ({ subscription, enabled }) => {
      const queryKey = queryKeys.subscriptions(user.id)
      feedback.begin('subscription-notification', subscription.id)
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<{ subscriptions: Subscription[] }>(queryKey)
      queryClient.setQueryData<{ subscriptions: Subscription[] }>(queryKey, (current) => current ? ({
        ...current,
        subscriptions: current.subscriptions.map((item) => item.id === subscription.id
          ? { ...item, notify_on_new_items: enabled }
          : item),
      }) : current)
      return { previous }
    },
    onSuccess: (updated, { source, enabled }) => {
      const queryKey = queryKeys.subscriptions(user.id)
      queryClient.setQueryData<{ subscriptions: Subscription[] }>(queryKey, (current) => current ? ({
        ...current,
        subscriptions: current.subscriptions.map((item) => item.id === updated.id
          ? { ...item, ...updated, schedule: updated.schedule ?? item.schedule }
          : item),
      }) : current)
      feedback.clear('subscription-notification', updated.id)
      actionToast.success(`${source.display_name} 新内容通知已${enabled ? '开启' : '关闭'}`)
    },
    onError: (caught, { source, subscription }, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.subscriptions(user.id), context.previous)
      }
      feedback.clear('subscription-notification', subscription.id)
      actionToast.danger(`${source.display_name} 通知设置保存失败`, { description: mutationError(caught) })
    },
  })
  const fetchMutation = useMutation({
    mutationFn: async ({ source, subscription }: { source: CatalogSource; subscription: Subscription }) => {
      const schedule = await scheduleQuery.refetch()
      if (schedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。')
      return api.createSourceFetch(source.id, subscription.id)
    },
    onMutate: ({ source }) => {
      feedback.begin('source-fetch', source.id)
      return { token: beginAction() }
    },
    onSuccess: (job, { source, subscription }, context) => {
      if (!context || !isActionCurrent(context.token)) return
      initiatedJobs.current.set(job.id, { action: 'source-fetch', entity: source.id, label: source.display_name, subscriptionId: subscription.id, token: context.token })
      feedback.advance('source-fetch', source.id, 'queued')
      upsertJob(job)
    },
    onError: (caught, { source }, context) => {
      if (!context || !isActionCurrent(context.token)) return
      feedback.clear('source-fetch', source.id)
      actionToast.danger(`${source.display_name} 获取失败`, { description: mutationError(caught) })
    },
  })

  const sources = useMemo(() => sourcesQuery.data?.sources ?? [], [sourcesQuery.data])
  const subscriptions = useMemo(
    () => subscriptionsQuery.data?.subscriptions ?? [],
    [subscriptionsQuery.data?.subscriptions],
  )
  const taxonomy: TaxonomyOptions = configQuery.data?.taxonomy ?? { channels: [], topics: Array.isArray(configQuery.data?.config.tags) ? configQuery.data.config.tags.filter((topic): topic is string => typeof topic === 'string') : [] }
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources])
  const scheduleCoverage = useMemo(() => subscriptions.reduce(
    (counts, subscription) => {
      const source = sourceForSubscription(
        subscription,
        sourceMap.get(subscription.source_id),
      )
      if (!subscription.enabled || !source.enabled) return counts
      if (subscription.schedule?.enabled) counts.custom += 1
      else counts.global += 1
      return counts
    },
    { global: 0, custom: 0 },
  ), [sourceMap, subscriptions])
  const healthMap = useMemo(() => new Map((healthQuery.data?.items ?? []).map((health) => [health.subscription_id, health])), [healthQuery.data])
  const normalized = search.trim().toLocaleLowerCase()
  const matchesSource = (source: CatalogSource) => (typeFilter === 'all' || effectiveSourceType(source) === typeFilter) && (scopeFilter === 'all' || (scopeFilter === 'public' ? isPublicSubscriptionScope(source.scope) : source.scope === 'private')) && (!normalized || [source.display_name, source.description, source.default_channel, ...(source.default_topics ?? [])].some((value) => String(value ?? '').toLocaleLowerCase().includes(normalized)))
  const subscriptionEntries = subscriptions
    .filter((subscription) => healthMatches(healthMap.get(subscription.id), healthFilter))
    .map((subscription) => {
      const source = sourceForSubscription(subscription, sourceMap.get(subscription.source_id))
      return {
        source,
        subscription,
        health: healthMap.get(subscription.id),
      }
    })
    .filter(({ source }) => matchesSource(source))
    .map((entry): SubscriptionViewEntry => {
      const activeJob = (feedJobsQuery.data?.jobs ?? []).find((job) => job.job_type === 'source_fetch' && job.subscription_id === entry.subscription.id && ['queued', 'running'].includes(job.status))
      const phase = feedback.phase('source-fetch', entry.source.id)
      const fetchLabel: SubscriptionViewEntry['fetchLabel'] = phase === 'pending'
        ? '提交中'
        : activeJob?.status === 'running' || phase === 'running'
          ? '获取中'
          : activeJob?.status === 'queued' || phase === 'queued'
            ? '已排队'
            : '立即获取'
      const canEdit = Boolean(definitions.find((definition) => definition.type === effectiveSourceType(entry.source))) && canEditSource(user, entry.source)
      return {
        ...entry,
        fetchLabel,
        notificationPending: feedback.isPending('subscription-notification', entry.subscription.id),
        canEdit,
        canShare: editable && entry.source.scope === 'private' && entry.source.owner_user_id === user.id,
      }
    })
  const libraryEntries = sources.filter(matchesSource).map((source): LibraryViewEntry => {
    const subscription = subscriptions.find((item) => item.source_id === source.id)
    return {
      source,
      subscription,
      channel: String(source.default_channel || '').trim() || '其他',
      subscribed: Boolean(subscription),
      subscribePending: feedback.isPending('subscribe', source.id),
      unsubscribePending: feedback.isPending('unsubscribe', source.id),
      canEdit: canEditSource(user, source),
      canShare: editable && source.scope === 'private' && source.owner_user_id === user.id,
    }
  })
  const sourceGroups = channelViewGroupsByChannel(libraryEntries, (entry) => entry.channel, taxonomy.channels)
  const activeLibraryChannel = resolveViewSelection(sourceGroups, libraryChannel)
  const loadError = sourcesQuery.error || typesQuery.error || subscriptionsQuery.error || healthQuery.error || configQuery.error
  const loading = sourcesQuery.isLoading || typesQuery.isLoading || capabilitiesQuery.isLoading || subscriptionsQuery.isLoading || healthQuery.isLoading || configQuery.isLoading
  const schedulePending = feedback.isPending('feed-schedule', 'global')
  useEffect(() => {
    const jobs = feedJobsQuery.data?.jobs ?? []
    for (const job of jobs.filter((entry) => initiatedJobs.current.has(entry.id))) {
      const initiated = initiatedJobs.current.get(job.id)!
      if (job.status === 'running' && feedback.phase(initiated.action, initiated.entity) !== 'running') {
        feedback.advance(initiated.action, initiated.entity, 'running')
      }
    }
    const settled = jobs.flatMap((job) => {
      const initiated = initiatedJobs.current.get(job.id)
      if (
        !initiated
        || job.user_id !== user.id
        || job.job_type !== 'source_fetch'
        || !['succeeded', 'partial', 'failed', 'cancelled'].includes(job.status)
      ) return []
      return [{ job, initiated }]
    })
    if (settled.length === 0) return

    for (const { job } of settled) initiatedJobs.current.delete(job.id)
    const current = settled.filter(({ initiated }) => isActionCurrent(initiated.token))
    for (const { job, initiated } of current.filter(({ job }) => job.status === 'failed' || job.status === 'cancelled')) {
      const message = job.status === 'cancelled' ? '任务已取消。' : job.error_message || '请稍后重试。'
      const show = job.status === 'cancelled' ? actionToast.warning : actionToast.danger
      show(`${initiated.label} 获取${job.status === 'cancelled' ? '已取消' : '失败'}`, {
        description: message,
        onRetry: job.retryable ? () => retryJob(job) : undefined,
      })
      feedback.clear(initiated.action, initiated.entity)
    }

    const reloadable = current.filter(({ job }) => job.status === 'succeeded' || job.status === 'partial')
    if (reloadable.length === 0) return
    void reloadFeed()
      .then(() => {
        for (const { job, initiated } of reloadable) {
          if (!isActionCurrent(initiated.token)) continue
          const newItemCount = newItemCountOf(job)
          if (job.status === 'succeeded') {
            actionToast.success(`${initiated.label} 获取完成`, {
              description: newItemCount === undefined
                ? '信息流已加载。'
                : newItemCount === 0
                  ? '本次没有新增内容，信息流已加载。'
                  : `新增 ${newItemCount} 条，信息流已加载。`,
            })
          } else {
            actionToast.warning(`${initiated.label} 部分完成`, {
              description: newItemCount === undefined
                ? '信息流已加载；请查看运行记录。'
                : newItemCount === 0
                  ? '本次没有新增内容，信息流已加载；请查看运行记录。'
                  : `新增 ${newItemCount} 条，信息流已加载；请查看运行记录。`,
              onRetry: job.retryable ? () => retryJob(job) : undefined,
            })
          }
          feedback.clear(initiated.action, initiated.entity)
        }
      })
      .catch(() => {
        for (const { initiated } of reloadable) {
          if (isActionCurrent(initiated.token)) feedback.clear(initiated.action, initiated.entity)
        }
      })
  }, [feedback, feedJobsQuery.data, isActionCurrent, reloadFeed, retryJob, user.id])

  async function createJob(kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) {
    if (kind === 'test') {
      const job = await api.createSourceTest(sourceId, subscriptionId)
      upsertJob(job)
    }
    else {
      const token = beginAction()
      const schedule = await scheduleQuery.refetch()
      if (schedule.data?.worker_status !== 'ready') throw new Error('后台获取服务当前不可用，请稍后再试。')
      const job = await api.createSourceFetch(sourceId, subscriptionId)
      if (!isActionCurrent(token)) return
      const source = sourceMap.get(sourceId)
      initiatedJobs.current.set(job.id, { action: 'source-fetch', entity: sourceId, label: source?.display_name ?? '来源', subscriptionId, token })
      feedback.advance('source-fetch', sourceId, 'queued')
      upsertJob(job)
    }
  }

  function beginShare(source: CatalogSource, trigger: HTMLElement) {
    shareSourceReturnFocus.current = trigger
    setShareSource(source)
  }

  function beginEditSource(source: CatalogSource, trigger: HTMLElement) {
    editingSourceReturnFocus.current = trigger
    setEditingSource(source)
  }

  function beginEditSubscription(entry: SubscriptionViewEntry) {
    rememberDialogTrigger(editingSubscriptionReturnFocus)
    setEditingSubscription({ source: entry.source, subscription: entry.subscription })
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

  function selectTab(key: string) {
    const next = new URLSearchParams(searchParams)
    next.set('tab', key === 'library' || key === 'jobs' ? key : 'subscriptions')
    setSearchParams(next, { replace: true })
  }

  const sourceFilters = {
    definitions,
    typeFilter,
    onTypeChange: setTypeFilter,
    scopeFilter,
    onScopeChange: setScopeFilter,
    healthFilter,
    onHealthChange: setHealthFilter,
    includeHealth: tab === 'subscriptions',
  }

  return <div className="quiet-scroll-region h-full min-w-0 overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid min-w-0 gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description="选择要持续关注的来源，并查看每次更新发生了什么。" />
    {loadError && <HeroNotice title="订阅数据加载失败，请刷新页面后重试。" />}
    {capabilitiesQuery.isError && <HeroNotice title="Actor Route 能力目录读取失败，付费来源创建已暂时隐藏。" status="warning">
      <Button size="sm" variant="ghost" onPress={() => void capabilitiesQuery.refetch()}>重试能力目录</Button>
    </HeroNotice>}
    <Tabs selectedKey={tab} onSelectionChange={(key) => selectTab(String(key))}>
      <div data-subscription-tabs-toolbar className="sticky top-0 z-20 py-2">
        <div className="rounded-xl bg-background/70 supports-[backdrop-filter:blur(1px)]:backdrop-blur-md">
          <ViewBar className={`min-w-0 ${tab === 'jobs' ? 'justify-start' : 'grid gap-2 min-[640px]:grid-cols-[auto_minmax(0,1fr)_auto_auto] min-[640px]:items-center'}`}>
            <div className="quiet-scroll-region min-w-0 max-w-full overflow-x-auto">
              <Tabs.List aria-label="订阅与来源页面" className="flex w-max min-w-0 gap-1 bg-transparent p-0">
                <Tabs.Tab id="subscriptions" aria-label="我的订阅" className="min-h-9 w-auto shrink-0 justify-center gap-2 rounded-lg px-3">我的订阅<Tabs.Indicator /></Tabs.Tab>
                <Tabs.Tab id="library" aria-label="来源库" className="min-h-9 w-auto shrink-0 justify-center gap-2 rounded-lg px-3">来源库<Tabs.Indicator /></Tabs.Tab>
                <Tabs.Tab id="jobs" aria-label="运行记录" className="min-h-9 w-auto shrink-0 justify-center gap-2 rounded-lg px-3">运行记录<Tabs.Indicator /></Tabs.Tab>
              </Tabs.List>
            </div>
            {tab !== 'jobs' && <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-1 min-[640px]:contents">
              <SourceSearchField value={search} onChange={setSearch} />
              <SourceFilterMenu filters={sourceFilters} />
              {editable && <Button size="sm" aria-label="新增来源" className="size-8 min-w-8 shrink-0 px-0 min-[480px]:w-auto min-[480px]:px-3" onPress={() => setCreateOpen(true)}>
                <Icons.Plus size={15} />
                <span className="hidden min-[480px]:inline">新增来源</span>
              </Button>}
            </div>}
          </ViewBar>
        </div>
      </div>
      <Tabs.Panel id="subscriptions" className="grid gap-5 pt-5">
        {loading
          ? <LoadingState label="正在读取订阅" rows={1} />
          : <SubscriptionListView
              items={subscriptionEntries}
              editable={editable}
              feedWindowDays={healthQuery.data?.window?.feed_days ?? 7}
              globalSchedule={scheduleQuery.data}
              schedule={<FeedScheduleControls
                schedule={scheduleQuery.data}
                globalSubscriptionCount={scheduleCoverage.global}
                customSubscriptionCount={scheduleCoverage.custom}
                editable={editable}
                pending={schedulePending}
                loading={scheduleQuery.isLoading}
                error={scheduleQuery.isError}
                onRetry={() => void scheduleQuery.refetch()}
                onUpdate={(patch) => scheduleMutation.mutate(patch)}
              />}
              onFetch={(entry) => fetchMutation.mutate({ source: entry.source, subscription: entry.subscription })}
              onToggleNotification={(entry, enabled) => notificationMutation.mutate({ source: entry.source, subscription: entry.subscription, enabled })}
              onEditSubscription={beginEditSubscription}
              onEditSource={beginEditSource}
              onShare={beginShare}
            />}
      </Tabs.Panel>
      <Tabs.Panel id="library" className="grid gap-5 pt-5">
        {loading
          ? <LoadingState label="正在读取来源库" rows={1} />
          : <SourceLibraryChannelView
              groups={sourceGroups}
              selectedChannel={activeLibraryChannel}
              onSelectChannel={setLibraryChannel}
              editable={editable}
              hasSources={sources.length > 0}
              onSubscribe={(source) => subscribeMutation.mutate(source)}
              onUnsubscribe={(entry) => {
                if (entry.subscription) unsubscribeMutation.mutate({ source: entry.source, subscription: entry.subscription })
              }}
              onEditSource={beginEditSource}
              onShare={beginShare}
            />}
      </Tabs.Panel>
      <Tabs.Panel id="jobs" className="grid gap-3 pt-5">
        <p className="type-body text-muted">任务类型和状态使用中文展示；可加入 OpenClaw 分析，仅管理员可展开技术详情。</p>
        {jobsQuery.isLoading && <LoadingState label="正在读取运行记录" rows={2} />}
        {jobsQuery.isError && <HeroNotice title="运行记录读取失败" status="warning">
          <span>订阅和来源仍可继续使用。</span>
          <Button size="sm" variant="ghost" className="ml-2" onPress={() => void jobsQuery.refetch()}>重试</Button>
        </HeroNotice>}
        {(jobsQuery.data?.jobs ?? []).filter((job) => job.user_id === user.id).map((job) => {
          const presented = presentJob(job, sourceMap)
          const feedActivity = job.job_type === 'user_feed_refresh' ? describeFeedJob(job, scheduleQuery.data?.worker_status) : undefined
          const retryPending = feedback.isPending('retry-job', job.id)
          const contextId = `job:${job.id}`
          const inContext = agent.draft.items.some((item) => item.articleId === contextId)
          const resultDetail = feedActivity?.message || presented.detail || presented.resultLabel
          const resultSummary = feedActivity?.message || presented.resultLabel
          const extraDetail = presented.detail && presented.detail !== resultSummary ? presented.detail : null
          const statusTone = presented.tone === 'positive' ? 'success' : presented.tone === 'critical' ? 'danger' : presented.tone
          const statusIcon = presented.icon === 'loader'
            ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            : presented.icon === 'check'
              ? <Icons.CircleCheck size={13} aria-hidden="true" />
              : presented.icon === 'warning'
                ? <Icons.TriangleAlert size={13} aria-hidden="true" />
                : presented.icon === 'error'
                  ? <Icons.CircleX size={13} aria-hidden="true" />
                  : presented.icon === 'stop'
                    ? <Icons.CircleStop size={13} aria-hidden="true" />
                    : <Icons.Clock3 size={13} aria-hidden="true" />
          return <Card key={job.id} data-compact-job-card variant="secondary" className="min-w-0 max-w-full border border-separator bg-surface-secondary p-3 shadow-none">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Card.Title className="min-w-0 flex-1">{presented.title}</Card.Title>
              <StatusIndicator iconOnly label={presented.statusLabel} tone={statusTone} icon={statusIcon} />
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
            <Card.Description className="type-meta mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="min-w-0 flex-1 truncate">{presented.sourceName ? `${presented.sourceName} · ` : ''}{resultSummary}</span>
              <span className="shrink-0">创建 {formatCompactTime(job.created_at)} · {job.finished_at ? `完成 ${formatCompactTime(job.finished_at)}` : '进行中'}</span>
            </Card.Description>
            {extraDetail && <p className="type-meta mt-1 line-clamp-2 text-muted">{extraDetail}</p>}
            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-separator pt-2">
              {isAdmin && <HeroSoftDisclosure label="技术详情"><pre className="type-meta whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify({ id: job.id, job_type: job.job_type, status: job.status, error_code: job.error_code }, null, 2)}</pre></HeroSoftDisclosure>}
              {!['queued', 'running'].includes(job.status) && <HeroResponseSchemaDetails job={job} sourceNames={sourceMap} api={api} userId={user.id} className="m-0" />}
              {editable && job.retryable && <Button size="sm" variant="ghost" className="ml-auto" aria-label={retryPending ? `重试中 ${presented.title}` : undefined} isDisabled={retryPending} onPress={() => retryMutation.mutate(job)}>{retryPending ? '重试中' : '重试'}</Button>}
            </div>
          </Card>
        })}
        {!jobsQuery.isLoading && !(jobsQuery.data?.jobs ?? []).some((job) => job.user_id === user.id) && <Card variant="transparent" className="p-6 text-center"><Card.Title>还没有运行记录</Card.Title></Card>}
      </Tabs.Panel>
    </Tabs>
  </PageFrame>

  <HeroDialog
    isOpen={Boolean(editingSubscription)}
    onOpenChange={(open) => !open && closeEditingSubscription()}
    returnFocusRef={editingSubscriptionReturnFocus}
    title={editingSubscription ? `${editingSubscription.source.display_name} · 订阅设置` : '订阅设置'}
    locked={subscriptionDialogPending}
  >{editingSubscription && <SubscriptionForm
    {...editingSubscription}
    readonly={!editable}
    taxonomy={taxonomy}
    onPendingChange={setSubscriptionDialogPending}
    onDone={() => { void refreshCatalogAndContent(); closeEditingSubscription() }}
    onJob={createJob}
  />}</HeroDialog>
  <HeroDialog isOpen={Boolean(editingSource)} onOpenChange={(open) => !open && closeEditingSource()} returnFocusRef={editingSourceReturnFocus} title={editingSource ? `${editingSource.display_name} · 来源设置` : '来源设置'}>
    {editingSource && activeDefinition && (
      sourceDialogNeedsSecret && secretsQuery.isLoading
        ? <LoadingState label="正在读取可用 Key" rows={2} />
        : sourceDialogNeedsSecret && secretsQuery.isError
          ? <HeroNotice title="可用 Key 读取失败" status="warning">
              <Button size="sm" variant="ghost" className="ml-2" onPress={() => void secretsQuery.refetch()}>重试</Button>
            </HeroNotice>
          : <SourceForm
              definition={activeDefinition}
              source={editingSource}
              secrets={secretsQuery.data?.secrets ?? []}
              allowSecret={isAdmin && sourceUsesSecret(activeDefinition)}
              scopes={sourceScopesForUser(user)}
              taxonomy={taxonomy}
              submitLabel="保存来源"
              onSubmit={async (payload) => {
                await api.updateSource(editingSource.id, payload)
                await refreshCatalogAndContent()
                closeEditingSource()
                actionToast.success('来源设置已保存')
              }}
            />
    )}
  </HeroDialog>
  <HeroDialog isOpen={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (!open) setCreateType('') }} title="新增来源">
    <div className="grid gap-4">
      <HeroSelect label="来源类型" value={createType} onChange={setCreateType} options={[{ id: '', label: '请选择来源类型' }, ...definitions.map((definition: SourceTypeDefinition) => ({ id: definition.type, label: definition.label || definition.display_name || sourceTypeLabel(definition.type) }))]} />
      <Card variant="secondary" className="grid gap-3 p-3">
        <div>
          <Card.Title>找不到需要的社交来源？</Card.Title>
          <Card.Description className="mt-1">提交公开 Actor Route 支持检查；系统只生成候选提案，付费试跑仍需管理员逐次确认。</Card.Description>
        </div>
        <div className="grid gap-3 min-[560px]:grid-cols-[minmax(0,1fr)_auto] min-[560px]:items-end">
          <HeroSelect
            label="待检查 Profile"
            value={selectedSupportProfile?.id ?? ''}
            onChange={setSupportProfileId}
            isDisabled={supportCheckMutation.isPending || capabilitiesQuery.isError}
            options={supportProfiles.map((profile) => ({
              id: profile.id,
              label: profile.label,
              description: `${profile.platform}/${profile.target_type}/${profile.capability} · ${profile.mode}`,
            }))}
          />
          <Button
            type="button"
            variant="secondary"
            isDisabled={supportCheckMutation.isPending || !selectedSupportProfile}
            onPress={() => supportCheckMutation.mutate()}
          >{supportCheckMutation.isPending ? '提交中…' : '请求支持检查'}</Button>
        </div>
      </Card>
      {activeDefinition && (
        sourceDialogNeedsSecret && secretsQuery.isLoading
          ? <LoadingState label="正在读取可用 Key" rows={2} />
          : sourceDialogNeedsSecret && secretsQuery.isError
            ? <HeroNotice title="可用 Key 读取失败" status="warning">
                <Button size="sm" variant="ghost" className="ml-2" onPress={() => void secretsQuery.refetch()}>重试</Button>
              </HeroNotice>
            : <SourceForm
                key={activeDefinition.type}
                definition={activeDefinition}
                secrets={secretsQuery.data?.secrets ?? []}
                allowSecret={isAdmin && sourceUsesSecret(activeDefinition)}
                scopes={sourceScopesForUser(user)}
                taxonomy={taxonomy}
                submitLabel="创建并订阅"
                onSubmit={async (payload) => {
                  const created = await api.createSource(payload)
                  try {
                    const result = await api.subscribe(created.id)
                    const reused = result.subscription.reused_item_count ?? 0
                    actionToast.success('来源已创建并订阅', { description: reused > 0 ? `已复用 ${reused} 条已有内容。` : undefined })
                  } catch (caught) {
                    actionToast.danger('来源已创建，但订阅失败', { description: `${mutationError(caught)} 可在来源库中重试订阅。` })
                  }
                  await refreshCatalogAndContent()
                  setCreateOpen(false)
                  setCreateType('')
                }}
              />
      )}
    </div>
  </HeroDialog>
  <HeroDialog isOpen={Boolean(shareSource)} onOpenChange={(open) => !open && closeShareSource()} returnFocusRef={shareSourceReturnFocus} title={shareSource ? `分享 ${shareSource.display_name}` : '分享来源'}>
    <div className="grid gap-4">
      <HeroNotice title="分享后管理权将发生变化" status="warning">来源订阅地址和管理权会转交给工作区超级用户与管理员。你之后取消订阅只影响自己，不会删除其他成员正在使用的来源。</HeroNotice>
      <p className="type-body text-muted">分享后将成为公共订阅，所有成员都可以发现并订阅。</p>
      <Button isDisabled={shareMutation.isPending} onPress={() => shareSource && shareMutation.mutate({ source: shareSource, scope: 'public' })}>{shareMutation.isPending ? '分享中…' : '确认公开并转交管理权'}</Button>
    </div>
  </HeroDialog>
  </div>
}
