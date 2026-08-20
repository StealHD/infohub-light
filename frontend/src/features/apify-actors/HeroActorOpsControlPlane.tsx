import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type {
  ApifyActorDiagnosticEvents,
  ApifyActorCanaryBatch,
  ApifyActorCanaryPlan,
  ApifyActorDiscoverySettingsPatch,
  ApifyActorPoolCandidate,
  ApifyActorPoolGoal,
  ApifyActorRevisionSummary,
  ApifyActorRouteDetail,
  ApifyActorRouteSummary,
  ApifyActorSlotName,
  ApifyActorSourceValidation,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  SettingsDisclosure,
  SettingsGroup,
  SettingsItem,
  StatusBadge,
} from '../../components/settings'
import {
  actionToast,
  Button,
  Card,
  Checkbox,
  CountBadge,
  Description,
  FieldError,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  StatusIndicator,
  Switch,
  Tabs,
  TextField,
} from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import {
  APIFY_ACTOR_ROUTE_REFRESH_MS,
  formatActorDateTime,
  formatActorPercent,
  formatActorUsd,
  safeActorActionError,
} from './apifyActorModel'
import {
  humanActorError,
  routeProductNames,
  routeProfileId,
  routeProfileOrder,
  taskTabs,
  type ActorOpsTaskTab,
  type HumanActorError,
} from './actorOpsPresentation'
import {
  ActorOpsActivationConfirmationDialog,
  ActorOpsBatchConfirmationDialog,
  ActorOpsRollbackConfirmationDialog,
  ActorOpsSourceActivationConfirmationDialog,
  ActorOpsSourceCanaryConfirmationDialog,
  ActorOpsVerifiedActivationConfirmationDialog,
  HumanActorErrorNotice,
} from './ActorOpsWorkflowDialogs'
import { ActorOpsPoolSlots, ActorOpsRemovePoolDialog, ActorStoreQuality } from './ActorOpsPoolManagementControls'
import { actorPickerCandidates } from './actorOpsCandidatePicker'
import { actorOpsPoolPlanTarget } from './actorOpsPoolPlanTarget'
import { actorOpsWorkflowIntent } from './actorOpsWorkflowIntent'
import { useActorOpsPoolCandidates } from './useActorOpsPoolCandidates'
import { useActorOpsDiscoveryCompletionRefresh } from './useActorOpsDiscoveryCompletionRefresh'
import { useActorOpsPoolManagement } from './useActorOpsPoolManagement'
import { useActorOpsVerifiedActivation } from './useActorOpsVerifiedActivation'
import {
  poolCandidatePricingLabel,
  routeMinimumActors,
} from './actorOpsPoolPresentation'
import { openActorOpsSourceCanary } from './actorOpsSourceCanary'
import { toActivationConfirmationView, toBatchConfirmationView,
  toRollbackConfirmationView, toSourceCanaryConfirmationView } from './actorOpsWorkflowDialogModel'
const slotOrder: ApifyActorSlotName[] = ['primary', 'backup_1', 'backup_2']
const slotLabels: Record<ApifyActorSlotName, string> = {
  primary: 'Primary',
  backup_1: 'Backup 1',
  backup_2: 'Backup 2',
}
const slotDisplayLabels: Record<ApifyActorSlotName, string> = {
  primary: '主用',
  backup_1: '备用 1',
  backup_2: '备用 2',
}
const terminalDiscoveryStatuses = new Set([
  'awaiting_canary_approval',
  'activation_ready',
  'canary_exhausted',
  'candidate_shortfall',
  'blocked_ai_unavailable',
  'completed',
  'failed',
  'cancelled',
  'blocked',
])

const discoveryReasonLabels: Record<string, string> = {
  actor_input_validation_rejected: '候选输入与固定 Build Schema 不兼容',
  actor_input_validation_forbidden: '候选不允许执行官方输入校验',
  actor_input_validation_target_unavailable: '候选 Actor 或固定 Build 已不可用',
  actor_input_validation_unavailable: '官方输入校验暂时不可用（已完成有界重试）',
  actor_input_validation_contract_error: '输入校验请求合同被拒绝',
  actor_input_schema_unmappable: '官方输入 Schema 无法安全映射目标身份',
  actor_items_capability_unproven: 'Actor 只提供频道资料或统计，不能返回频道内容',
  apify_actor_metadata_authentication_failed: 'Apify Key 无法认证元数据请求',
  apify_actor_metadata_unavailable: 'Store、Actor 或 Build 元数据暂时不可用',
  apify_actor_metadata_not_found: 'Actor 或固定 Build 元数据不存在',
  build_input_validation_failed: '候选输入未通过固定 Build Schema',
  input_validation_candidate_shortfall: '通过输入校验的候选不足三个',
  publisher_diversity_candidate_shortfall: '通过校验的候选不足两个发布者',
  candidate_shortfall: '商城元数据过滤后候选不足',
  route_canary_attempts_exhausted: '本轮五次 Route Canary 已用完，请重新发现并生成修正后的 Revision',
  apify_actor_run_timed_out: 'Actor 在时限内未完成，已中止且不会自动重试',
  apify_actor_contract_mismatch: 'Dataset 未满足统一内容合同',
  apify_actor_target_identity_mismatch: 'Actor 返回了其他账号或频道的内容，或结果缺少可证明目标归属的字段',
  apify_manifest_output_pointer_unverifiable: 'Manifest 字段路径不在固定 Build Dataset Schema 中',
  apify_manifest_item_identity_invalid: 'Manifest 把频道或主页本身错误映射成内容条目',
  apify_actor_metadata_only: 'Actor 只返回频道资料，没有返回视频内容；该 Build 已停止重复试跑',
  apify_manifest_source_identity_invalid: 'Manifest 错把内容 URL 当作来源身份',
  apify_actor_discovery_failed: '发现流程失败，请稍后重新触发',
  discovery_ai_invalid_json: 'Discovery AI 返回了非法响应，请检查 AI Provider 配置',
  discovery_ai_disabled: 'Discovery AI 未启用，请先在设置中启用',
  discovery_global_ai_unavailable: 'Discovery AI 全局配置不可用',
  metadata_token_unavailable: 'Apify 元数据凭证不可用',
  discovery_interrupted: '发现流程被中断，请重新触发',
  discovery_admin_unavailable: '没有可用的管理员账号来触发发现',
  superseded_duplicate_refresh: '已被一次更新的刷新取代',
}

type PoolDraft = Record<ApifyActorSlotName, string | null>

type CanaryRouteContext = {
  routeKey: string
  routeLabel: string
  routeMode: 'primary' | 'fallback'
  actorPricingLabel: string
  buildLabel: string
}

type CanaryTarget = CanaryRouteContext & {
    kind: 'source'
    sourceId: string
    revision: ApifyActorRevisionSummary
    expectedGeneration: number
    capUsd: number
  }

export type CanaryApprovalTarget = CanaryTarget & {
  approvalId: string
}

type CanaryBatchApprovalTarget = {
  plan: ApifyActorCanaryPlan
  approvalId: string
}

function workflowFailureNotice(
  progress: Record<string, unknown> | undefined,
  goal: ApifyActorPoolGoal | undefined,
): HumanActorError | null {
  const rawFailure = progress?.last_failure
  if (rawFailure === null || typeof rawFailure !== 'object' || Array.isArray(rawFailure)) return null
  const failure = rawFailure as Record<string, unknown>
  const code = typeof failure.code === 'string' && /^[a-z0-9_]{1,128}$/.test(failure.code)
    ? failure.code
    : null
  if (!code) return null
  const actualCost = typeof failure.actual_cost_usd === 'number'
    && Number.isFinite(failure.actual_cost_usd)
    && failure.actual_cost_usd >= 0
    ? failure.actual_cost_usd
    : null
  const costFinal = failure.cost_final === true
  const presented = humanActorError(
    new ApiError(409, { code, message: '' }),
    '刷新状态后选择另一个候选；系统不会自动重试。',
  )
  const spend = costFinal && actualCost !== null
    ? ` 本次已结算费用 ${formatActorUsd(actualCost, true)}。`
    : costFinal
      ? ''
      : ' 本次费用仍在对账，暂不会显示为 $0。'
  return {
    ...presented,
    impact: `${presented.impact}${spend}`,
    next: code === 'apify_actor_run_timed_out' && costFinal
      ? goal === 'upgrade_legacy'
        ? '当前 Actor 的升级已停止；保持兼容池，不提价、不延时、不选择替补。'
        : '打开候选列表，把等待时间从当前值调高后再确认；系统不会自动重试。'
      : ['suspicious_empty', 'apify_actor_suspicious_empty'].includes(code)
        ? goal === 'upgrade_legacy'
          ? '打开当前 Actor 状态；样本为 1 时只可扩大到 3，样本 3 仍失败就停止升级。'
          : '打开候选列表；支持扩大样本时改为 3 或 5 条，否则更换 Actor。'
        : presented.next,
  }
}

type DiscoverySettingsDraft = {
  enabled: boolean
  aiConfigId: string
  maxQueriesPerRun: string
  maxCandidates: string
  maxOutputTokens: string
}


function shortRevision(revisionId: string | null | undefined): string {
  if (!revisionId) return '未绑定'
  return revisionId.length > 16 ? `${revisionId.slice(0, 8)}…${revisionId.slice(-6)}` : revisionId
}

function discoveryReasonLabel(reason: string): string {
  return discoveryReasonLabels[reason] || '未通过当前发现规则'
}

function discoveryFailureTitle(phase: string | null | undefined): string {
  if (phase === 'store' || phase === 'metadata') return 'Store / Actor 元数据读取需要处理'
  if (phase === 'input_validation') return '固定 Build 输入校验需要处理'
  if (phase === 'ai_generation') return 'Discovery AI 生成需要处理'
  if (phase === 'static_validation') return 'Manifest 静态校验需要处理'
  if (phase === 'route_canary') return '本轮 Route Canary 已停止'
  return '发现任务需要处理'
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3">
    <p className="type-meta text-muted">{label}</p>
    <p className="type-page-title mt-1 break-words tabular-nums">{value}</p>
    {detail && <p className="type-meta mt-1 break-words text-muted">{detail}</p>}
  </div>
}

function routeMinimumPublishers(
  route: Pick<ApifyActorRouteSummary, 'min_runtime_healthy'> & {
    actual_min_runtime_healthy?: number
    actual_min_publishers?: number
  },
): number {
  const actorMinimum = routeMinimumActors(route)
  const value = route.actual_min_publishers ?? (actorMinimum === 1 ? 1 : 2)
  return Math.min(actorMinimum, Math.max(1, Math.trunc(value)))
}

