import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  ApifyActorAlertEvent,
  ApifyActorAlertSettings,
  ApifyActorAlertSettingsPatch,
  ApifyActorRoute,
  ApifyActorRouteCandidate,
  CatalogSource,
  NotificationChannel,
  NotificationService,
  NotificationTestResult,
  WebhookProvider,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Card,
  Checkbox,
  Description,
  Icons,
  LoadingState,
  Modal,
  StatusIndicator,
  Switch,
  Table,
} from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import {
  notificationDestinationError,
} from '../notifications/notificationModel'
import {
  NotificationChannelCards,
  type NotificationDestinationDrafts,
  type NotificationDestinationErrors,
} from '../notifications/NotificationChannelCards'
import {
  APIFY_ACTOR_ROUTE_REFRESH_MS,
  actorAlertEventLabels,
  actorCandidateStatePresentation,
  actorReasonLabel,
  actorRouteStatusPresentation,
  formatActorDateTime,
  formatActorPercent,
  formatActorUsd,
  formatEstimatedDays,
  safeActorActionError,
} from './apifyActorModel'
import { HeroActorOpsControlPlane } from './HeroActorOpsControlPlane'

const alertEvents = Object.keys(actorAlertEventLabels) as ApifyActorAlertEvent[]

function isXProfileSource(source: CatalogSource): boolean {
  if (!source.enabled || source.type !== 'apify_social') return false
  const config = source.config
  return config?.platform === 'x' && config?.kind === 'profile'
}

function routeIcon(status: ApifyActorRoute['status']) {
  if (status === 'ready') return <Icons.CircleCheck size={14} aria-hidden="true" />
  if (status === 'degraded') return <Icons.TriangleAlert size={14} aria-hidden="true" />
  return <Icons.CircleX size={14} aria-hidden="true" />
}

function candidateIcon(state: ApifyActorRouteCandidate['state']) {
  if (state === 'closed') return <Icons.CircleCheck size={13} aria-hidden="true" />
  if (state === 'open') return <Icons.CircleX size={13} aria-hidden="true" />
  if (state === 'disabled') return <Icons.CircleDashed size={13} aria-hidden="true" />
  return <Icons.TriangleAlert size={13} aria-hidden="true" />
}

function RouteMetric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3">
    <p className="type-meta text-muted">{label}</p>
    <p className="type-page-title mt-1 tabular-nums">{value}</p>
    {detail && <p className="type-meta mt-1 text-muted">{detail}</p>}
  </div>
}