function DiscoveryPanel({
  detail,
  queryEnabled,
  activeBatch,
  onBatchCanary,
  goal = 'initial_pool',
  showApprovalAction = true,
}: {
  detail: ApifyActorRouteDetail
  queryEnabled: boolean
  activeBatch: ApifyActorCanaryBatch | null
  onBatchCanary: (plan: ApifyActorCanaryPlan) => void
  goal?: ApifyActorPoolGoal
  showApprovalAction?: boolean
}) {
  const { api, user } = useAppContext()
  const runId = detail.discovery_run_id || ''
  const query = useQuery({
    queryKey: queryKeys.apifyActorDiscoveryRun(user.id, runId),
    queryFn: ({ signal }) => api.apifyActorDiscoveryRun(runId, signal),
    enabled: queryEnabled && Boolean(runId),
    retry: false,
    refetchInterval: (current) => {
      const data = current.state.data
      if (data?.candidates.some((candidate) => (
        candidate.canary_in_flight
        || ['queued', 'running'].includes(candidate.validation_status || '')
      ))) return 3_000
      const status = data?.status
      return status && terminalDiscoveryStatuses.has(status) ? false : 5_000
    },
  })
  const canPlan = Boolean(runId)
    && ['awaiting_canary_approval', 'canary_exhausted', 'candidate_shortfall', 'activation_ready'].includes(query.data?.stage || '')
    && !detail.activation_recommendation?.ready
  const planQuery = useQuery({
    queryKey: queryKeys.apifyActorCanaryPlan(user.id, runId, goal),
    queryFn: ({ signal }) => api.apifyActorCanaryPlan(runId, goal, signal),
    enabled: queryEnabled && canPlan,
    retry: false,
    refetchInterval: activeBatch && ['queued', 'preflighting', 'running'].includes(activeBatch.status)
      ? 3_000
      : false,
  })

  if (!runId) return <HeroNotice title="当前没有进行中的发现任务" status="default" role="status">
    Actor、Build 或 Schema 指纹变化时，系统会在这里生成不自动付费的补位提案。
  </HeroNotice>
  if (query.isPending) return <LoadingState label="正在读取 Actor 发现进度" rows={2} />
  if (query.isError || !query.data) return <HeroNotice title="发现任务读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void query.refetch()}>重试此区域</Button>
  </HeroNotice>

  const run = query.data
  const displayedBatch = activeBatch ?? run.canary_batch ?? null
  const publisherCount = run.publisher_count ?? new Set(
    run.candidates.map((candidate) => candidate.revision.publisher),
  ).size
  const routeTargetCount = goal === 'upgrade_legacy'
    ? 3
    : ['complete_third', 'compatibility_single'].includes(goal)
      ? 1
      : routeMinimumActors(detail)
  const targetActorCount = planQuery.data?.target_slot_count ?? routeTargetCount
  const targetPublisherCount = goal === 'upgrade_legacy'
    ? 2
    : goal === 'compatibility_single' || targetActorCount === 1
      ? 1
      : routeMinimumPublishers(detail)
  const singleActorTarget = targetActorCount === 1
  const paidBatchRunning = Boolean(displayedBatch && ['queued', 'preflighting', 'running'].includes(displayedBatch.status))
  return <div className="grid gap-3">
    <div className="grid gap-3 min-[720px]:grid-cols-3">
      <Metric
        label="发现阶段"
        value={run.stage || run.status}
        detail={run.queries_limit
          ? `已完成 ${run.queries_completed ?? 0}/${run.queries_limit} 轮查询`
          : `状态 ${run.status}`}
      />
      <Metric
        label="Route 认证费用"
        value={`${formatActorUsd(run.spent_usd ?? 0)} 已确认`}
        detail={`待远端对账 ${run.unreconciled_cost_count ?? 0} 笔；已审批但未运行的费用上限 ${formatActorUsd(run.reserved_usd ?? 0)}；认证预算上限 ${formatActorUsd(run.budget_cap_usd)}（不是扣款）`}
      />
      <Metric
        label="候选完整度"
        value={run.candidate_shortfall
          ? `缺少 ${run.candidate_shortfall} 个 Actor`
          : run.publisher_shortfall
            ? `缺少 ${run.publisher_shortfall} 个发布者`
            : '数量充足'}
        detail={`${run.candidate_count ?? run.candidates.length}/${targetActorCount} Actor · ${publisherCount}/${targetPublisherCount} 发布者；付费验证只统计真实启动`}
      />
    </div>
    {run.error_code && <HeroNotice title={discoveryFailureTitle(run.failure_phase)} status="warning">
      {discoveryReasonLabel(run.error_code)}。安全错误码：<code>{run.error_code}</code>
    </HeroNotice>}
    {displayedBatch && <HeroNotice
      title={displayedBatch.stop_reason === 'apify_start_not_created'
        ? 'Apify 已确认未创建 Run：本次费用 $0，系统没有自动重跑'
        : displayedBatch.status === 'activation_ready'
        ? singleActorTarget ? '单路 Actor 验证完成，可以确认启用' : '两路主备验证完成，可以确认启用'
        : paidBatchRunning
          ? `正在串行验证${singleActorTarget ? '单路 Actor' : '主备'}（${displayedBatch.success_count}/${targetActorCount} 成功）`
          : displayedBatch.status === 'partial'
            ? singleActorTarget
              ? '本批候选未通过单路验证；系统不会自动追逐额外备用'
              : '本批候选未凑齐两路，系统正在补位发现（不会启动 Actor）'
            : '主备验证批次已结束'}
      status={displayedBatch.status === 'activation_ready' ? 'success' : paidBatchRunning ? 'warning' : 'default'}
    >
      实际费用 {displayedBatch.actual_cost_usd === null || displayedBatch.actual_cost_usd === undefined
        ? '待远端对账'
        : formatActorUsd(displayedBatch.actual_cost_usd, true)}；
      未启动或不再需要的候选费用为 $0。批次状态：<code>{displayedBatch.status}</code>。
    </HeroNotice>}
    {showApprovalAction && !detail.activation_recommendation?.ready && !paidBatchRunning && planQuery.data?.ready && <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-separator bg-surface-secondary p-3">
      <div>
        <p className="type-control">一次确认，系统验证{singleActorTarget ? '单路 Actor' : '两路主备'}</p>
        <p className="type-meta mt-1 text-muted">
          服务器已选择 {planQuery.data.items.length} 个候选，严格串行；{singleActorTarget ? '一个 Actor 成功后立即停止，不自动补第二或第三路' : '两位不同发布者成功后立即停止'}。全部候选总封顶 {formatActorUsd(planQuery.data.max_total_charge_usd, true)}。
        </p>
      </div>
      <Button
        size="sm"
        isDisabled={paidBatchRunning}
        onPress={() => onBatchCanary(planQuery.data)}
      ><Icons.FlaskConical size={14} aria-hidden="true" />验证{singleActorTarget ? '单路 Actor' : '两路主备'}</Button>
    </div>}
    {!detail.activation_recommendation?.ready && planQuery.isError && <HeroNotice title={singleActorTarget ? '当前候选还不能形成可用的单路 fallback' : '当前候选还不能组成安全的两路主备'} status="warning">
      {singleActorTarget
        ? '无需反复刷新或逐个试跑；系统会保留已有成功证据，也不会为了补满三槽自动重复验证。'
        : '无需反复刷新或逐个试跑；系统会保留已有成功证据，并在候选用尽时自动创建不会启动 Actor 的补位发现任务。'}
    </HeroNotice>}
    {Boolean(run.rejections?.length) && <HeroNotice title="确定性淘汰摘要" status="default">
      <ul className="list-disc space-y-1 pl-5 type-meta text-muted">
        {run.rejections?.map((item) => <li key={item.reason}>
          {discoveryReasonLabel(item.reason)} · <code>{item.reason}</code> · {item.count} 个
        </li>)}
      </ul>
    </HeroNotice>}
  </div>
}

function RevisionHistory({
  detail,
  onRollback,
  actionPending,
}: {
  detail: ApifyActorRouteDetail
  onRollback: (revision: ApifyActorRevisionSummary, trigger: HTMLButtonElement) => void
  actionPending: boolean
}) {
  const activeRevisionIds = new Set(
    detail.slots.flatMap((slot) => slot.revision_id ? [slot.revision_id] : []),
  )
  const history = (detail.revisions ?? []).filter((revision) => (
    revision.lifecycle === 'superseded'
    || (
      revision.lifecycle === 'legacy_builtin'
      && !activeRevisionIds.has(revision.revision_id)
    )
  ))
  return <div className="grid gap-3">
    {Boolean(detail.revision_diffs?.length) && <ul className="grid gap-2" aria-label="Revision 差异">
      {detail.revision_diffs?.map((diff) => <li
        key={`${diff.slot}-${diff.proposed_revision_id}`}
        className="rounded-control border border-separator bg-surface-secondary p-3"
      >
        <p className="type-control">{slotLabels[diff.slot]} · {shortRevision(diff.current_revision_id)} → {shortRevision(diff.proposed_revision_id)}</p>
        <p className="type-meta mt-1 break-words text-muted">{diff.changes.join(' · ') || 'Manifest 或 Build 指纹发生变化'}</p>
      </li>)}
    </ul>}
    {history.length === 0
      ? <p className="type-meta text-muted">当前没有可回滚的历史 Revision。</p>
      : <ol className="grid gap-2" aria-label="可回滚 Revision">
        {history.map((revision) => <li
          key={revision.revision_id}
          className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-control border border-separator bg-surface-secondary p-3"
        >
          <div className="min-w-0">
            <p className="type-control">{revision.actor_public_name || revision.actor_id}</p>
            <p className="type-meta mt-1 break-words text-muted">
              {revision.publisher} · Build {revision.build_number || revision.build_id || 'legacy_builtin'}
            </p>
            <code className="type-meta mt-1 block break-all text-muted">{revision.revision_id}</code>
          </div>
          <Button
            size="sm"
            variant="secondary"
            isDisabled={actionPending || !revision.can_activate}
            onPress={(event) => onRollback(revision, event.target as HTMLButtonElement)}
          ><Icons.RotateCcw size={14} aria-hidden="true" />回滚到此 Revision</Button>
        </li>)}
      </ol>}
  </div>
}

function DiscoverySettingsPanel({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<DiscoverySettingsDraft | null>(null)
  const [fieldError, setFieldError] = useState('')
  const [measurementConfirmation, setMeasurementConfirmation] = useState('')
  const query = useQuery({
    queryKey: queryKeys.apifyActorDiscoverySettings(user.id),
    queryFn: ({ signal }) => api.apifyActorDiscoverySettings(signal),
    enabled: queryEnabled,
    retry: false,
  })
  useEffect(() => {
    if (!query.data) return
    // The server generation is the reset boundary for this editable draft.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({
      enabled: query.data.enabled,
      aiConfigId: query.data.ai_config_id,
      maxQueriesPerRun: String(query.data.max_queries_per_run),
      maxCandidates: String(query.data.max_candidates),
      maxOutputTokens: String(query.data.max_output_tokens),
    })
  }, [query.data])

  const update = useMutation({
    mutationFn: (patch: ApifyActorDiscoverySettingsPatch) => api.updateApifyActorDiscoverySettings(patch),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.apifyActorDiscoverySettings(user.id), settings)
      actionToast.success('Actor Discovery AI 设置已热更新')
    },
    onError: (caught) => {
      void query.refetch()
      actionToast.danger('Discovery AI 设置保存失败', {
        description: safeActorActionError(caught, '设置或 generation 已变化，请刷新后重试。'),
      })
    },
  })

  const measurement = useMutation({
    mutationFn: ({ maxOutputTokens, routeKeys }: {
      maxOutputTokens: 32768 | 65536
      routeKeys: Array<'youtube/channel/items' | 'instagram/profile/items'>
    }) => {
      if (!query.data) throw new Error('Discovery 设置尚未加载')
      return api.measureApifyActorDiscovery({
        expected_generation: query.data.generation,
        confirmation: '确认AI容量测试',
        max_output_tokens: maxOutputTokens,
        route_keys: routeKeys,
      })
    },
    onSuccess: () => {
      setMeasurementConfirmation('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorDiscoverySettings(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      actionToast.success('AI 容量测试已按顺序排队；不会启动付费 Actor')
    },
    onError: (caught) => actionToast.danger('AI 容量测试未启动', {
      description: safeActorActionError(caught, '设置、确认短语或测试条件不满足。'),
    }),
  })

  function save(event: FormEvent) {
    event.preventDefault()
    if (!query.data || !draft || update.isPending) return
    const maxQueries = Number(draft.maxQueriesPerRun)
    const maxCandidates = Number(draft.maxCandidates)
    const maxOutputTokens = Number(draft.maxOutputTokens)
    const selectedAI = query.data.ai_options.find((option) => option.id === draft.aiConfigId)
    if (!selectedAI || !Number.isInteger(maxQueries) || maxQueries < 1 || maxQueries > 3
      || !Number.isInteger(maxCandidates) || maxCandidates < 3 || maxCandidates > 30) {
      setFieldError('请选择全局 AI；查询轮数为 1–3，候选数为 3–30。')
      return
    }
    if (!Number.isInteger(maxOutputTokens) || maxOutputTokens < 4096 || maxOutputTokens > 65536) {
      setFieldError('生产输出上限必须为 4096–65536。')
      return
    }
    if (draft.enabled && !selectedAI.ready) {
      setFieldError('人工选择的全局 AI Key 尚未就绪，不能启用 Actor 发现。')
      return
    }
    setFieldError('')
    update.mutate({
      expected_generation: query.data.generation,
      enabled: draft.enabled,
      ai_config_id: draft.aiConfigId,
      max_queries_per_run: maxQueries,
      max_candidates: maxCandidates,
      max_output_tokens: maxOutputTokens,
    })
  }

  if (query.isPending || !draft) return <LoadingState label="正在读取 Actor Discovery AI 设置" rows={2} />
  if (query.isError || !query.data) return <HeroNotice title="Discovery AI 设置读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void query.refetch()}>重试此区域</Button>
  </HeroNotice>

  const selectedAI = query.data.ai_options.find((option) => option.id === draft.aiConfigId)

  return <form className="grid gap-4" onSubmit={save} noValidate>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="type-control">从全局 AI 配置人工选择</p>
        <p className="type-meta mt-1 text-muted">Provider、模型和 Base URL 继承全局 AI；这里人工固定一个同 Provider 的已保存 Key，下一 Discovery Job 热生效且不自动切 Key。</p>
      </div>
      <Switch
        isSelected={draft.enabled}
        isDisabled={update.isPending || (!draft.enabled && !selectedAI?.ready)}
        onChange={(enabled) => setDraft((current) => current ? { ...current, enabled } : current)}
      >
        <Switch.Content>
          <Switch.Control><Switch.Thumb /></Switch.Control>
          {draft.enabled ? '发现已启用' : '发现已停用'}
        </Switch.Content>
      </Switch>
    </div>
    <div className="grid gap-4 min-[720px]:grid-cols-2">
      <HeroSelect
        label="Discovery 使用的全局 AI"
        value={draft.aiConfigId}
        onChange={(aiConfigId) => setDraft((current) => current ? { ...current, aiConfigId } : current)}
        isDisabled={update.isPending}
        options={query.data.ai_options.map((option) => ({
          id: option.id,
          label: `${option.label}${option.preferred ? '（全局首选）' : ''}${option.ready ? '' : '（未就绪）'}`,
          description: `${option.provider || '未配置'} · ${option.model || '未配置模型'} · ${option.key_name || '未选择 Key'}`,
        }))}
        description="只列出与当前全局 Provider 匹配的 AI Key；模型和 Key 均在全局 AI 设置中维护。"
      />
      <div className="grid grid-cols-2 gap-3">
        <TextField
          fullWidth
          value={draft.maxQueriesPerRun}
          onChange={(maxQueriesPerRun) => setDraft((current) => current ? { ...current, maxQueriesPerRun } : current)}
          isDisabled={update.isPending}
        ><Label>最多查询轮数</Label><Input type="number" min={1} max={3} /></TextField>
        <TextField
          fullWidth
          value={draft.maxCandidates}
          onChange={(maxCandidates) => setDraft((current) => current ? { ...current, maxCandidates } : current)}
          isDisabled={update.isPending}
        ><Label>最多候选数</Label><Input type="number" min={3} max={30} /></TextField>
        <TextField
          fullWidth
          value={draft.maxOutputTokens}
          onChange={(maxOutputTokens) => setDraft((current) => current ? { ...current, maxOutputTokens } : current)}
          isDisabled={update.isPending}
          className="col-span-2"
        >
          <Label>生产输出 Token 上限</Label>
          <Input type="number" min={4096} max={65536} step={1024} />
          <Description>
            下一 Discovery Job 热生效；建议值为 {query.data.recommended_max_output_tokens ?? '等待两条 Route 实测'}。
          </Description>
        </TextField>
      </div>
    </div>
    {!selectedAI?.ready && <HeroNotice title="所选全局 AI 尚未就绪" status="warning">
      请先前往 <a className="type-control text-accent underline" href="#settings-ai">全局 AI 设置</a> 配置相同 Provider 的可用 Key，再回到这里人工选择。
    </HeroNotice>}
    {fieldError && <FieldError>{fieldError}</FieldError>}
    <section className="grid gap-3 rounded-control border border-separator bg-surface-secondary p-3">
      <div>
        <p className="type-control">AI 容量实测</p>
        <p className="type-meta mt-1 text-muted">YouTube 与 Instagram 顺序各调用模型一次，32K 仅为本次护栏；不运行 Actor 或付费 Canary。</p>
      </div>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {(['youtube', 'instagram'] as const).map((name) => {
          const result = query.data.measurements[name]
          const metrics = result?.metrics
          return <div key={name} className="rounded-control border border-separator p-3">
            <p className="type-control">{name === 'youtube' ? 'YouTube Channel' : 'Instagram Profile'}</p>
            <p className="type-meta mt-1 text-muted">
              completion {metrics?.completion_tokens ?? '未知'} · reasoning {metrics?.reasoning_tokens ?? '未知'} · content {metrics?.content_tokens ?? '未知'}
            </p>
            <p className="type-meta mt-1 text-muted">
              finish {metrics?.finish_reason ?? '未知'} · {metrics?.latency_ms != null ? `${metrics.latency_ms} ms` : '耗时未知'} · JSON {metrics?.json_status ?? '未知'} · Manifest {metrics?.manifest_status ?? '未知'}
            </p>
          </div>
        })}
      </div>
      <TextField
        fullWidth
        value={measurementConfirmation}
        onChange={setMeasurementConfirmation}
        isDisabled={measurement.isPending}
      >
        <Label>容量测试确认短语</Label>
        <Input placeholder="确认AI容量测试" />
        <Description>该操作会调用当前全局 AI，但不会调用 Apify Actor。</Description>
      </TextField>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          isDisabled={!draft.enabled || measurement.isPending || measurementConfirmation !== '确认AI容量测试'}
          onPress={() => measurement.mutate({
            maxOutputTokens: 32768,
            routeKeys: ['youtube/channel/items', 'instagram/profile/items'],
          })}
        >{measurement.isPending ? '排队中…' : '运行两条 Route 的 32K 实测'}</Button>
        {query.data.measurements.youtube?.metrics?.finish_reason === 'length' && <Button
          type="button"
          variant="secondary"
          isDisabled={measurement.isPending || measurementConfirmation !== '确认AI容量测试'}
          onPress={() => measurement.mutate({ maxOutputTokens: 65536, routeKeys: ['youtube/channel/items'] })}
        >YouTube 64K 重测</Button>}
        {query.data.measurements.instagram?.metrics?.finish_reason === 'length' && <Button
          type="button"
          variant="secondary"
          isDisabled={measurement.isPending || measurementConfirmation !== '确认AI容量测试'}
          onPress={() => measurement.mutate({ maxOutputTokens: 65536, routeKeys: ['instagram/profile/items'] })}
        >Instagram 64K 重测</Button>}
      </div>
    </section>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="type-meta text-muted">
        generation {query.data.generation} · 更新于 {formatActorDateTime(query.data.updated_at ?? null)}
      </p>
      <Button type="submit" isDisabled={update.isPending}>{update.isPending ? '保存中…' : '保存并热加载'}</Button>
    </div>
  </form>
}