function ActorCandidateTable({
  route,
  actionPending,
  onMove,
  onToggle,
  onCanary,
  registerCanaryTrigger,
}: {
  route: ApifyActorRoute
  actionPending: boolean
  onMove: (candidateId: string, offset: -1 | 1) => void
  onToggle: (candidate: ApifyActorRouteCandidate, action: 'enable' | 'disable') => void
  onCanary: (candidate: ApifyActorRouteCandidate) => void
  registerCanaryTrigger: (candidateId: string, node: HTMLButtonElement | null) => void
}) {
  const candidates = [...route.candidates].sort((left, right) => left.position - right.position)

  return <Table variant="secondary" className="max-w-full">
    <Table.ScrollContainer className="max-w-full overflow-x-auto" data-testid="apify-actor-route-scroll">
      <Table.Content aria-label="X 抓取主备 Actor">
        <Table.Header>
          <Table.Column>顺序</Table.Column>
          <Table.Column isRowHeader>Actor 与状态</Table.Column>
          <Table.Column>稳定性</Table.Column>
          <Table.Column>标价与实际费用</Table.Column>
          <Table.Column>恢复时间</Table.Column>
          <Table.Column>操作</Table.Column>
        </Table.Header>
        <Table.Body
          items={candidates}
          renderEmptyState={() => <div className="p-6 text-center text-muted">尚未配置 X 抓取 Actor</div>}
        >
          {(candidate) => {
            const index = candidates.findIndex((item) => item.id === candidate.id)
            const state = actorCandidateStatePresentation[candidate.state]
            const active = candidate.id === route.active_candidate_id
            return <Table.Row id={candidate.id}>
              <Table.Cell>
                <div className="flex min-w-24 items-center gap-1">
                  <span className="type-control w-5 text-center tabular-nums">{index + 1}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    isIconOnly
                    aria-label={`上移 ${candidate.display_name}`}
                    isDisabled={actionPending || index === 0}
                    onPress={() => onMove(candidate.id, -1)}
                  ><Icons.ArrowUp size={14} aria-hidden="true" /></Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    isIconOnly
                    aria-label={`下移 ${candidate.display_name}`}
                    isDisabled={actionPending || index === candidates.length - 1}
                    onPress={() => onMove(candidate.id, 1)}
                  ><Icons.ArrowDown size={14} aria-hidden="true" /></Button>
                </div>
              </Table.Cell>
              <Table.Cell>
                <div className="min-w-60">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="type-control">{candidate.display_name}</p>
                    {active && <span className="type-meta text-accent">当前使用</span>}
                  </div>
                  <code className="type-meta mt-1 block break-all text-muted">{candidate.actor_public_name}</code>
                  <div className="mt-2">
                    <StatusIndicator
                      label={state.label}
                      tone={state.tone}
                      icon={candidateIcon(candidate.state)}
                    />
                  </div>
                </div>
              </Table.Cell>
              <Table.Cell>
                <div className="min-w-52">
                  <p className="type-control tabular-nums">24 小时成功率 {formatActorPercent(candidate.success_rate_24h)}</p>
                  <p className="type-meta mt-1 text-muted">最近成功 {formatActorDateTime(candidate.last_success_at)}</p>
                  <p className="type-meta mt-1 text-muted">最近失败 {formatActorDateTime(candidate.last_failure_at)}</p>
                  {candidate.last_error_code && <p className="type-meta mt-1 text-warning">
                    {actorReasonLabel(candidate.last_error_code)}
                  </p>}
                </div>
              </Table.Cell>
              <Table.Cell>
                <div className="min-w-56">
                  <p className="type-control tabular-nums">
                    {candidate.paid_plan_listed_price_usd_per_1000 != null
                      ? 'Apify Free 约'
                      : '页面标价'}{' '}
                    {formatActorUsd(candidate.listed_price_usd_per_1000)} / 千条
                  </p>
                  {candidate.paid_plan_listed_price_usd_per_1000 != null && (
                    <p className="type-meta mt-1 text-muted tabular-nums">
                      Apify 付费计划约 {formatActorUsd(candidate.paid_plan_listed_price_usd_per_1000)} / 千条
                    </p>
                  )}
                  <p className="type-meta mt-1 text-muted tabular-nums">
                    最近一次 {formatActorUsd(candidate.last_charge_usd, true)}
                  </p>
                  <p className="type-meta mt-1 text-muted tabular-nums">
                    24 小时平均 {formatActorUsd(candidate.avg_charge_24h_usd, true)}
                  </p>
                  <p className="type-meta mt-1 text-muted">费用判断以实际账单为准</p>
                </div>
              </Table.Cell>
              <Table.Cell>
                <div className="min-w-40">
                  <p className="type-control">{candidate.retry_at ? formatActorDateTime(candidate.retry_at) : '无需等待'}</p>
                  <p className="type-meta mt-1 text-muted">
                    {candidate.retry_at ? '到期后由自然任务探测' : '当前不在冷却期'}
                  </p>
                </div>
              </Table.Cell>
              <Table.Cell>
                <div className="flex min-w-52 flex-wrap gap-2">
                  {candidate.can_enable && <Button
                    size="sm"
                    variant="secondary"
                    isDisabled={actionPending}
                    onPress={() => onToggle(candidate, 'enable')}
                  >启用</Button>}
                  {candidate.can_disable && <Button
                    size="sm"
                    variant="ghost"
                    isDisabled={actionPending}
                    onPress={() => onToggle(candidate, 'disable')}
                  >禁用</Button>}
                  <Button
                    ref={(node) => registerCanaryTrigger(candidate.id, node)}
                    size="sm"
                    variant="secondary"
                    isDisabled={actionPending || !candidate.can_canary}
                    onPress={() => onCanary(candidate)}
                  ><Icons.FlaskConical size={14} aria-hidden="true" />付费试跑</Button>
                </div>
              </Table.Cell>
            </Table.Row>
          }}
        </Table.Body>
      </Table.Content>
    </Table.ScrollContainer>
  </Table>
}

/** @deprecated Kept for the one-version x/profile compatibility surface. */
export function ApifyActorRoutePanel({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const canaryTriggerRefs = useRef(new Map<string, HTMLButtonElement>())
  const pendingCanaryFocusId = useRef<string | null>(null)
  const [canaryCandidate, setCanaryCandidate] = useState<ApifyActorRouteCandidate | null>(null)
  const [canarySourceId, setCanarySourceId] = useState('')
  const [canaryError, setCanaryError] = useState('')
  const routeQuery = useQuery({
    queryKey: queryKeys.apifyActorXProfileRoute(user.id),
    queryFn: ({ signal }) => api.apifyActorXProfileRoute(signal),
    enabled: queryEnabled,
    retry: false,
    refetchInterval: queryEnabled ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })
  const canarySources = useQuery({
    queryKey: queryKeys.sources(user.id),
    queryFn: ({ signal }) => api.sources(false, signal),
    enabled: queryEnabled && Boolean(canaryCandidate),
    staleTime: queryStaleTime.catalog,
    retry: false,
  })
  const xProfileSources = useMemo(
    () => (canarySources.data?.sources ?? []).filter(isXProfileSource),
    [canarySources.data],
  )
  const orderMutation = useMutation({
    mutationFn: ({ candidateIds, expectedGeneration }: {
      candidateIds: string[]
      expectedGeneration: number
    }) => api.reorderApifyActorXProfileRoute(candidateIds, expectedGeneration),
    onSuccess: (route) => {
      queryClient.setQueryData(queryKeys.apifyActorXProfileRoute(user.id), route)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorAlertIncidents(user.id) })
      actionToast.success('Actor 顺序已更新')
    },
    onError: (caught) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorXProfileRoute(user.id) })
      actionToast.danger('Actor 顺序更新失败', {
        description: safeActorActionError(caught, 'Actor 顺序更新失败，请稍后重试。'),
      })
    },
  })
  const toggleMutation = useMutation({
    mutationFn: ({ candidate, action, expectedGeneration }: {
      candidate: ApifyActorRouteCandidate
      action: 'enable' | 'disable'
      expectedGeneration: number
    }) => action === 'enable'
      ? api.enableApifyActorXProfileCandidate(candidate.id, expectedGeneration)
      : api.disableApifyActorXProfileCandidate(candidate.id, expectedGeneration),
    onSuccess: (route, variables) => {
      queryClient.setQueryData(queryKeys.apifyActorXProfileRoute(user.id), route)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorAlertIncidents(user.id) })
      actionToast.success(variables.action === 'enable' ? 'Actor 已启用' : 'Actor 已禁用', {
        description: variables.candidate.display_name,
      })
    },
    onError: (caught) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorXProfileRoute(user.id) })
      actionToast.danger('Actor 状态更新失败', {
        description: safeActorActionError(caught, 'Actor 状态更新失败，请稍后重试。'),
      })
    },
  })
  const canaryMutation = useMutation({
    mutationFn: ({ candidateId, sourceId, expectedGeneration }: {
      candidateId: string
      sourceId: string
      expectedGeneration: number
    }) => api.canaryApifyActorXProfileCandidate(
      candidateId,
      sourceId,
      expectedGeneration,
      '确认付费试跑',
    ),
    onSuccess: (route) => {
      queryClient.setQueryData(queryKeys.apifyActorXProfileRoute(user.id), route)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorAlertIncidents(user.id) })
      closeCanary()
      actionToast.success('Actor 付费试跑已提交')
    },
    onError: (caught) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorXProfileRoute(user.id) })
      setCanaryError(safeActorActionError(caught, 'Actor 付费试跑失败，请稍后重试。'))
    },
  })
  const route = routeQuery.data
  const actionPending = orderMutation.isPending || toggleMutation.isPending || canaryMutation.isPending

  useEffect(() => {
    if (canaryCandidate || canaryMutation.isPending || !pendingCanaryFocusId.current) return
    let secondFrame: number | undefined
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        const candidateId = pendingCanaryFocusId.current
        const trigger = candidateId ? canaryTriggerRefs.current.get(candidateId) : null
        if (trigger && !trigger.disabled) {
          trigger.focus()
          pendingCanaryFocusId.current = null
        }
      })
    })
    return () => {
      window.cancelAnimationFrame(firstFrame)
      if (secondFrame !== undefined) window.cancelAnimationFrame(secondFrame)
    }
  }, [canaryCandidate, canaryMutation.isPending])

  function closeCanary() {
    const candidateId = canaryCandidate?.id
    if (candidateId) pendingCanaryFocusId.current = candidateId
    setCanaryCandidate(null)
    setCanarySourceId('')
    setCanaryError('')
  }

  function moveCandidate(candidateId: string, offset: -1 | 1) {
    if (!route || actionPending) return
    const candidates = [...route.candidates].sort((left, right) => left.position - right.position)
    const index = candidates.findIndex((candidate) => candidate.id === candidateId)
    const target = index + offset
    if (index < 0 || target < 0 || target >= candidates.length) return
    const reordered = [...candidates]
    const [moving] = reordered.splice(index, 1)
    reordered.splice(target, 0, moving)
    orderMutation.mutate({
      candidateIds: reordered.map((candidate) => candidate.id),
      expectedGeneration: route.generation,
    })
  }

  function openCanary(candidate: ApifyActorRouteCandidate) {
    if (actionPending || !candidate.can_canary) return
    setCanaryCandidate(candidate)
    setCanarySourceId('')
    setCanaryError('')
  }

  function submitCanary() {
    if (!route || !canaryCandidate || !canarySourceId || canaryMutation.isPending) return
    setCanaryError('')
    canaryMutation.mutate({
      candidateId: canaryCandidate.id,
      sourceId: canarySourceId,
      expectedGeneration: route.generation,
    })
  }

  return <>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <Card.Title>X 抓取主备</Card.Title>
        <Card.Description className="mt-1">
          只使用 Apify；按健康状态和管理员顺序选择 Actor，故障时串行切换。
        </Card.Description>
      </div>
      {route && <StatusIndicator
        label={actorRouteStatusPresentation[route.status].label}
        tone={actorRouteStatusPresentation[route.status].tone}
        icon={routeIcon(route.status)}
      />}
    </div>

    {routeQuery.isPending && <div className="mt-4"><LoadingState label="正在读取 X Actor 路由" rows={2} /></div>}
    {routeQuery.isError && <div className="mt-4"><HeroNotice title="X Actor 路由读取失败" status="warning">
      <Button size="sm" variant="ghost" isDisabled={routeQuery.isFetching} onPress={() => void routeQuery.refetch()}>
        {routeQuery.isFetching ? '重试中…' : '重试此区域'}
      </Button>
    </HeroNotice></div>}

    {route && <>
      <div className="mt-4 grid gap-3 min-[720px]:grid-cols-2 min-[1080px]:grid-cols-4">
        <RouteMetric
          label="Apify 总剩余额度"
          value={formatActorUsd(route.quota.total_remaining_usd)}
          detail={`更新于 ${formatActorDateTime(route.quota.as_of)}`}
        />
        <RouteMetric
          label="X 可使用额度"
          value={formatActorUsd(route.quota.x_allocatable_usd)}
          detail="已保留其他 Apify 来源所需额度"
        />
        <RouteMetric
          label="近 24 小时实际消费"
          value={formatActorUsd(route.quota.spend_24h_usd)}
          detail={`单次最高 ${formatActorUsd(route.limits.per_run_usd)}`}
        />
        <RouteMetric
          label="预计可运行"
          value={formatEstimatedDays(route.quota.estimated_days_remaining)}
          detail={`单任务预留上限 ${formatActorUsd(route.limits.per_job_usd)}`}
        />
      </div>

      <div className="mt-4 rounded-control border border-separator bg-surface-secondary p-3">
        <p className="type-control">
          {route.active_candidate_id
            ? `当前使用：${route.candidates.find((candidate) => candidate.id === route.active_candidate_id)?.display_name ?? '状态更新中'}`
            : '当前没有可用 Actor'}
        </p>
        <p className="type-meta mt-1 text-muted">
          最近切换：{actorReasonLabel(route.last_switch_reason)} · {formatActorDateTime(route.last_switch_at)}
        </p>
        {route.retry_at && <p className="type-meta mt-1 text-warning">
          预计恢复探测：{formatActorDateTime(route.retry_at)}
        </p>}
        {route.blocked_reason && <p className="type-meta mt-1 text-danger">
          {actorReasonLabel(route.blocked_reason)}
        </p>}
      </div>

      <div className="mt-4 min-w-0 max-w-full" aria-busy={actionPending || routeQuery.isFetching}>
        <ActorCandidateTable
          route={route}
          actionPending={actionPending}
          onMove={moveCandidate}
          onToggle={(candidate, action) => {
            if (actionPending) return
            toggleMutation.mutate({ candidate, action, expectedGeneration: route.generation })
          }}
          onCanary={openCanary}
          registerCanaryTrigger={(candidateId, node) => {
            if (node) canaryTriggerRefs.current.set(candidateId, node)
            else canaryTriggerRefs.current.delete(candidateId)
          }}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="type-meta text-muted">
          标价只用于参考；请结合真实费用和稳定性调整顺序。失败费用 6 小时上限 {formatActorUsd(route.limits.failed_spend_6h_usd)}。
        </p>
        <Button
          size="sm"
          variant="ghost"
          isDisabled={routeQuery.isFetching}
          onPress={() => void routeQuery.refetch()}
        ><Icons.RefreshCw
          size={14}
          className={routeQuery.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}
          aria-hidden="true"
        />{routeQuery.isFetching ? '刷新中…' : '刷新状态'}</Button>
      </div>
    </>}

    <Modal isOpen={Boolean(canaryCandidate)} onOpenChange={(open) => {
      if (!open && !canaryMutation.isPending) closeCanary()
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开 Actor 付费试跑</Modal.Trigger>
      <Modal.Backdrop isDismissable={!canaryMutation.isPending} isKeyboardDismissDisabled={canaryMutation.isPending}>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>{`付费试跑 ${canaryCandidate?.display_name ?? 'Actor'}`}</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-4" aria-busy={canaryMutation.isPending}>
                <HeroNotice title="此操作会产生一次 Apify 调用" status="warning" role="status">
                  单次最高费用为 {formatActorUsd(route?.limits.per_run_usd ?? null)}。请选择一个当前工作区的 X Profile 来源；不会并行调用其他 Actor。
                </HeroNotice>
                {canarySources.isPending && <LoadingState label="正在读取可试跑的 X 来源" rows={1} />}
                {canarySources.isError && <HeroNotice title="X 来源读取失败" status="warning">
                  <Button size="sm" variant="ghost" onPress={() => void canarySources.refetch()}>重试来源读取</Button>
                </HeroNotice>}
                {!canarySources.isPending && !canarySources.isError && xProfileSources.length === 0 && <HeroNotice
                  title="没有可用于试跑的 X Profile 来源"
                  status="warning"
                  role="status"
                >
                  请先在订阅页配置并启用一个 X Profile 来源。
                </HeroNotice>}
                {xProfileSources.length > 0 && <HeroSelect
                  label="试跑 X 来源"
                  value={canarySourceId}
                  onChange={(value) => {
                    setCanarySourceId(value)
                    setCanaryError('')
                  }}
                  options={xProfileSources.map((source) => ({ id: source.id, label: source.display_name }))}
                  description="只向服务端提交来源 ID；不会显示原始来源配置或 Actor 运行标识。"
                />}
                {canaryError && <HeroNotice title={canaryError} />}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={canaryMutation.isPending} onPress={closeCanary}>取消</Button>
              <Button
                type="button"
                isDisabled={!canarySourceId || canaryMutation.isPending}
                onPress={submitCanary}
              >{canaryMutation.isPending ? '提交中…' : '确认付费试跑'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </>
}

function lastAlertLabel(
  status: string | null,
  channel: NotificationChannel,
  verificationMode: 'http_status' | 'provider_response',
): string {
  if (!status) return '尚未发送运行告警'
  if (status === 'sent' || status === 'succeeded' || status === 'success') {
    if (channel === 'email') return '最近一次运行告警邮件已发送'
    if (channel === 'telegram') return '最近一次 Telegram 运行告警已发送'
    if (verificationMode === 'provider_response') return '最近一次运行告警已获平台接受'
    return '最近一次运行告警请求已发送，请确认接收端'
  }
  if (status === 'failed' || status === 'failure') return '最近一次运行告警发送失败'
  if (status === 'unknown') return '最近一次运行告警结果未知，不会自动重发'
  return '最近一次运行告警正在处理'
}

const emptyAlertDestinations = (): NotificationDestinationDrafts => ({
  email: '',
  webhook: '',
  telegram: '',
})

function sameAlertChannels(left: NotificationChannel[], right: NotificationChannel[]): boolean {
  return left.length === right.length && left.every((channel, index) => channel === right[index])
}

export function ApifyActorAlertSettingsForm({
  settings,
  onSave,
  onTest,
}: {
  settings: ApifyActorAlertSettings
  onSave: (patch: ApifyActorAlertSettingsPatch) => Promise<ApifyActorAlertSettings>
  onTest: (channel: NotificationChannel) => Promise<NotificationTestResult>
}) {
  const webhookState = settings.channel_states.webhook
  const [enabled, setEnabled] = useState(settings.enabled)
  const [channels, setChannels] = useState<NotificationChannel[]>(settings.channels)
  const [events, setEvents] = useState<ApifyActorAlertEvent[]>(settings.events)
  const [destinations, setDestinations] = useState<NotificationDestinationDrafts>(emptyAlertDestinations)
  const [webhookProvider, setWebhookProvider] = useState<WebhookProvider>(webhookState.provider)
  const [providerTouched, setProviderTouched] = useState(false)
  const [signingEnabled, setSigningEnabled] = useState(webhookState.signing_secret_configured)
  const [signingSecret, setSigningSecret] = useState('')
  const [errors, setErrors] = useState<NotificationDestinationErrors>({})
  const [eventError, setEventError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testingChannel, setTestingChannel] = useState<NotificationChannel | null>(null)
  const eventsDirty = [...events].sort().join(':') !== [...settings.events].sort().join(':')
  const signingDirty = signingEnabled !== webhookState.signing_secret_configured
    || Boolean(signingSecret.trim())
  const dirty = enabled !== settings.enabled
    || !sameAlertChannels(channels, settings.channels)
    || eventsDirty
    || Object.values(destinations).some((value) => Boolean(value.trim()))
    || providerTouched
    || signingDirty
  const busy = saving || testingChannel !== null

  function channelDirty(channel: NotificationChannel): boolean {
    if (channels.includes(channel) !== settings.channel_states[channel].enabled) return true
    if (destinations[channel].trim()) return true
    return channel === 'webhook' && (providerTouched || signingDirty)
  }

  function setDestination(channel: NotificationChannel, value: string) {
    setDestinations((current) => ({ ...current, [channel]: value }))
    setErrors((current) => ({ ...current, [channel]: undefined }))
    setRequestError('')
  }

  function toggleChannel(channel: NotificationChannel, selected: boolean) {
    setChannels((current) => selected
      ? current.includes(channel) ? current : [...current, channel]
      : current.filter((item) => item !== channel))
    setErrors((current) => ({ ...current, [channel]: undefined }))
    setRequestError('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const submittedDestinations = {
      email: destinations.email.trim(),
      webhook: destinations.webhook.trim(),
      telegram: destinations.telegram.trim(),
    }
    const submittedSigningSecret = signingSecret.trim()
    setDestinations(emptyAlertDestinations())
    setSigningSecret('')
    setErrors({})
    setEventError('')
    setRequestError('')
    if (enabled && events.length === 0) {
      setEventError('启用运行告警时，请至少选择一种告警事件。')
      return
    }
    if (enabled && channels.length === 0) {
      setRequestError('启用 Apify 运行告警时，请至少选择一种告警渠道。')
      return
    }
    const nextErrors: NotificationDestinationErrors = {}
    for (const channel of ['email', 'webhook', 'telegram'] as const) {
      const configured = channel === 'webhook'
        ? webhookState.configured
          && webhookProvider === webhookState.provider
          && !providerTouched
        : settings.channel_states[channel].configured
      if (channels.includes(channel) || submittedDestinations[channel]) {
        const error = notificationDestinationError({
          channel,
          destination: submittedDestinations[channel],
          configured,
          enabled: channels.includes(channel),
        })
        if (error) nextErrors[channel] = error
      }
    }
    if (
      channels.includes('webhook')
      && !webhookState.provider_explicit
      && (providerTouched || submittedDestinations.webhook)
      && !submittedDestinations.webhook
    ) {
      nextErrors.webhook = '升级旧 Webhook 配置时，请选择类型并重新输入对应地址。'
    }
    if (providerTouched && !submittedDestinations.webhook) {
      nextErrors.webhook = '选择或更换 Webhook 类型时，请重新输入对应地址。'
    }
    const signingConfigured = webhookState.signing_secret_configured
      && webhookProvider === webhookState.provider
      && !providerTouched
    if (
      signingEnabled
      && !signingConfigured
      && !submittedSigningSecret
    ) {
      nextErrors.signing = '启用签名校验时需要填写签名 Secret。'
    }
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }
    setSaving(true)
    try {
      await onSave({
        enabled,
        channels,
        events,
        ...(submittedDestinations.email ? { email_address: submittedDestinations.email } : {}),
        ...(submittedDestinations.webhook ? { webhook_url: submittedDestinations.webhook } : {}),
        ...(submittedDestinations.telegram ? { telegram_chat_id: submittedDestinations.telegram } : {}),
        ...(providerTouched || submittedDestinations.webhook ? { webhook_provider: webhookProvider } : {}),
        ...(submittedSigningSecret ? { webhook_signing_secret: submittedSigningSecret } : {}),
        ...(!signingEnabled
          && webhookState.signing_secret_configured
          ? { webhook_signing_secret: null }
          : {}),
      })
      actionToast.success('Apify 运行告警设置已保存')
    } catch (caught) {
      const message = safeActorActionError(caught, 'Apify 运行告警设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('Apify 运行告警设置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function sendTest(channel: NotificationChannel) {
    if (busy || channelDirty(channel)) return
    setTestingChannel(channel)
    setRequestError('')
    try {
      const result = await onTest(channel)
      if (result.channel === 'email') {
        actionToast.success('测试运行告警邮件已发送', {
          description: '请检查当前告警收件邮箱。',
        })
      } else if (result.channel === 'telegram') {
        actionToast.success('Telegram 测试运行告警已发送', {
          description: '请检查当前告警目标会话。',
        })
      } else {
        actionToast.success(
          result.verification === 'provider_accepted' ? '平台已接受测试运行告警' : '测试运行告警请求已发送',
          {
            description: result.verification === 'provider_accepted'
              ? '平台业务响应已通过，请确认接收端实际展示。'
              : '接收端已返回 HTTP 成功状态，请确认实际处理。',
          },
        )
      }
    } catch (caught) {
      const message = safeActorActionError(caught, '测试运行告警发送失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('测试运行告警发送失败', { description: message })
    } finally {
      setTestingChannel(null)
    }
  }

  return <form className="grid min-w-0 gap-4" noValidate onSubmit={save}>
    <div className="grid gap-1">
      <Switch isSelected={enabled} onChange={(value) => {
        setEnabled(value)
        setEventError('')
        setRequestError('')
      }}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用 Apify 运行告警</Switch.Content>
      </Switch>
      <Description>只报告 Actor 切换、额度、费用保护和恢复；可同时选择多个渠道。</Description>
    </div>

    <NotificationChannelCards
      idPrefix="apify-alert"
      settings={settings}
      selectedChannels={channels}
      destinations={destinations}
      webhookProvider={webhookProvider}
      providerTouched={providerTouched}
      signingEnabled={signingEnabled}
      signingSecret={signingSecret}
      errors={errors}
      readOnly={false}
      busy={busy}
      testingChannel={testingChannel}
      channelDirty={channelDirty}
      destinationNoun="告警"
      onChannelChange={toggleChannel}
      onDestinationChange={setDestination}
      onProviderChange={(provider) => {
        setWebhookProvider(provider)
        setProviderTouched(provider !== webhookState.provider || !webhookState.provider_explicit)
        setDestinations((current) => ({ ...current, webhook: '' }))
        setSigningEnabled(false)
        setSigningSecret('')
        setErrors((current) => ({ ...current, webhook: undefined, signing: undefined }))
        setRequestError('')
      }}
      onSigningEnabledChange={(value) => {
        setSigningEnabled(value)
        if (!webhookState.provider_explicit) setProviderTouched(true)
        setSigningSecret('')
        setErrors((current) => ({ ...current, signing: undefined }))
        setRequestError('')
      }}
      onSigningSecretChange={(value) => {
        setSigningSecret(value)
        setErrors((current) => ({ ...current, signing: undefined }))
        setRequestError('')
      }}
      onTest={(channel) => void sendTest(channel)}
    />

    <fieldset className="grid gap-3" aria-describedby="apify-actor-alert-events-help">
      <legend className="type-control">告警事件</legend>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {alertEvents.map((event) => <Checkbox
          key={event}
          isSelected={events.includes(event)}
          onChange={(selected) => {
            setEvents((current) => selected
              ? [...current, event]
              : current.filter((item) => item !== event))
            setEventError('')
            setRequestError('')
          }}
        >
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{actorAlertEventLabels[event]}</Checkbox.Content>
        </Checkbox>)}
      </div>
      <Description id="apify-actor-alert-events-help">同一故障只首报一次；状态恢复后再发送一条恢复通知。</Description>
      {eventError && <p className="type-meta text-danger" role="alert">{eventError}</p>}
    </fieldset>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      <p>每个渠道独立配置、测试与投递；一个渠道暂停或失败不会阻断其他渠道或抓取任务。</p>
      <p className="mt-1">测试告警使用模拟内容，不会抓取 X、调用 Actor 或产生 Apify 费用。</p>
      <p className="type-meta mt-1">
        {lastAlertLabel(
          settings.last_alert_status,
          settings.channel,
          settings.webhook_verification_mode,
        )} · {formatActorDateTime(settings.last_alerted_at)}
      </p>
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={busy || !dirty}>{saving ? '保存中…' : '保存运行告警'}</Button>
    </div>
  </form>
}

function ApifyActorAlertSettingsPanel({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: queryKeys.apifyActorAlertSettings(user.id),
    queryFn: ({ signal }) => api.apifyActorAlertSettings(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
    retry: false,
    refetchInterval: queryEnabled ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })
  const services = useQuery({
    queryKey: queryKeys.notificationServices(user.id),
    queryFn: ({ signal }) => api.notificationServices(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })

  if (settings.isPending || services.isPending) return <LoadingState label="正在读取 Apify 运行告警设置" rows={2} />
  if (settings.isError || services.isError || !settings.data || !services.data) return <HeroNotice title="Apify 运行告警设置读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void settings.refetch()}>重试此区域</Button>
  </HeroNotice>

  const sharedTargets = services.data.services.filter((service) => service.scope === 'shared')
  const cacheKey = [
    settings.data.enabled,
    settings.data.target_ids.join(':'),
    settings.data.events.join(':'),
    sharedTargets.map((target) => `${target.id}:${target.available}:${target.config_generation}`).join('|'),
    settings.data.last_alerted_at,
  ].join(':')

  async function save(patch: ApifyActorAlertSettingsPatch) {
    const updated = await api.updateApifyActorAlertSettings(patch)
    queryClient.setQueryData(queryKeys.apifyActorAlertSettings(user.id), updated)
    return updated
  }

  return <ApifyTargetSelectionForm
    key={cacheKey}
    settings={settings.data}
    targets={sharedTargets}
    onSave={save}
  />
}

function ApifyTargetSelectionForm({
  settings,
  targets,
  onSave,
}: {
  settings: ApifyActorAlertSettings
  targets: NotificationService[]
  onSave: (patch: ApifyActorAlertSettingsPatch) => Promise<ApifyActorAlertSettings>
}) {
  const [enabled, setEnabled] = useState(settings.enabled)
  const [targetIds, setTargetIds] = useState(settings.target_ids)
  const [events, setEvents] = useState(settings.events)
  const [saving, setSaving] = useState(false)
  const [requestError, setRequestError] = useState('')
  const dirty = enabled !== settings.enabled
    || targetIds.length !== settings.target_ids.length
    || targetIds.some((id, index) => id !== settings.target_ids[index])
    || [...events].sort().join(':') !== [...settings.events].sort().join(':')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving || !dirty) return
    if (enabled && targetIds.length === 0) {
      setRequestError('启用运行告警时，请至少选择一个工作区共享通知服务。')
      return
    }
    if (enabled && events.length === 0) {
      setRequestError('启用运行告警时，请至少选择一种告警事件。')
      return
    }
    setSaving(true)
    setRequestError('')
    try {
      await onSave({ enabled, target_ids: targetIds, events })
      actionToast.success('Apify 运行告警设置已保存')
    } catch (caught) {
      const message = safeActorActionError(caught, 'Apify 运行告警设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('Apify 运行告警设置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  return <form className="grid min-w-0 gap-4" noValidate onSubmit={save}>
    <div className="grid gap-1">
      <Switch isSelected={enabled} onChange={(value) => {
        setEnabled(value)
        setRequestError('')
      }}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用 Apify 运行告警</Switch.Content>
      </Switch>
      <Description>系统告警只能选择工作区共享通知服务；接收地址、共享凭据和测试统一在“消息通知”中完成。</Description>
    </div>
    <fieldset className="grid gap-3">
      <legend className="type-control">共享通知服务</legend>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {targets.map((target) => <Card key={target.id} className="grid gap-2 p-3">
          <Checkbox
            isSelected={targetIds.includes(target.id)}
            isDisabled={!target.available && !targetIds.includes(target.id)}
            onChange={(selected) => {
              setTargetIds((current) => selected
                ? current.includes(target.id) ? current : [...current, target.id]
                : current.filter((id) => id !== target.id))
              setRequestError('')
            }}
          >
            <Checkbox.Content>
              <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
              {target.name}
            </Checkbox.Content>
          </Checkbox>
          <Card.Description>
            {target.channel === 'email' ? '邮箱' : target.channel === 'telegram' ? 'Telegram' : 'Webhook'}
            {' · '}{target.available
              ? '可用'
              : target.enabled
                ? '暂不可用，不能新选择'
                : '已暂停，不能新选择'}
          </Card.Description>
        </Card>)}
      </div>
      {targets.length === 0 && <HeroNotice title="没有工作区共享通知服务" status="warning">
        <a className="underline" href="#settings-notifications">前往消息通知创建通知服务</a>
      </HeroNotice>}
    </fieldset>
    <fieldset className="grid gap-3" aria-describedby="apify-target-events-help">
      <legend className="type-control">告警事件</legend>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {alertEvents.map((alertEvent) => <Checkbox
          key={alertEvent}
          isSelected={events.includes(alertEvent)}
          onChange={(selected) => {
            setEvents((current) => selected
              ? current.includes(alertEvent) ? current : [...current, alertEvent]
              : current.filter((item) => item !== alertEvent))
            setRequestError('')
          }}
        >
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{actorAlertEventLabels[alertEvent]}</Checkbox.Content>
        </Checkbox>)}
      </div>
      <Description id="apify-target-events-help">同一故障只首报一次；状态恢复后按原目标发送恢复通知。</Description>
    </fieldset>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      <p>任一目标失败不会阻断其他目标或原抓取任务；结果未知的投递不会自动重放。</p>
      <p className="type-meta mt-1">
        {lastAlertLabel(
          settings.last_alert_status,
          settings.channel,
          settings.webhook_verification_mode,
        )} · {formatActorDateTime(settings.last_alerted_at)}
      </p>
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={saving || !dirty}>{saving ? '保存中…' : '保存运行告警'}</Button>
    </div>
  </form>
}

function incidentDeliveryLabel(status: string | null): string {
  if (!status) return '未触发投递'
  if (status === 'sent') return '已发送'
  if (status === 'failed') return '发送失败'
  if (status === 'unknown') return '结果未知，不自动重发'
  if (status === 'partial') return '部分渠道发送失败'
  if (status === 'skipped') return '已按设置跳过'
  return '等待发送'
}

function ApifyActorIncidentList({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const incidents = useQuery({
    queryKey: queryKeys.apifyActorAlertIncidents(user.id),
    queryFn: ({ signal }) => api.apifyActorAlertIncidents(signal),
    enabled: queryEnabled,
    retry: false,
    refetchInterval: queryEnabled ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })

  if (incidents.isPending) return <LoadingState label="正在读取 Actor 事件" rows={2} />
  if (incidents.isError || !incidents.data) return <HeroNotice title="最近 Actor 事件读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void incidents.refetch()}>重试此区域</Button>
  </HeroNotice>
  const rows = incidents.data.incidents.slice(0, 20)
  if (rows.length === 0) return <p className="type-meta text-muted">尚无切换、熔断、费用保护或恢复记录。</p>

  return <ol className="grid gap-2" aria-label="最近 Actor 事件">
    {rows.map((incident) => <li
      key={incident.id}
      className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="type-control">{actorAlertEventLabels[incident.event_type]}</p>
          <p className="type-meta mt-1 break-words text-muted">
            {incident.actor_name ? `涉及 ${incident.actor_name}` : '工作区 X 抓取路线'}
            {incident.active_actor_name ? ` · 当前 ${incident.active_actor_name}` : ''}
          </p>
        </div>
        <StatusIndicator
          label={incident.status === 'resolved' ? '已恢复' : incident.severity === 'critical' ? '需要处理' : '持续观察'}
          tone={incident.status === 'resolved' ? 'success' : incident.severity === 'critical' ? 'danger' : 'warning'}
          icon={incident.status === 'resolved'
            ? <Icons.CircleCheck size={13} aria-hidden="true" />
            : <Icons.TriangleAlert size={13} aria-hidden="true" />}
        />
      </div>
      <p className="type-meta mt-2 text-muted">{actorReasonLabel(incident.reason_code)}</p>
      <p className="type-meta mt-1 text-muted">
        <time dateTime={incident.opened_at}>发生于 {formatActorDateTime(incident.opened_at)}</time>
        {incident.resolved_at && <> · <time dateTime={incident.resolved_at}>恢复于 {formatActorDateTime(incident.resolved_at)}</time></>}
        {' · '}{incidentDeliveryLabel(incident.delivery_status)}
      </p>
      {(incident.deliveries ?? []).length > 0 && <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1" aria-label="逐渠道投递状态">
        {(incident.deliveries ?? []).map((delivery) => <li
          key={`${delivery.event_type}:${delivery.target_id ?? delivery.channel}`}
          className="type-meta text-muted"
        >
          {delivery.target_name ?? (delivery.channel === 'email' ? '邮箱' : delivery.channel === 'webhook' ? 'Webhook' : 'Telegram')}
          {' · '}{incidentDeliveryLabel(delivery.status)}
        </li>)}
      </ul>}
    </li>)}
  </ol>
}

export function HeroApifyActorRouteSettings({ queryEnabled = true }: { queryEnabled?: boolean }) {
  return <Card variant="secondary" className="min-w-0 max-w-full p-4">
    <HeroActorOpsControlPlane queryEnabled={queryEnabled} />
    <div className="mt-6 border-t border-separator pt-5">
      <h3 className="type-page-title">故障告警</h3>
      <p className="type-meta mt-1 text-muted">从工作区共享通知服务中多选；服务只需统一配置和测试一次。</p>
      <div className="mt-4"><ApifyActorAlertSettingsPanel queryEnabled={queryEnabled} /></div>
    </div>
    <div className="mt-6 border-t border-separator pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="type-page-title">最近事件</h3>
        <span className="type-meta text-muted">最多显示 20 条</span>
      </div>
      <div className="mt-3"><ApifyActorIncidentList queryEnabled={queryEnabled} /></div>
    </div>
  </Card>
}