function sourceStatusPresentation(
  status: string,
  route?: Pick<ApifyActorRouteSummary, 'min_runtime_healthy' | 'admission_mode'> & {
    actual_min_runtime_healthy?: number
  },
): { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } {
  if (status === 'ready_1of1') {
    return route && routeMinimumActors(route) === 1 && route.admission_mode !== 'compatibility'
      ? { label: '已启用（1/1 fallback）', tone: 'success' }
      : { label: '兼容启用（1/3）', tone: 'warning' }
  }
  if (status === 'ready_2of2') return { label: '已启用（2/2）', tone: 'success' }
  if (status === 'ready_3of3') return { label: '已启用（3/3）', tone: 'success' }
  if (['queued', 'running'].includes(status)) return { label: '验证中', tone: 'warning' }
  if (status === 'legacy_validation_pending') return { label: '先升级主备', tone: 'danger' }
  if (['pending', 'revalidation_pending'].includes(status)) return { label: '待验证', tone: 'warning' }
  if (['failed', 'blocked'].includes(status)) return { label: '需要处理', tone: 'danger' }
  return { label: '尚未启用', tone: 'neutral' }
}

function sourceShortLabel(sourceId: string): string {
  return `来源 · ${sourceId.slice(-6)}`
}

function sourceActorSummary(source: ApifyActorSourceValidation): string {
  const preference = source.actor_preference
  if (!preference) return '当前实际 Actor 尚无记录'
  const active = preference.active_actor_name || '尚无运行记录'
  if (preference.preference_suspended) {
    return `当前实际 Actor：${active} · 手动首选已暂停，系统正在自动切备`
  }
  if (preference.preferred_actor_name) {
    return `当前实际 Actor：${active} · 手动首选：${preference.preferred_actor_name}`
  }
  return `当前实际 Actor：${active} · 自动选择`
}

function SourceActorPreferenceControl({
  detail,
  source,
}: {
  detail: ApifyActorRouteDetail
  source: ApifyActorSourceValidation
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const preference = source.actor_preference
  const [draft, setDraft] = useState(preference?.preferred_candidate_id || 'automatic')
  const options = [
    { id: 'automatic', label: '自动选择', description: '按健康与新鲜度自动串行切换' },
    ...(detail.slot_freshness ?? []).flatMap((slot) => (
      slot.candidate_id && slot.actor_name
        ? [{
            id: slot.candidate_id,
            label: slot.actor_name,
            description: `${slot.candidate_id === preference?.active_candidate_id ? '当前实际 · ' : ''}${
              detail.slots.find((item) => item.slot === slot.slot_name)?.runnable === false
                ? `${slotDisplayLabels[slot.slot_name]} · 当前因故障或旧数据暂停`
                : `${slotDisplayLabels[slot.slot_name]} · 失败或旧数据时仍自动切备`
            }`,
            isDisabled: detail.slots.find((item) => item.slot === slot.slot_name)?.runnable === false,
          }]
        : []
    )),
  ].filter((item, index, rows) => rows.findIndex((candidate) => candidate.id === item.id) === index)
  const mutation = useMutation({
    mutationFn: () => api.updateApifyActorSourcePreference(
      source.source_id,
      draft === 'automatic' ? null : draft,
      source.generation,
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, detail.route_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorSourceSupport(user.id, source.source_id) })
      actionToast.success('来源首选 Actor 已更新')
    },
    onError: (caught) => actionToast.danger('来源首选更新失败', {
      description: safeActorActionError(caught, '来源或 Actor 主备已变化，请刷新后重试。'),
    }),
  })
  if (!preference) return null
  const changed = draft !== (preference.preferred_candidate_id || 'automatic')
  return <div className="grid gap-3 rounded-control border border-separator bg-default p-3">
    <div className="flex min-w-0 flex-col gap-2 min-[640px]:flex-row min-[640px]:items-start min-[640px]:justify-between">
      <div className="min-w-0"><p className="type-control">当前实际 Actor</p><p className="type-page-title mt-1 break-words">{preference.active_actor_name || '尚无运行记录'}</p><p className="type-meta mt-1 text-muted">最近一次实际使用，并会在自动模式下优先复用。</p></div>
      <StatusBadge tone={preference.preference_suspended ? 'warning' : preference.mode === 'manual' ? 'accent' : 'success'}>
        {preference.preference_suspended ? '手动首选已暂停' : preference.mode === 'manual' ? '手动首选' : '自动选择'}
      </StatusBadge>
    </div>
    <div><p className="type-control">切换本来源的 Actor</p><p className="type-meta mt-1 text-muted">保存后从下一次计划抓取起优先使用；不会立即启动 Actor 或产生额外费用。旧数据、失败或暂停时仍自动切备。</p></div>
    <div className="grid gap-3 min-[640px]:grid-cols-[minmax(0,1fr)_auto] min-[640px]:items-end">
      <HeroSelect label="下次抓取优先使用" value={draft} onChange={setDraft} isDisabled={mutation.isPending} options={options} />
      <Button size="sm" isDisabled={!changed || mutation.isPending} onPress={() => mutation.mutate()}>{mutation.isPending ? '保存中…' : '保存切换'}</Button>
    </div>
    {preference.preference_suspended && <HeroNotice title="手动首选暂未使用" status="warning" role="status">该 Actor 因旧数据或故障暂停。系统会继续使用健康备用；连续两次新鲜度通过后自动恢复首选。</HeroNotice>}
  </div>
}

function ActorFreshnessPanel({ detail, queryEnabled }: { detail: ApifyActorRouteDetail; queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const saveRef = useRef<HTMLButtonElement | null>(null)
  const [enabled, setEnabled] = useState(Boolean(detail.freshness?.enabled))
  const [interval, setInterval] = useState(String(detail.freshness?.interval_hours ?? 24))
  const [settingsConfirmOpen, setSettingsConfirmOpen] = useState(false)
  const [manualConfirmOpen, setManualConfirmOpen] = useState(false)
  const [checkId, setCheckId] = useState('')
  const planQuery = useQuery({
    queryKey: queryKeys.apifyActorFreshnessPlan(user.id, detail.route_id),
    queryFn: ({ signal }) => api.apifyActorFreshnessPlan(detail.route_id, signal),
    enabled: queryEnabled,
    retry: false,
  })
  const checkQuery = useQuery({
    queryKey: queryKeys.apifyActorFreshnessCheck(user.id, checkId),
    queryFn: ({ signal }) => api.apifyActorFreshnessCheck(checkId, signal),
    enabled: queryEnabled && Boolean(checkId),
    retry: false,
    refetchInterval: (query) => ['queued', 'running'].includes(query.state.data?.status || '') ? 3_000 : false,
  })
  const numericInterval = Number(interval)
  const intervalValid = Number.isInteger(numericInterval) && numericInterval >= 6 && numericInterval <= 168
  const currentEnabled = Boolean(detail.freshness?.enabled)
  const currentInterval = detail.freshness?.interval_hours ?? 24
  const changed = enabled !== currentEnabled || numericInterval !== currentInterval
  const saveMutation = useMutation({
    mutationFn: () => api.updateApifyActorFreshnessSettings(detail.route_id, {
      enabled,
      interval_hours: numericInterval,
      expected_generation: detail.generation,
      standing_authorization_confirmed: enabled,
    }),
    onSuccess: () => {
      setSettingsConfirmOpen(false)
      window.requestAnimationFrame(() => saveRef.current?.focus())
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, detail.route_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorFreshnessPlan(user.id, detail.route_id) })
      actionToast.success(enabled ? '自动新鲜度校验已授权' : '自动新鲜度校验已关闭')
    },
    onError: (caught) => actionToast.danger('新鲜度设置保存失败', { description: safeActorActionError(caught, '请检查校验 Key 与 Route 状态。') }),
  })
  const manualMutation = useMutation({
    mutationFn: () => api.createApifyActorFreshnessCheck(detail.route_id, {
      cost_confirmed: true,
      expected_generation: detail.generation,
      max_total_charge_usd: Number(planQuery.data?.max_total_charge_usd),
    }),
    onSuccess: (result) => {
      setCheckId(result.check.check_id)
      setManualConfirmOpen(false)
      window.requestAnimationFrame(() => triggerRef.current?.focus())
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, detail.route_id) })
      actionToast.success('主备新鲜度校验已提交，将严格串行执行')
    },
    onError: (caught) => actionToast.danger('新鲜度校验未提交', { description: safeActorActionError(caught, '不会自动重试或产生新的 Actor Run。') }),
  })
  const state = detail.freshness
  const validationKeyUsable = Boolean(state?.validation_key.usable)
  const activeActorCount = detail.active_slot_count
    ?? detail.slots.filter((slot) => Boolean(slot.revision_id) && slot.runnable).length
  const hasActiveActor = activeActorCount > 0
  const freshnessLabel = activeActorCount === 1 ? 'Actor 新鲜度' : '主备新鲜度'
  const comparisonRule = activeActorCount >= 3
    ? '三路按最新内容指纹多数结果识别落后 Actor。'
    : activeActorCount === 2
      ? '两路不一致先记为疑似旧数据，连续两轮才确认。'
      : '单路只能验证可运行性和结果时效，无法进行主备交叉验证。'
  return <Card variant="secondary" className="grid gap-4 border border-separator p-4" data-testid="actorops-freshness-panel">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><Card.Title>{freshnessLabel}</Card.Title><Card.Description className="mt-1">专用校验 Key 按同一参考账号与窗口校验；不会保存或返回明文目标。{comparisonRule}</Card.Description></div><StatusIndicator label={state?.status || '尚未校验'} tone={state?.status === 'fresh' ? 'success' : ['stale', 'failed'].includes(state?.status || '') ? 'danger' : 'warning'} /></div>
    {!validationKeyUsable && <HeroNotice title="需要先指定专用校验 Key" status="warning">自动校验和手动立即校验均不会借用生产 Key。请在“凭据”页指定一个独占校验 Key。</HeroNotice>}
    {!hasActiveActor && <HeroNotice title="当前没有可校验的 Actor" status="warning">先完成标准或兼容启用；没有活动 Actor 时不会创建自动或手动付费校验。</HeroNotice>}
    <div className="grid gap-3 min-[720px]:grid-cols-[auto_minmax(120px,220px)_auto] min-[720px]:items-end">
      <Switch isSelected={enabled} isDisabled={saveMutation.isPending} onChange={setEnabled}><Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{enabled ? '自动校验已开启' : '自动校验已关闭'}</Switch.Content></Switch>
      <TextField fullWidth value={interval} onChange={setInterval} isInvalid={Boolean(interval) && !intervalValid} isDisabled={saveMutation.isPending}>
        <Label>运行间隔（小时）</Label><Input type="number" min={6} max={168} step={1} /><Description>允许 6–168 小时，默认 24。</Description>{Boolean(interval) && !intervalValid && <FieldError>请输入 6–168 的整数。</FieldError>}
      </TextField>
      <Button ref={saveRef} size="sm" isDisabled={!changed || !intervalValid || saveMutation.isPending || (enabled && (!validationKeyUsable || !hasActiveActor))} onPress={() => setSettingsConfirmOpen(true)}>保存并确认授权</Button>
    </div>
    <dl className="grid gap-2 type-meta min-[720px]:grid-cols-3"><div><dt className="text-muted">上次 / 下次</dt><dd className="mt-1">{formatActorDateTime(state?.last_checked_at ?? null)} / {formatActorDateTime(state?.next_check_at ?? null)}</dd></div><div><dt className="text-muted">单轮实际 / 上限</dt><dd className="mt-1">{formatActorUsd(state?.last_actual_cost_usd ?? null, true)} / {formatActorUsd(state?.per_round_max_usd ?? planQuery.data?.max_total_charge_usd ?? null, true)}</dd></div><div><dt className="text-muted">理论月上限</dt><dd className="mt-1">{formatActorUsd(state?.theoretical_monthly_max_usd ?? null, true)}</dd></div></dl>
    {(detail.slot_freshness ?? []).length > 0 && <ol className="grid gap-2 min-[720px]:grid-cols-3" aria-label="Actor 新鲜度摘要">{(detail.slot_freshness ?? []).map((slot) => <li key={slot.slot_name} className="min-w-0 rounded-control border border-separator bg-default p-3"><p className="type-control break-words">{slot.actor_name || slotDisplayLabels[slot.slot_name]}</p><p className="type-meta mt-1 break-words text-muted">{slot.status}{slot.follows_current_build ? ' · 跟随当前 Build' : ''}{slot.observed_manifest ? ' · 观察型 Manifest' : ''}</p><p className="type-meta mt-1 text-muted">最近内容 {formatActorDateTime(slot.latest_published_at)}</p></li>)}</ol>}
    <div className="flex flex-wrap items-center gap-3"><Button ref={triggerRef} size="sm" variant="secondary" isDisabled={!validationKeyUsable || !hasActiveActor || manualMutation.isPending || planQuery.isPending || !planQuery.data} onPress={() => setManualConfirmOpen(true)}>立即校验{activeActorCount === 1 ? ' Actor' : '主备'}</Button>{checkQuery.data && <span className="type-meta text-muted" role="status">本轮 {checkQuery.data.status} · {checkQuery.data.completed_count}/{checkQuery.data.planned_count} · {checkQuery.data.cost_final ? `已结算 ${formatActorUsd(checkQuery.data.actual_cost_usd, true)}` : '费用待对账'}</span>}</div>
    <Modal isOpen={settingsConfirmOpen} onOpenChange={(open) => { if (!open && !saveMutation.isPending) { setSettingsConfirmOpen(false); window.requestAnimationFrame(() => saveRef.current?.focus()) } }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">确认自动校验授权</Modal.Trigger><Modal.Backdrop isDismissable={!saveMutation.isPending} isKeyboardDismissDisabled={saveMutation.isPending}><Modal.Container><Modal.Dialog><Modal.Header><Modal.Heading>{enabled ? '确认站立费用授权' : '确认关闭自动校验'}</Modal.Heading></Modal.Header><Modal.Body><HeroNotice title={enabled ? `每 ${numericInterval} 小时运行一次` : '停止后续自动运行'} status="warning" role="status">{enabled ? `每轮最多 ${formatActorUsd(planQuery.data?.max_total_charge_usd ?? state?.per_round_max_usd ?? null, true)}，理论月上限 ${formatActorUsd(state?.per_round_max_usd ? state.per_round_max_usd * 24 * 30 / numericInterval : null, true)}。频率变更即替换本次授权。` : '已排队或运行中的校验不会被重放；关闭后不再创建新周期。'}</HeroNotice></Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={saveMutation.isPending} onPress={() => setSettingsConfirmOpen(false)}>取消</Button><Button isDisabled={saveMutation.isPending} onPress={() => saveMutation.mutate()}>{saveMutation.isPending ? '保存中…' : enabled ? '确认授权并保存' : '确认关闭'}</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
    <Modal isOpen={manualConfirmOpen} onOpenChange={(open) => { if (!open && !manualMutation.isPending) { setManualConfirmOpen(false); window.requestAnimationFrame(() => triggerRef.current?.focus()) } }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">确认立即校验费用</Modal.Trigger><Modal.Backdrop isDismissable={!manualMutation.isPending} isKeyboardDismissDisabled={manualMutation.isPending}><Modal.Container><Modal.Dialog><Modal.Header><Modal.Heading>确认立即校验{activeActorCount === 1 ? ' Actor' : '主备'}</Modal.Heading></Modal.Header><Modal.Body><HeroNotice title="严格串行，不自动重试" status="warning" role="status">本轮最多 {formatActorUsd(planQuery.data?.max_total_charge_usd ?? state?.per_round_max_usd ?? null, true)}。使用专用校验 Key；{comparisonRule}</HeroNotice></Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={manualMutation.isPending} onPress={() => setManualConfirmOpen(false)}>取消</Button><Button isDisabled={manualMutation.isPending} onPress={() => manualMutation.mutate()}>{manualMutation.isPending ? '提交中…' : '确认费用并立即校验'}</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
  </Card>
}

function ActorDiagnosticTimeline({ detail, queryEnabled }: { detail: ApifyActorRouteDetail; queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const routeId = detail.route_id
  const [phase, setPhase] = useState('all')
  const [outcome, setOutcome] = useState('all')
  const [sourceId, setSourceId] = useState('all')
  const [candidateId, setCandidateId] = useState('all')
  const [windowHours, setWindowHours] = useState('24')
  const [cursor, setCursor] = useState('')
  const sourceOptions = [
    { id: 'all', label: '全部来源' },
    ...(detail.source_validations ?? []).map((source) => ({
      id: source.source_id,
      label: sourceShortLabel(source.source_id),
    })),
  ]
  const actorOptionsQuery = useQuery<ApifyActorDiagnosticEvents>({
    queryKey: [...queryKeys.apifyActorEvents(user.id, routeId, 'actor_options', 'all', 'all', 'all', windowHours)],
    queryFn: ({ signal }) => api.apifyActorEvents({
      route_id: routeId,
      since: new Date(Date.now() - Number(windowHours) * 60 * 60 * 1_000).toISOString(),
      limit: 100,
    }, signal),
    enabled: queryEnabled && Boolean(routeId),
    retry: false,
  })
  const actorOptions = [
    { id: 'all', label: '全部 Actor' },
    ...(detail.slot_freshness ?? []).flatMap((slot) => (
      slot.candidate_id && slot.actor_name
        ? [{ id: slot.candidate_id, label: slot.actor_name }]
        : []
    )),
    ...(actorOptionsQuery.data?.events ?? []).flatMap((event) => (
      event.candidate_id && event.actor_public_name
        ? [{ id: event.candidate_id, label: event.actor_public_name }]
        : []
    )),
  ].filter((item, index, rows) => rows.findIndex((candidate) => candidate.id === item.id) === index)
  const query = useQuery<ApifyActorDiagnosticEvents>({
    queryKey: [...queryKeys.apifyActorEvents(user.id, routeId, phase, outcome, sourceId, candidateId, windowHours), cursor],
    queryFn: ({ signal }) => api.apifyActorEvents({
      route_id: routeId,
      source_id: sourceId === 'all' ? undefined : sourceId,
      candidate_id: candidateId === 'all' ? undefined : candidateId,
      phase: phase === 'all' ? undefined : phase,
      outcome: outcome === 'all' ? undefined : outcome,
      since: new Date(Date.now() - Number(windowHours) * 60 * 60 * 1_000).toISOString(),
      cursor: cursor || undefined,
      limit: 50,
    }, signal),
    enabled: queryEnabled && Boolean(routeId),
    retry: false,
  })
  const updateFilter = (setter: (value: string) => void) => (value: string) => {
    setter(value)
    setCursor('')
  }
  return <Card variant="secondary" className="grid gap-4 border border-separator p-4" data-testid="actorops-diagnostic-timeline">
    <div><Card.Title>ActorOps 诊断时间线</Card.Title><Card.Description className="mt-1">汇总发现、验证、费用、新鲜度、切备、Key 与人工操作；只显示安全原因码和公共 Actor 名称。</Card.Description></div>
    <div className="grid gap-3 min-[640px]:grid-cols-2 min-[1100px]:grid-cols-5">
      <HeroSelect label="阶段" value={phase} onChange={updateFilter(setPhase)} options={[{ id: 'all', label: '全部阶段' }, { id: 'discovery', label: '候选发现' }, { id: 'metadata', label: '元数据检查' }, { id: 'compatibility_metadata', label: '兼容预检' }, { id: 'static_validation', label: '静态检查' }, { id: 'input_validation', label: '输入检查' }, { id: 'canary', label: 'Canary' }, { id: 'freshness', label: '新鲜度' }, { id: 'source_preference', label: '来源首选' }, { id: 'validation_key', label: '校验 Key' }]} />
      <HeroSelect label="结果" value={outcome} onChange={updateFilter(setOutcome)} options={[{ id: 'all', label: '全部结果' }, { id: 'succeeded', label: '成功' }, { id: 'failed', label: '失败' }, { id: 'queued', label: '已排队' }, { id: 'skipped', label: '已跳过' }]} />
      <HeroSelect label="来源" value={sourceId} onChange={updateFilter(setSourceId)} options={sourceOptions} />
      <HeroSelect label="Actor" value={candidateId} onChange={updateFilter(setCandidateId)} options={actorOptions} />
      <HeroSelect label="时间范围" value={windowHours} onChange={updateFilter(setWindowHours)} options={[{ id: '24', label: '最近 24 小时' }, { id: '168', label: '最近 7 天' }, { id: '720', label: '最近 30 天' }]} />
    </div>
    {query.isPending && <LoadingState label="正在读取诊断事件" rows={3} />}
    {query.isError && <HeroNotice title="诊断时间线读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void query.refetch()}>重试</Button></HeroNotice>}
    {query.data && (query.data.events.length ? <ol className="grid gap-2">{query.data.events.map((event) => <li key={event.event_id} className="min-w-0 rounded-control border border-separator bg-default p-3"><div className="flex flex-wrap items-start justify-between gap-2"><p className="type-control break-words">{event.actor_public_name || event.phase}</p><StatusIndicator label={event.outcome} tone={event.outcome === 'succeeded' ? 'success' : event.outcome === 'failed' ? 'danger' : 'warning'} /></div><p className="type-meta mt-1 break-words text-muted">{event.phase} · {event.reason_code || '无原因码'} · {formatActorDateTime(event.created_at)}</p><p className="type-meta mt-1 break-words text-muted">次数 {event.occurrence_count}{event.final_cost_usd !== null ? ` · 最终费用 ${formatActorUsd(event.final_cost_usd, true)}` : ''}{event.job_id ? ` · Job ${event.job_id.slice(-8)}` : ''}</p></li>)}</ol> : <HeroNotice title="当前筛选下没有事件" status="default">默认查看最近 24 小时，数据库最多保留 30 天。</HeroNotice>)}
    {query.data && <div className="flex items-center justify-between gap-3"><Button size="sm" variant="ghost" isDisabled={!cursor} onPress={() => setCursor('')}>返回最新</Button><Button size="sm" variant="ghost" isDisabled={!query.data.next_cursor} onPress={() => setCursor(query.data?.next_cursor || '')}>下一页</Button></div>}
  </Card>
}

export function HeroActorOpsControlPlane({
  queryEnabled = true,
  operationsContent,
}: {
  queryEnabled?: boolean
  operationsContent?: ReactNode
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab')
  const tab: ActorOpsTaskTab = rawTab && taskTabs.has(rawTab as ActorOpsTaskTab)
    ? rawTab as ActorOpsTaskTab
    : 'pool'
  const requestedProfileId = searchParams.get('route') || ''
  const selectedSourceId = tab === 'sources' ? searchParams.get('source') || '' : ''
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [discoverySettingsOpen, setDiscoverySettingsOpen] = useState(false)
  const [candidatePickerOpen, setCandidatePickerOpen] = useState(false)
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[] | null>(null)
  const [submittedDiscovery, setSubmittedDiscovery] = useState<{
    routeId: string
    runId: string
    previousRunId: string
  } | null>(null)
  const [candidateError, setCandidateError] = useState<HumanActorError | null>(null)
  const [batchTarget, setBatchTarget] = useState<CanaryBatchApprovalTarget | null>(null)
  const [batchError, setBatchError] = useState<HumanActorError | null>(null)
  const [activeBatchId, setActiveBatchId] = useState('')
  const [activationTarget, setActivationTarget] = useState<ApifyActorRouteDetail | null>(null)
  const [activationError, setActivationError] = useState<HumanActorError | null>(null)
  const [canaryTarget, setCanaryTarget] = useState<CanaryApprovalTarget | null>(null)
  const [canaryError, setCanaryError] = useState('')
  const [sourceActivationOpen, setSourceActivationOpen] = useState(false)
  const [rollbackRevision, setRollbackRevision] = useState<ApifyActorRevisionSummary | null>(null)
  const [rollbackSlot, setRollbackSlot] = useState<ApifyActorSlotName>('primary')
  const batchTriggerRef = useRef<HTMLButtonElement | null>(null)
  const candidateTriggerRef = useRef<HTMLButtonElement | null>(null)
  const activationTriggerRef = useRef<HTMLButtonElement | null>(null)
  const canaryTriggerRef = useRef<HTMLButtonElement | null>(null)
  const rollbackTriggerRef = useRef<HTMLButtonElement | null>(null)
  const sourceActivationTriggerRef = useRef<HTMLButtonElement | null>(null)
  const sourceDetailHeadingRef = useRef<HTMLDivElement | null>(null)

  const routesQuery = useQuery({
    queryKey: queryKeys.apifyActorRoutes(user.id),
    queryFn: ({ signal }) => api.apifyActorRoutes(signal),
    enabled: queryEnabled,
    retry: false,
    refetchInterval: queryEnabled ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })
  const routes = routesQuery.data?.routes ?? []
  const availableProfileIds = routes.map(routeProfileId)
  const fallbackProfileId = availableProfileIds.includes('x/profile/items')
    ? 'x/profile/items'
    : availableProfileIds[0] || ''
  const selectedProfileId = availableProfileIds.includes(requestedProfileId)
    ? requestedProfileId
    : fallbackProfileId
  const selectedSummary = routes.find((route) => routeProfileId(route) === selectedProfileId)
  const selectedRouteId = selectedSummary?.route_id ?? ''

  const detailQuery = useQuery({
    queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId),
    queryFn: ({ signal }) => api.apifyActorRoute(selectedRouteId, signal),
    enabled: queryEnabled && Boolean(selectedRouteId),
    retry: false,
    refetchInterval: (current) => {
      const kind = current.state.data?.workflow?.kind || ''
      return /(running|discovery_running|canary_running)/.test(kind) ? 3_000 : APIFY_ACTOR_ROUTE_REFRESH_MS
    },
  })
  const detail = detailQuery.data
  const refetchRoutes = routesQuery.refetch
  const refetchDetail = detailQuery.refetch
  const refreshSelected = useCallback(() => {
    void refetchRoutes()
    if (tab !== 'operations') void refetchDetail()
  }, [refetchDetail, refetchRoutes, tab])
  const poolManagement = useActorOpsPoolManagement({
    detail,
    setCandidatePickerOpen,
    setSelectedCandidateIds,
    setCandidateError,
    refreshSelected,
  })
  const { slotOperation, removeTarget, removePoolSlot } = poolManagement
  const workflow = detail?.workflow ?? selectedSummary?.workflow
  const minimumActors = detail
    ? routeMinimumActors(detail)
    : selectedSummary
      ? routeMinimumActors(selectedSummary)
      : 2
  const { next, candidateGoal, candidateTargetSlot } = actorOpsWorkflowIntent(workflow, slotOperation, minimumActors)
  const workflowFailure = workflowFailureNotice(workflow?.progress, candidateGoal)
  const submittedDiscoveryRunId = submittedDiscovery?.routeId === selectedRouteId
    ? submittedDiscovery.runId
    : ''
  const workflowDiscoveryRunId = workflow?.run_id || ''
  const workflowAdvancedPastSubmission = Boolean(
    submittedDiscoveryRunId
    && workflowDiscoveryRunId
    && workflowDiscoveryRunId !== submittedDiscovery?.previousRunId,
  )
  const trackedDiscoveryRunId = workflowAdvancedPastSubmission
    ? workflowDiscoveryRunId
    : submittedDiscoveryRunId || workflowDiscoveryRunId
  const trackedDiscoveryQuery = useQuery({
    queryKey: queryKeys.apifyActorDiscoveryRun(user.id, trackedDiscoveryRunId),
    queryFn: ({ signal }) => api.apifyActorDiscoveryRun(trackedDiscoveryRunId, signal),
    enabled: queryEnabled && tab === 'pool' && Boolean(trackedDiscoveryRunId),
    retry: false,
    refetchInterval: (current) => {
      const status = current.state.data?.status
      return status && terminalDiscoveryStatuses.has(status) ? false : 3_000
    },
  })
  const workflowDiscoveryRunning = Boolean(workflow?.kind && /discovery_running/.test(workflow.kind))
  const submittedDiscoveryRunning = Boolean(
    submittedDiscoveryRunId
    && trackedDiscoveryRunId === submittedDiscoveryRunId
    && (!trackedDiscoveryQuery.data || !terminalDiscoveryStatuses.has(trackedDiscoveryQuery.data.status)),
  )
  const discoveryRunRunning = workflowDiscoveryRunning || submittedDiscoveryRunning
  const {
    candidatesQuery,
    preferredCandidateIds,
    activeSelectedCandidateIds,
  } = useActorOpsPoolCandidates({
    routeId: selectedRouteId,
    goal: candidateGoal,
    targetSlot: candidateTargetSlot,
    queryEnabled,
    pickerOpen: candidatePickerOpen,
    selectedCandidateIds,
  })
  const verifiedActivation = useActorOpsVerifiedActivation({
    candidates: candidatesQuery.data, selectedCandidateIds: activeSelectedCandidateIds,
    detail, candidateGoal, targetSlot: candidateTargetSlot,
    onActivated: () => {
      setCandidatePickerOpen(false)
      setCandidateError(null)
      poolManagement.clearSlotOperation()
      restoreCandidateFocus()
    },
    onClosed: restoreCandidateFocus,
    onStale: refreshSelected,
  })

  const batchQuery = useQuery({
    queryKey: queryKeys.apifyActorCanaryBatch(user.id, activeBatchId),
    queryFn: ({ signal }) => api.apifyActorCanaryBatch(activeBatchId, signal),
    enabled: queryEnabled && Boolean(activeBatchId),
    retry: false,
    refetchInterval: (current) => ['queued', 'preflighting', 'running'].includes(current.state.data?.status || '') ? 3_000 : false,
  })
  const catalogQuery = useQuery({
    queryKey: queryKeys.sources(user.id),
    queryFn: ({ signal }) => api.sources(false, signal),
    enabled: queryEnabled && tab === 'sources',
    retry: false,
  })
  const sourceRows = detail?.source_validations ?? []
  const selectedSourceValid = Boolean(selectedSourceId && sourceRows.some((row) => row.source_id === selectedSourceId))
  const sourceSupportQuery = useQuery({
    queryKey: queryKeys.apifyActorSourceSupport(user.id, selectedSourceId),
    queryFn: ({ signal }) => api.apifyActorSourceSupport(selectedSourceId, signal),
    enabled: queryEnabled && tab === 'sources' && selectedSourceValid,
    retry: false,
    refetchInterval: (current) => current.state.data?.slots.some((slot) => ['queued', 'running'].includes(slot.status)) ? 3_000 : false,
  })

  useEffect(() => {
    if (!routesQuery.data || !selectedProfileId) return
    const nextParams = new URLSearchParams()
    nextParams.set('route', selectedProfileId)
    nextParams.set('tab', tab)
    if (tab === 'sources' && selectedSourceId) nextParams.set('source', selectedSourceId)
    if (nextParams.toString() !== searchParams.toString()) setSearchParams(nextParams, { replace: true })
  }, [routesQuery.data, searchParams, selectedProfileId, selectedSourceId, setSearchParams, tab])

  useEffect(() => {
    if (tab !== 'sources' || !detail || !selectedSourceId || selectedSourceValid) return
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('source')
    setSearchParams(nextParams, { replace: true })
  }, [detail, searchParams, selectedSourceId, selectedSourceValid, setSearchParams, tab])

  useEffect(() => {
    if (!selectedSourceValid) return
    sourceDetailHeadingRef.current?.focus({ preventScroll: true })
  }, [selectedSourceId, selectedSourceValid])

  useActorOpsDiscoveryCompletionRefresh({
    queryClient, userId: user.id, routeId: selectedRouteId, goal: candidateGoal,
    targetSlot: candidateTargetSlot, submittedRunId: submittedDiscoveryRunId,
    trackedRunId: trackedDiscoveryRunId,
    terminal: Boolean(trackedDiscoveryQuery.data && terminalDiscoveryStatuses.has(trackedDiscoveryQuery.data.status)),
  })

  function replaceQuery(nextTab: ActorOpsTaskTab, sourceId?: string) {
    const nextParams = new URLSearchParams()
    if (selectedProfileId) nextParams.set('route', selectedProfileId)
    nextParams.set('tab', nextTab)
    if (nextTab === 'sources' && sourceId) nextParams.set('source', sourceId)
    setSearchParams(nextParams, { replace: true })
  }

  function restoreFocus(ref: { current: HTMLButtonElement | null }) {
    window.requestAnimationFrame(() => ref.current?.focus())
  }
  function restoreCandidateFocus() { if (slotOperation) poolManagement.restoreSlotOperationFocus(); else restoreFocus(candidateTriggerRef) }
  function restoreBatchFocus() { if (slotOperation) poolManagement.restoreSlotOperationFocus(); else restoreFocus(batchTriggerRef) }
  function restoreRollbackFocus() { if (rollbackTriggerRef.current?.isConnected) restoreFocus(rollbackTriggerRef); else poolManagement.restoreSlotFocus(rollbackSlot) }
  function restoreSourceActivationFocus() {
    window.requestAnimationFrame(() => (
      sourceActivationTriggerRef.current ?? sourceDetailHeadingRef.current
    )?.focus())
  }

  const discovery = useMutation({
    mutationFn: async () => {
      if (!selectedSummary) throw new Error('route unavailable')
      return candidateTargetSlot
        ? api.refreshApifyActorPoolCandidates(
          selectedSummary.route_id,
          selectedSummary.generation,
          candidateGoal,
          candidateTargetSlot,
        )
        : api.refreshApifyActorPoolCandidates(
          selectedSummary.route_id,
          selectedSummary.generation,
          candidateGoal,
        )
    },
    onSuccess: (response) => {
      setSubmittedDiscovery({
        routeId: response.route_id,
        runId: response.run_id,
        previousRunId: workflow?.run_id || '',
      })
      if (!slotOperation) setCandidatePickerOpen(false)
      setSelectedCandidateIds([])
      setCandidateError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      if (selectedRouteId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId) })
      if (selectedRouteId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorPoolCandidates(user.id, selectedRouteId, candidateGoal, candidateTargetSlot) })
      actionToast.success('已开始免费搜索，页面会自动更新进度')
    },
    onError: (caught) => setCandidateError(humanActorError(caught)),
  })

  const preparePlan = useMutation({
    mutationFn: async () => {
      const { runId, goal } = actorOpsPoolPlanTarget(candidatesQuery.data, workflow, detail)
      if (!runId) throw new Error('plan unavailable')
      return queryClient.fetchQuery({
        queryKey: queryKeys.apifyActorCanaryPlan(user.id, runId, goal, candidateTargetSlot),
        queryFn: ({ signal }) => api.apifyActorCanaryPlan(runId, goal, signal, candidateTargetSlot),
        staleTime: 0,
      })
    },
    onSuccess: (plan) => {
      if (!plan.ready) {
        setBatchTarget(null)
        setBatchError(null)
        refreshSelected()
        actionToast.warning('候选仍不足，未启动付费验证', {
          description: '已通过的候选会保留；请继续免费搜索更多不同 Actor 或发布者。',
        })
        return
      }
      setBatchError(null)
      setBatchTarget({ plan, approvalId: crypto.randomUUID() })
    },
    onError: (caught) => actionToast.danger('当前验证计划不可用', {
      description: safeActorActionError(caught, '候选或来源已变化，请刷新状态。'),
    }),
  })

  const canaryBatch = useMutation({
    mutationFn: (target: CanaryBatchApprovalTarget) => api.createApifyActorCanaryBatch(target.plan.run_id, {
      expected_generation: target.plan.generation,
      expected_plan_hash: target.plan.plan_hash,
      approval_id: target.approvalId,
      confirmation: '确认付费验证主备',
      goal: target.plan.goal || workflow?.goal || 'initial_pool',
      max_candidates: target.plan.max_candidates,
      max_total_charge_usd: target.plan.max_total_charge_usd,
      ...(target.plan.selection_mode === 'manual' ? {
        candidate_ids: target.plan.items.map((item) => item.candidate_id).filter((value): value is string => Boolean(value)),
        candidate_validation_profiles: target.plan.items.flatMap((item) => (
          item.candidate_id && item.validation_profile ? [{
            candidate_id: item.candidate_id,
            timeout_seconds: item.validation_profile.timeout_seconds,
            sample_items: item.validation_profile.sample_items,
            max_charge_usd: item.validation_profile.max_charge_usd,
            options_hash: item.validation_profile.options_hash,
          }] : []
        )),
        target_slot_count: target.plan.target_slot_count || (
          target.plan.goal === 'compatibility_single'
            ? 1
            : target.plan.goal === 'add_slot' || target.plan.goal === 'replace_slot'
              ? ((detail?.slots.filter((slot) => Boolean(slot.revision_id)).length ?? 0)
                + (target.plan.goal === 'add_slot' ? 1 : 0)) as 1 | 2 | 3
            : target.plan.goal === 'initial_pool'
              ? minimumActors as 1 | 2 | 3
              : 3
        ),
      } : {}),
      ...(target.plan.operation_slot ? { target_slot_count: target.plan.target_slot_count, target_slot: target.plan.operation_slot } : {}),
    }),
    onSuccess: (response) => {
      setActiveBatchId(response.batch.batch_id)
      setBatchTarget(null)
      setBatchError(null)
      setSelectedCandidateIds([])
      restoreBatchFocus()
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      if (selectedRouteId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId) })
      actionToast.success('限额付费验证已提交，将严格串行执行')
    },
    onError: (caught) => {
      if (caught instanceof ApiError && [
        'apify_actor_canary_plan_conflict',
        'apify_actor_route_generation_conflict',
        'apify_actor_pool_stage_active',
      ].includes(caught.code)) {
        setBatchTarget(null)
        restoreBatchFocus()
        refreshSelected()
        actionToast.danger('配置刚刚更新，请重新选择')
        return
      }
      setBatchError(humanActorError(caught, '返回候选列表重新选择；系统不会自动重放。'))
    },
  })

  const activatePool = useMutation({
    mutationFn: (target: ApifyActorRouteDetail) => api.activateApifyActorRouteRecommendedPool(target.route_id, {
      expected_generation: target.generation,
      confirmation: '确认启用 Actor 主备',
      ...(target.workflow?.stage_id && target.workflow.plan_hash ? {
        stage_id: target.workflow.stage_id,
        expected_plan_hash: target.workflow.plan_hash,
        apply_id: crypto.randomUUID(),
      } : {}),
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCapabilities(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceTypes(user.id) })
      setActivationTarget(null)
      setActivationError(null)
      poolManagement.clearSlotOperation()
      restoreFocus(activationTriggerRef)
      actionToast.success('Actor 主备已安全生效')
    },
    onError: (caught) => {
      if (caught instanceof ApiError && [
        'apify_actor_canary_plan_conflict',
        'apify_actor_route_generation_conflict',
        'apify_actor_pool_stage_stale',
        'apify_actor_pool_stage_source_validation_incomplete',
        'apify_actor_pool_stage_precondition_incomplete',
        'apify_actor_active_pool_incomplete',
      ].includes(caught.code)) {
        setActivationTarget(null)
        restoreFocus(activationTriggerRef)
        refreshSelected()
        actionToast.danger('配置刚刚更新，请重新确认')
        return
      }
      setActivationError(humanActorError(caught, '刷新状态后重新确认；系统不会自动重放。'))
    },
  })

  const updatePool = useMutation({
    mutationFn: ({ target, draft, rollbackRevisionId }: {
      target: ApifyActorRouteDetail
      draft: PoolDraft
      rollbackRevisionId?: string
    }) => api.updateApifyActorRouteActivePool(target.route_id, {
      expected_generation: target.generation,
      ...(rollbackRevisionId ? { rollback_revision_id: rollbackRevisionId } : {}),
      slots: slotOrder.map((slot) => ({ slot, revision_id: draft[slot] })),
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      setRollbackRevision(null)
      poolManagement.restoreSlotFocus(rollbackSlot)
      actionToast.success('Actor Revision 已安全回滚')
    },
    onError: (caught) => {
      setRollbackRevision(null)
      poolManagement.restoreSlotFocus(rollbackSlot)
      refreshSelected()
      actionToast.danger('Actor Revision 回滚失败', {
        description: safeActorActionError(caught, 'Route 已变化，请刷新后重试。'),
      })
    },
  })

  const sourceCanary = useMutation({
    mutationFn: async (target: CanaryApprovalTarget) => {
      if (target.kind !== 'source') throw new Error('source validation required')
      return api.canaryApifyActorSourceRevision(target.sourceId, target.revision.revision_id, {
        expected_generation: target.expectedGeneration,
        approval_id: target.approvalId,
        confirmation: '确认付费试跑',
        max_total_charge_usd: target.capUsd,
      })
    },
    onSuccess: () => {
      setCanaryTarget(null)
      setCanaryError('')
      restoreFocus(canaryTriggerRef)
      if (selectedSourceId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorSourceSupport(user.id, selectedSourceId) })
      if (selectedRouteId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId) })
      actionToast.success('来源验证已提交')
    },
    onError: (caught) => setCanaryError(safeActorActionError(caught, '来源验证未能提交；不会自动重放。')),
  })

  const sourceActivate = useMutation({
    mutationFn: () => {
      const support = sourceSupportQuery.data
      if (!support) throw new Error('source unavailable')
      return api.activateApifyActorSourceBinding(support.source_id, {
        expected_generation: support.generation,
        confirmation: support.activation_confirmation || '确认首次启用',
      })
    },
    onSuccess: () => {
      setSourceActivationOpen(false)
      restoreSourceActivationFocus()
      void sourceSupportQuery.refetch()
      if (selectedRouteId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId) })
      actionToast.success('来源已首次启用')
    },
    onError: (caught) => actionToast.danger('来源未能启用', {
      description: safeActorActionError(caught, '来源或 Route 状态已变化，请刷新后重试。'),
    }),
  })

  const actionPending = discovery.isPending || preparePlan.isPending || verifiedActivation.isPending || canaryBatch.isPending
    || activatePool.isPending || updatePool.isPending || removePoolSlot.isPending || sourceCanary.isPending || sourceActivate.isPending
  const activePoolDraft = useMemo(() => detail ? Object.fromEntries(
    detail.slots.map((slot) => [slot.slot, slot.revision_id]),
  ) as PoolDraft : null, [detail])
  const rollbackDraft = useMemo(() => {
    if (!activePoolDraft || !rollbackRevision) return null
    return { ...activePoolDraft, [rollbackSlot]: rollbackRevision.revision_id }
  }, [activePoolDraft, rollbackRevision, rollbackSlot])
  const candidateRequiredCount = candidatesQuery.data?.required_selection_count
    ?? (['complete_third', 'compatibility_single', 'add_slot', 'replace_slot'].includes(candidateGoal)
      ? 1
      : candidateGoal === 'upgrade_legacy'
        ? 3
        : minimumActors)
  const selectedCandidates = activeSelectedCandidateIds.map((candidateId) => (
    candidatesQuery.data?.candidates.find((candidate) => candidate.candidate_id === candidateId)
  )).filter((candidate): candidate is ApifyActorPoolCandidate => Boolean(candidate))
  const { visibleCandidates: verifiedCandidates } = actorPickerCandidates(candidatesQuery.data?.candidates ?? [], candidateGoal)
  const hasPendingCandidateVerification = Boolean(candidatesQuery.data?.blockers.includes('candidate_verification_pending'))
  const candidateSelectionComplete = activeSelectedCandidateIds.length === candidateRequiredCount
    && selectedCandidates.length === activeSelectedCandidateIds.length
    && selectedCandidates.every((candidate) => candidate.already_validated === true)
  const sourceCatalog = new Map((catalogQuery.data?.sources ?? []).map((source) => [source.id, source]))
  const pendingSourceCount = detail?.source_validation_summary?.pending ?? 0
  const workflowPendingSourceCount = typeof workflow?.progress?.pending_sources === 'number'
    ? Math.max(0, Math.trunc(workflow.progress.pending_sources))
    : pendingSourceCount
  const candidateShortfall = Boolean(
    workflow?.blockers?.includes('candidate_shortfall')
    && next.action === 'start_discovery'
    && workflow?.kind !== 'compatibility_operational'
  )
  const eligibleCandidateCount = typeof workflow?.progress?.eligible_candidate_count === 'number'
    ? Math.max(0, Math.trunc(workflow.progress.eligible_candidate_count))
    : null
  const requiredSuccessCount = typeof workflow?.progress?.required_selection_count === 'number'
    ? Math.max(1, Math.trunc(workflow.progress.required_selection_count))
    : typeof workflow?.progress?.required_success_count === 'number'
      ? Math.max(1, Math.trunc(workflow.progress.required_success_count))
    : null
  const trackedDiscovery = trackedDiscoveryQuery.data
  const trackedDiscoveryProgress = trackedDiscoveryQuery.isError
    ? '暂时未读到进度，仍锁定重复提交并等待自动重试'
    : trackedDiscovery?.queries_limit
      ? `已完成 ${trackedDiscovery.queries_completed ?? 0}/${trackedDiscovery.queries_limit} 轮查询`
      : '正在准备候选检查'
  const youtubeOptionalThirdShortfall = candidateShortfall
    && workflow?.goal === 'complete_third'
    && selectedProfileId === 'youtube/channel/items'
  const discoveryFailed = Boolean(
    trackedDiscovery
    && terminalDiscoveryStatuses.has(trackedDiscovery.status)
    && trackedDiscovery.error_code
    && !candidateShortfall
    && !submittedDiscoveryRunning
  )
  const nextTitle = submittedDiscoveryRunning
    ? '正在免费搜索候选'
    : workflow?.kind === 'source_validation_required' && workflowPendingSourceCount > 0
    ? `有 ${workflowPendingSourceCount} 个来源等待启用`
    : candidateShortfall
      ? workflow?.goal === 'upgrade_legacy'
        ? '当前 Actor 尚未全部升级'
        : youtubeOptionalThirdShortfall
          ? '本轮已完成，未找到新的第三路备用'
          : workflow?.goal === 'complete_third'
            ? '本轮已完成，第三路备用候选不足'
          : '主备候选不足'
    : discoveryFailed
      ? '上次免费搜索未完成'
    : next.title
  const nextDescription = discoveryRunRunning
    ? `${trackedDiscoveryProgress}。页面每 3 秒自动刷新；完成后会显示找到的候选和失败原因，无需再次点击。`
    : candidateShortfall
    ? workflow?.goal === 'upgrade_legacy'
      ? '上面的当前 Actor 仍继续运行。重新检查只会尝试为这 3 个 Actor 生成安全新版；任一 Actor 未通过就停止，不选择替补。免费检查不会启动 Actor。'
      : youtubeOptionalThirdShortfall
        ? `${trackedDiscovery?.updated_at ? `完成于 ${formatActorDateTime(trackedDiscovery.updated_at)}。` : ''}本轮找到 ${eligibleCandidateCount ?? 0}/${requiredSuccessCount ?? 1} 个符合条件的候选。YouTube 使用认证 Actor 主抓取；第三路是可选备份。相同 Actor / Build 的失败已记录，立即重复搜索不会改变结果。`
      : `${eligibleCandidateCount !== null && requiredSuccessCount !== null
        ? `当前找到 ${eligibleCandidateCount}/${requiredSuccessCount} 个符合条件的候选。`
        : '当前符合条件的候选还不足。'}本轮已终结，已通过的候选会保留。请先查看候选与失败原因；只在 Actor / Build 证据变化后再发起新检查。`
    : discoveryFailed
      ? `${discoveryReasonLabel(trackedDiscovery?.error_code ?? '')}（错误码 ${trackedDiscovery?.error_code ?? ''}）。可重新触发免费搜索，不会启动 Actor 或产生费用。`
    : next.description
  const nextCta = discoveryRunRunning
    ? null
    : candidateShortfall
    ? workflow?.goal === 'upgrade_legacy' ? '查看当前 Actor 升级状态' : '查看候选与失败原因'
    : discoveryFailed
      ? '重新触发免费搜索'
    : next.cta

  function performNextAction() {
    if (actionPending) return
    if (candidateShortfall) {
      setSelectedCandidateIds(null)
      setCandidateError(null)
      setCandidatePickerOpen(true)
    }
    else if (next.action === 'start_discovery') discovery.mutate()
    else if (next.action === 'select_candidates') {
      setSelectedCandidateIds(null)
      setCandidateError(null)
      setCandidatePickerOpen(true)
    }
    else if (next.action === 'approve_canary') preparePlan.mutate()
    else if (next.action === 'approve_activation' && detail) setActivationTarget(detail)
    else if (next.action === 'open_sources') replaceQuery('sources')
    else if (next.action === 'open_operations') replaceQuery('operations')
    else if (next.action === 'refresh') refreshSelected()
  }

  function toggleCandidate(candidateId: string, selected: boolean) {
    setCandidateError(null)
    setSelectedCandidateIds((current) => {
      const currentIds = current ?? preferredCandidateIds
      if (!selected) return currentIds.filter((value) => value !== candidateId)
      if (candidateRequiredCount === 1) return [candidateId]
      if (currentIds.includes(candidateId) || currentIds.length >= candidateRequiredCount) return currentIds
      return [...currentIds, candidateId]
    })
  }

  return <>
    <div className="grid gap-5">
      <div className="grid gap-3 min-[768px]:grid-cols-[minmax(0,360px)_1fr] min-[768px]:items-end">
        <HeroSelect
          label="抓取类型"
          value={selectedProfileId}
          onChange={(value) => {
            setSubmittedDiscovery(null)
            setCandidatePickerOpen(false)
            setSelectedCandidateIds([])
            setCandidateError(null)
            setAdvancedOpen(false)
            setDiscoverySettingsOpen(false)
            const nextParams = new URLSearchParams()
            nextParams.set('route', value)
            nextParams.set('tab', tab)
            setSearchParams(nextParams, { replace: true })
          }}
          isDisabled={actionPending || routesQuery.isPending}
          className="w-full"
          options={(routesQuery.data?.support_profiles ?? [])
            .filter((profile) => availableProfileIds.includes(profile.id))
            .sort((left, right) => routeProfileOrder.indexOf(left.id as (typeof routeProfileOrder)[number])
              - routeProfileOrder.indexOf(right.id as (typeof routeProfileOrder)[number]))
            .map((profile) => ({
            id: profile.id,
            label: routeProductNames[profile.id]?.label || profile.label,
          }))}
        />
        {selectedSummary && <div className="flex min-h-10 items-center gap-3 px-1 py-2 min-[768px]:justify-end">
          <StatusIndicator label={next.status} tone={next.tone} role="status" />
          <span className="type-meta text-muted">{selectedSummary.runnable_slots}/3 路可用</span>
        </div>}
      </div>

      {routesQuery.isPending && <LoadingState label="正在读取 Actor 主备" rows={2} />}
      {routesQuery.isError && <HeroNotice title="Actor 主备读取失败" status="warning">
        <Button size="sm" variant="ghost" onPress={() => void routesQuery.refetch()}>重试</Button>
      </HeroNotice>}

      {selectedSummary && <Tabs selectedKey={tab} onSelectionChange={(key) => {
        if (!actionPending) {
          setCandidatePickerOpen(false)
          setSelectedCandidateIds([])
          setCandidateError(null)
          setAdvancedOpen(false)
          setDiscoverySettingsOpen(false)
          replaceQuery(String(key) as ActorOpsTaskTab)
        }
      }}>
        <div className="-mx-1 overflow-visible bg-transparent px-1 py-1">
          <Tabs.List aria-label="ActorOps 配置任务" className="grid w-full grid-cols-3 gap-1 rounded-control bg-accent/5 p-1 shadow-none">
            <Tabs.Tab id="pool" isDisabled={actionPending} className="min-h-11 min-w-0 justify-center px-2">主备配置<Tabs.Indicator /></Tabs.Tab>
            <Tabs.Tab id="sources" isDisabled={actionPending} className="min-h-11 min-w-0 justify-center gap-1 px-2">来源启用{pendingSourceCount > 0 && <CountBadge count={pendingSourceCount} label={`${pendingSourceCount} 个来源待处理`} />}<Tabs.Indicator /></Tabs.Tab>
            <Tabs.Tab id="operations" isDisabled={actionPending} className="min-h-11 min-w-0 justify-center px-2">运行与告警<Tabs.Indicator /></Tabs.Tab>
          </Tabs.List>
        </div>

        <Tabs.Panel id="pool" className="pt-5">
          {tab === 'pool' && <div className="grid gap-4">
            {detailQuery.isPending && <LoadingState label="正在读取当前主备" rows={3} />}
            {detailQuery.isError && <HeroNotice title="当前主备读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void detailQuery.refetch()}>重试</Button></HeroNotice>}
            {detail && <>
              <Card variant="secondary" className="grid gap-4 border border-separator p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div><Card.Title>当前主备</Card.Title><Card.Description className="mt-1">{detail.runnable_slots}/3 路可用 · {detail.mode === 'fallback' ? '原生优先，Actor 故障回退' : 'Actor 主抓取'}</Card.Description></div>
                  <StatusIndicator label={next.status} tone={next.tone} />
                </div>
                <ActorOpsPoolSlots detail={detail} pending={actionPending} onOperation={(goal, slot, trigger) => { if (!actionPending) poolManagement.startSlotOperation(goal, slot, trigger) }} onRemove={poolManagement.openRemoveDialog} />
              </Card>

              <Card variant="secondary" className="grid gap-4 border border-separator p-4" data-testid="actorops-next-action">
                <div className="flex flex-col gap-4 min-[720px]:flex-row min-[720px]:items-center min-[720px]:justify-between">
                  <div className="min-w-0"><Card.Title>{nextTitle}</Card.Title><Card.Description className="mt-1 max-w-3xl">{nextDescription}</Card.Description></div>
                  {nextCta && <Button
                    ref={candidateShortfall || next.action === 'select_candidates' ? candidateTriggerRef : next.action === 'approve_canary' ? batchTriggerRef : next.action === 'approve_activation' ? activationTriggerRef : undefined}
                    className="w-full shrink-0 min-[720px]:w-auto"
                    isDisabled={actionPending}
                    onPress={performNextAction}
                  >{actionPending ? '处理中…' : nextCta}</Button>}
                </div>
                {workflowFailure && <HumanActorErrorNotice error={workflowFailure} />}
                {workflow?.kind && /(setup|backup_2|legacy|compatibility)_(discovery|candidate|canary|activation)/.test(workflow.kind) && <div className="grid gap-2 border-t border-separator pt-3 type-meta text-muted min-[640px]:grid-cols-3" aria-label="配置流程">
                  <span>1. 手选安全候选（免费）</span><span>2. 付费验证（确认 1/2）</span><span>3. 生效（确认 2/2）</span>
                </div>}
              </Card>

              <SettingsDisclosure
                title="高级设置与技术详情"
                description="查看候选、费用、版本和 Discovery AI；日常配置无需展开。"
                onOpenChange={setAdvancedOpen}
              >
                {advancedOpen && <div className="grid gap-4">
                  <dl className="grid gap-3 type-meta min-[720px]:grid-cols-2">
                    <div><dt className="text-muted">Route 技术信息</dt><dd className="mt-1 break-all"><code>{detail.route_key}</code> · generation {detail.generation}</dd></div>
                    <div><dt className="text-muted">运行上限</dt><dd className="mt-1">{formatActorUsd(detail.per_run_cap_usd, true)} / Run · 更新于 {formatActorDateTime(detail.updated_at ?? null)}</dd></div>
                  </dl>
                  {workflow?.kind === 'probation_observing' && <div className="grid gap-2 min-[720px]:grid-cols-2">
                    {detail.slots.flatMap((slot) => slot.revision?.certification_progress ? [{ slot: slot.slot, progress: slot.revision.certification_progress }] : []).map(({ slot, progress }) => <div key={slot} className="rounded-control bg-default p-3 type-meta text-muted">
                      <p className="type-control text-foreground">{slotDisplayLabels[slot]} · 后台稳定性观察</p>
                      <p className="mt-1">身份 {progress.success_identities.current}/{progress.success_identities.required} · 参考来源 {progress.reference_targets.current}/{progress.reference_targets.required}</p>
                      <p className="mt-1">有效样本 {progress.valid_samples.current} · 成功率 {formatActorPercent(progress.success_rate.current)} / 目标 {formatActorPercent(progress.success_rate.required)}</p>
                      <p className="mt-1">最早自动认证：{formatActorDateTime(progress.eligible_at)}</p>
                    </div>)}
                    {!detail.slots.some((slot) => slot.revision?.certification_progress) && <p className="type-meta text-muted">观察进度暂不可用；系统仍会自动刷新，不需要手工操作。</p>}
                  </div>}
                  <DiscoveryPanel detail={detail} queryEnabled={queryEnabled && advancedOpen} activeBatch={batchQuery.data ?? null} goal={workflow?.goal || 'initial_pool'} showApprovalAction={false} onBatchCanary={() => undefined} />
                  <SettingsDisclosure title="Revision 差异与回滚" description="Build 与 Manifest 保持不可变；回滚同样受 generation 保护。">
                    <RevisionHistory detail={detail} actionPending={actionPending} onRollback={(revision, trigger) => {
                      rollbackTriggerRef.current = trigger
                      const matching = detail.slots.find((slot) => slot.revision?.actor_id === revision.actor_id)
                      setRollbackSlot(matching?.slot ?? 'primary')
                      setRollbackRevision(revision)
                    }} />
                  </SettingsDisclosure>
                  <SettingsDisclosure title="候选搜索 AI" description="只在此子区域展开后读取低频设置。" onOpenChange={setDiscoverySettingsOpen}>
                    {discoverySettingsOpen && <DiscoverySettingsPanel queryEnabled />}
                  </SettingsDisclosure>
                </div>}
              </SettingsDisclosure>
            </>}
          </div>}
        </Tabs.Panel>

        <Tabs.Panel id="sources" className="pt-5">
          {tab === 'sources' && <div className="grid gap-4">
            <div><p className="type-body">这里验证已经在“来源”页创建的账号或频道。</p><p className="type-meta mt-1 text-muted">它不会新增 Actor，也不会显示真实目标。</p></div>
            {detailQuery.isPending && <LoadingState label="正在读取来源启用状态" rows={3} />}
            {detail && <>
              <div className="flex flex-wrap gap-4 type-meta text-muted"><span>已启用 <strong className="text-foreground">{detail.source_validation_summary?.ready ?? 0}</strong></span><span>待验证 <strong className="text-foreground">{detail.source_validation_summary?.pending ?? 0}</strong></span><span>需要处理 <strong className="text-foreground">{detail.source_validation_summary?.failed ?? 0}</strong></span></div>
              {sourceRows.length === 0 ? <SettingsGroup ariaLabel="Actor 来源空状态"><SettingsItem label="还没有需要 Actor 验证的来源" description="先在来源页添加 X 或 Instagram 账号；创建后会自动出现在这里。" icon={<Icons.Plus size={17} aria-hidden="true" />} to="/subscriptions" /></SettingsGroup> : <SettingsGroup ariaLabel="Actor 来源启用列表">
                {sourceRows.map((row) => {
                  const source = sourceCatalog.get(row.source_id)
                  const status = sourceStatusPresentation(row.binding_status, detail)
                  const sourceDescription = source
                    ? `${sourceShortLabel(row.source_id)} · ${sourceActorSummary(row)}`
                    : `已脱敏来源；真实目标不会在此显示 · ${sourceActorSummary(row)}`
                  return <SettingsItem key={row.source_id} density="compact" label={source?.display_name || sourceShortLabel(row.source_id)} description={sourceDescription} icon={<Icons.RadioTower size={17} aria-hidden="true" />} trailing={<div className="flex items-center gap-2"><StatusIndicator label={status.label} tone={status.tone} /><Button size="sm" variant="ghost" onPress={() => replaceQuery('sources', row.source_id)}>{status.tone === 'success' ? '管理 Actor' : '继续验证'}</Button></div>} />
                })}
              </SettingsGroup>}
              {selectedSourceId && selectedSourceValid && <Card variant="secondary" className="grid gap-4 border border-separator p-4" aria-label={`来源 ${selectedSourceId} 验证详情`}>
                <div ref={sourceDetailHeadingRef} tabIndex={-1} data-testid="actorops-source-detail-heading" className="outline-none"><Card.Title>{sourceCatalog.get(selectedSourceId)?.display_name || sourceShortLabel(selectedSourceId)}</Card.Title><Card.Description className="mt-1">只显示当前主备的验证进度；真实目标保持隐藏。</Card.Description></div>
                {sourceSupportQuery.isPending && <LoadingState label="正在读取来源验证" rows={2} />}
                {sourceSupportQuery.data && <>
                  {sourceRows.find((row) => row.source_id === selectedSourceId) && <SourceActorPreferenceControl
                    key={`${selectedSourceId}:${sourceRows.find((row) => row.source_id === selectedSourceId)?.generation}:${sourceRows.find((row) => row.source_id === selectedSourceId)?.actor_preference?.preferred_candidate_id || 'automatic'}`}
                    detail={detail}
                    source={sourceRows.find((row) => row.source_id === selectedSourceId) as ApifyActorSourceValidation}
                  />}
                  <ol className="grid gap-2 min-[720px]:grid-cols-3" aria-label="来源主备验证槽位">{sourceSupportQuery.data.slots.map((slot) => <li key={slot.slot} className="rounded-control border border-separator bg-default p-3"><p className="type-control">{slotDisplayLabels[slot.slot]}</p><p className="type-meta mt-1 text-muted">{slot.status === 'passed' ? '已通过' : ['queued', 'running'].includes(slot.status) ? '验证中' : slot.status === 'blocked' ? '需先升级主备' : slot.status === 'failed' ? '需要处理' : '待验证'} · {formatActorDateTime(slot.last_canary_at ?? null)}</p></li>)}</ol>
                  <p className="type-meta text-muted">实际费用 {formatActorUsd(sourceSupportQuery.data.spent_usd, true)} · 已预留 {formatActorUsd(sourceSupportQuery.data.reserved_usd, true)} · 剩余 {formatActorUsd(sourceSupportQuery.data.remaining_budget_usd, true)}</p>
                  {(() => {
                    const nextAction = sourceSupportQuery.data.next_action
                    if (nextAction?.kind === 'upgrade_pool_required') return <HeroNotice title="先升级 Actor 主备" status="warning" role="alert"><p>当前兼容 Actor 没有固定 Build，无法安全验证这个来源；继续提交也不会成功。</p><p className="mt-1"><strong>影响：</strong>没有启动新的 Actor，现有抓取继续运行。</p><p className="mt-1"><strong>下一步：</strong>回到主备配置升级原 Actor，升级生效后再验证来源。</p><Button className="mt-3" size="sm" variant="secondary" onPress={() => replaceQuery('pool')}>前往主备配置</Button></HeroNotice>
                    const waiting = sourceSupportQuery.data.slots.some((slot) => ['queued', 'running'].includes(slot.status))
                    const nextSlot = sourceSupportQuery.data.slots.find((slot) => slot.can_canary)
                    if (waiting) return <HeroNotice title="来源验证正在运行" status="warning" role="status">完成后会自动显示下一项安全操作。</HeroNotice>
                    if (nextSlot) return <div className="flex flex-col gap-3 rounded-control border border-separator bg-default p-3 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between"><div><p className="type-control">下一步：验证{slotDisplayLabels[nextSlot.slot]}</p><p className="type-meta mt-1 text-muted">一次限额付费 Canary，不会并发调用其他 Actor。</p></div><Button ref={canaryTriggerRef} className="w-full min-[640px]:w-auto" onPress={() => openActorOpsSourceCanary(nextSlot, { detail, support: sourceSupportQuery.data, selectedProfileId, setError: setCanaryError, setTarget: setCanaryTarget })}>查看并确认付费验证</Button></div>
                    if (sourceSupportQuery.data.activation_confirmation) return <div className="flex flex-col gap-3 rounded-control border border-separator bg-default p-3 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between"><div><p className="type-control">所有槽位验证通过</p><p className="type-meta mt-1 text-muted">确认后首次启用这个来源。</p></div><Button ref={sourceActivationTriggerRef} className="w-full min-[640px]:w-auto" onPress={() => setSourceActivationOpen(true)}>查看并确认首次启用</Button></div>
                    return <HeroNotice title="来源已启用" status="success" role="status">后续槽位变化时，只会要求复验发生变化的部分。</HeroNotice>
                  })()}
                  <SettingsDisclosure title="来源技术详情" description="仅用于排查；不会显示目标、输入或远端 Run ID。"><dl className="grid gap-2 type-meta"><div><dt className="text-muted">来源 ID</dt><dd className="break-all"><code>{selectedSourceId}</code></dd></div><div><dt className="text-muted">Binding generation</dt><dd>{sourceSupportQuery.data.generation}</dd></div><div><dt className="text-muted">证据集</dt><dd className="break-all"><code>{sourceSupportQuery.data.verified_revision_set_hash || '尚未生成'}</code></dd></div></dl></SettingsDisclosure>
                </>}
              </Card>}
            </>}
          </div>}
        </Tabs.Panel>

        <Tabs.Panel id="operations" className="pt-5">
          {tab === 'operations' && <div className="grid gap-4">
            <p className="type-body">查看所选抓取类型的运行状态；告警设置适用于整个工作区的 ActorOps。</p>
            <Card variant="secondary" className="grid gap-3 border border-separator p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><Card.Title>运行状态</Card.Title><Card.Description className="mt-1">{selectedSummary.runnable_slots}/3 路可用 · {selectedSummary.mode === 'fallback' ? '原生优先，Actor 回退' : 'Actor 主链路'} · 单次上限 {formatActorUsd(selectedSummary.per_run_cap_usd)}</Card.Description></div><StatusIndicator label={next.status} tone={next.tone} /></div><div><Button size="sm" variant="ghost" isDisabled={routesQuery.isFetching} onPress={() => void routesQuery.refetch()}><Icons.RefreshCw size={14} className={routesQuery.isFetching ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />刷新状态</Button></div></Card>
            {detailQuery.isPending && <LoadingState label="正在读取新鲜度与诊断状态" rows={2} />}
            {detail && <ActorFreshnessPanel
              key={`${detail.route_id}:${detail.generation}:${detail.freshness?.enabled}:${detail.freshness?.interval_hours}`}
              detail={detail}
              queryEnabled={queryEnabled && tab === 'operations'}
            />}
            {detail && <ActorDiagnosticTimeline key={detail.route_id} detail={detail} queryEnabled={queryEnabled && tab === 'operations'} />}
            {operationsContent}
          </div>}
        </Tabs.Panel>
      </Tabs>}
    </div>

    <Modal isOpen={candidatePickerOpen} onOpenChange={(open) => {
      if (!open && !verifiedActivation.isPending && !discovery.isPending) {
        setCandidatePickerOpen(false)
        setSelectedCandidateIds([])
        poolManagement.clearSlotOperation()
        setCandidateError(null)
        restoreCandidateFocus()
      }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开 Actor 候选列表</Modal.Trigger>
      <Modal.Backdrop isDismissable={!verifiedActivation.isPending && !discovery.isPending} isKeyboardDismissDisabled={verifiedActivation.isPending || discovery.isPending}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{candidateGoal === 'add_slot' ? `添加 ${slotDisplayLabels[candidateTargetSlot || 'backup_2']} Actor` : candidateGoal === 'replace_slot' ? `替换 ${slotDisplayLabels[candidateTargetSlot || 'primary']} Actor` : candidateGoal === 'complete_third' ? '选择第三个备用 Actor' : candidateGoal === 'upgrade_legacy' ? '升级当前 3 个 Actor' : `选择 ${candidateRequiredCount} 个已验证 Actor`}</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-4" aria-busy={candidatesQuery.isPending || verifiedActivation.isPending || discovery.isPending}>
          {discoveryRunRunning && <HeroNotice title="正在搜索，无需重复点击" status="warning" role="status">
            {trackedDiscoveryProgress}。完成后页面会自动显示新候选或明确的失败原因。
          </HeroNotice>}
          {!discoveryRunRunning && trackedDiscovery && terminalDiscoveryStatuses.has(trackedDiscovery.status) && <HeroNotice title={trackedDiscovery.error_code ? '最近一轮免费搜索未完成' : '最近一轮免费搜索已结束'} status={trackedDiscovery.error_code ? 'warning' : 'default'} role="status">
            {trackedDiscovery.error_code
              ? `${discoveryReasonLabel(trackedDiscovery.error_code)}（错误码 ${trackedDiscovery.error_code}）。`
              : `完成于 ${formatActorDateTime(trackedDiscovery.updated_at ?? null)} · 查询 ${trackedDiscovery.queries_completed ?? 0}/${trackedDiscovery.queries_limit ?? 0} 轮。`}本轮免费检查的库存只供服务器受控筛选，不会显示在这里；只有真实目标、全部启用来源和费用对账均通过的 Actor 才会加入本列表。
          </HeroNotice>}
          <HeroNotice title="这里只显示已验证 Actor" status="default" role="status">每一项都已在当前平台用真实目标完成 Route 与所有启用来源验证，并已完成费用对账。选择后只会进行无费用的原子启用或替换；待测、失败和过期项不会出现在这里。</HeroNotice>
          {candidatesQuery.isPending && <LoadingState label="正在读取可选 Actor" rows={3} />}
          {candidatesQuery.isError && <HumanActorErrorNotice error={humanActorError(candidatesQuery.error)} />}
          {candidatesQuery.data && <>
            <div className="flex items-center justify-between gap-3 type-meta text-muted"><span>请选择 {candidateRequiredCount} 个</span><span aria-live="polite">已选 {activeSelectedCandidateIds.length}/{candidateRequiredCount}</span></div>
            {verifiedCandidates.length > 0 ? <div className="grid gap-2" role="group" aria-label="已验证 Actor">
              {verifiedCandidates.map((candidate) => {
                const selected = activeSelectedCandidateIds.includes(candidate.candidate_id)
                return <div key={candidate.candidate_id} className="rounded-control border border-separator bg-surface-secondary p-3">
                  <Checkbox isSelected={selected} isDisabled={candidateRequiredCount > 1 && activeSelectedCandidateIds.length >= candidateRequiredCount && !selected || verifiedActivation.isPending} onChange={(value) => toggleCandidate(candidate.candidate_id, value)}>
                    <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><span className="min-w-0"><span className="block type-control break-words">{candidate.actor_public_name}</span><span className="mt-1 block type-meta text-muted">发布者 {candidate.publisher} · {poolCandidatePricingLabel(candidate)} · 已完成真实目标验证与费用对账</span><ActorStoreQuality quality={candidate.store_quality} /></span></Checkbox.Content>
                  </Checkbox>
                </div>
              })}
            </div> : <HeroNotice title="暂时没有可选择的已验证 Actor" status="warning">{hasPendingCandidateVerification ? '系统已找到待实测项，正在受控验证；只有真实目标和所有启用来源均通过且费用对账完成后，才会显示在这里。' : '当前没有通过完整实测的候选。现有线路不会改变。'}</HeroNotice>}
          </>}
          {candidateError && <HumanActorErrorNotice error={candidateError} />}
        </div></Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={verifiedActivation.isPending || discovery.isPending} onPress={() => { setCandidatePickerOpen(false); setSelectedCandidateIds([]); poolManagement.clearSlotOperation(); setCandidateError(null); restoreCandidateFocus() }}>取消</Button>
          <Button variant="secondary" isDisabled={verifiedActivation.isPending || discovery.isPending || discoveryRunRunning} onPress={() => discovery.mutate()}>{discoveryRunRunning ? '正在搜索，自动刷新…' : discovery.isPending ? '正在搜索…' : slotOperation ? '自动搜索候选（免费）' : '更新待测 Actor（免费）'}</Button>
          {hasPendingCandidateVerification && <Button variant="secondary" isDisabled={preparePlan.isPending || discovery.isPending} onPress={() => { setCandidatePickerOpen(false); preparePlan.mutate() }}>{preparePlan.isPending ? '正在生成实测计划…' : '更新已验证 Actor 库'}</Button>}
          <Button isDisabled={!candidateSelectionComplete || verifiedActivation.isPending || discovery.isPending} onPress={() => { verifiedActivation.prepare(); setCandidatePickerOpen(false) }}>选择并启用</Button>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
    <ActorOpsRemovePoolDialog target={removeTarget} pending={removePoolSlot.isPending} onClose={poolManagement.closeRemoveDialog} onConfirm={(target) => removePoolSlot.mutate(target)} />

    <ActorOpsBatchConfirmationDialog
      view={toBatchConfirmationView(batchTarget?.plan ?? null)}
      error={batchError} pending={canaryBatch.isPending}
      onCancel={() => { setBatchTarget(null); setBatchError(null); restoreBatchFocus() }}
      onConfirm={() => { if (batchTarget) canaryBatch.mutate(batchTarget) }} />
    <ActorOpsActivationConfirmationDialog
      view={toActivationConfirmationView(activationTarget)}
      error={activationError} pending={activatePool.isPending}
      onCancel={() => { setActivationTarget(null); setActivationError(null); restoreFocus(activationTriggerRef) }}
      onConfirm={() => { if (activationTarget) activatePool.mutate(activationTarget) }} />
    <ActorOpsSourceCanaryConfirmationDialog
      view={toSourceCanaryConfirmationView(canaryTarget?.kind === 'source' ? canaryTarget : null)}
      error={canaryError} pending={sourceCanary.isPending}
      onCancel={() => { setCanaryTarget(null); setCanaryError(''); restoreFocus(canaryTriggerRef) }}
      onConfirm={() => { if (canaryTarget) sourceCanary.mutate(canaryTarget) }} />
    <ActorOpsSourceActivationConfirmationDialog
      open={sourceActivationOpen}
      pending={sourceActivate.isPending}
      onCancel={() => { setSourceActivationOpen(false); restoreSourceActivationFocus() }}
      onConfirm={() => sourceActivate.mutate()} />
    <ActorOpsRollbackConfirmationDialog
      view={toRollbackConfirmationView(rollbackRevision, rollbackSlot, Boolean(detail && rollbackDraft))}
      pending={updatePool.isPending} onSlotChange={setRollbackSlot}
      onCancel={() => { setRollbackRevision(null); restoreRollbackFocus() }}
      onConfirm={() => detail && rollbackDraft && rollbackRevision && updatePool.mutate({
        target: detail, draft: rollbackDraft, rollbackRevisionId: rollbackRevision.revision_id,
      })} />
    <ActorOpsVerifiedActivationConfirmationDialog
      target={verifiedActivation.target} error={verifiedActivation.error}
      pending={verifiedActivation.isPending} onCancel={verifiedActivation.cancel}
      onConfirm={verifiedActivation.confirm} />
  </>
}
