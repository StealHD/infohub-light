import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type {
  ApifyActorDiscoveryCandidate,
  ApifyActorCanaryBatch,
  ApifyActorCanaryPlan,
  ApifyActorDiscoverySettingsPatch,
  ApifyActorPaidCanaryRequest,
  ApifyActorRevisionSummary,
  ApifyActorRouteActiveSlot,
  ApifyActorRouteDetail,
  ApifyActorRouteRuntimeStatus,
  ApifyActorRouteSummary,
  ApifyActorRouteSupportStatus,
  ApifyActorSlotName,
  ApifyActorSourceSupport,
  ApifyActorSupportProfile,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Card,
  Description,
  FieldError,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  StatusIndicator,
  Switch,
  Table,
  TextField,
} from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import {
  APIFY_ACTOR_ROUTE_REFRESH_MS,
  formatActorDateTime,
  formatActorUsd,
  safeActorActionError,
} from './apifyActorModel'

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

const supportPresentation: Record<ApifyActorRouteSupportStatus, {
  label: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}> = {
  supported: { label: '已支持', tone: 'success' },
  degraded: { label: '支持待补位', tone: 'warning' },
  pending: { label: '发现或认证中', tone: 'warning' },
  unsupported: { label: '暂不支持', tone: 'neutral' },
  blocked: { label: '支持已阻断', tone: 'danger' },
}

const runtimePresentation: Record<ApifyActorRouteRuntimeStatus, {
  label: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}> = {
  ready: { label: '运行就绪', tone: 'success' },
  degraded: { label: '降级运行', tone: 'warning' },
  blocked: { label: '运行已阻断', tone: 'danger' },
  exhausted: { label: '可用 Actor 不足', tone: 'danger' },
  budget_blocked: { label: '费用保护已暂停', tone: 'danger' },
}

const lifecycleLabels: Record<ApifyActorRevisionSummary['lifecycle'], string> = {
  proposed: '待静态校验',
  static_valid: '静态校验通过',
  probationary: '试运行',
  certified: '已认证',
  legacy_builtin: '旧版内建',
  quarantined: '已隔离',
  superseded: '已被替代',
  rejected: '已拒绝',
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
  apify_actor_target_identity_mismatch: 'Dataset 内容无法确认属于目标账号或频道',
  apify_manifest_output_pointer_unverifiable: 'Manifest 字段路径不在固定 Build Dataset Schema 中',
  apify_manifest_item_identity_invalid: 'Manifest 把频道或主页本身错误映射成内容条目',
  apify_actor_metadata_only: 'Actor 只返回频道资料，没有返回视频内容；该 Build 已停止重复试跑',
  apify_manifest_source_identity_invalid: 'Manifest 错把内容 URL 当作来源身份',
}

type PoolDraft = Record<ApifyActorSlotName, string | null>

type CanaryRouteContext = {
  routeKey: string
  routeLabel: string
  routeMode: 'primary' | 'fallback'
  actorPricingLabel: string
  buildLabel: string
}

type CanaryTarget =
  | (CanaryRouteContext & {
    kind: 'discovery'
    runId: string
    candidate: ApifyActorDiscoveryCandidate
    expectedGeneration: number
    capUsd: number
    routeBudgetUsd: number
    routeSpentUsd: number
  })
  | (CanaryRouteContext & {
    kind: 'source'
    sourceId: string
    revision: ApifyActorRevisionSummary
    expectedGeneration: number
    capUsd: number
  })

type CanaryApprovalTarget = CanaryTarget & {
  approvalId: string
}

type CanaryBatchApprovalTarget = {
  plan: ApifyActorCanaryPlan
  approvalId: string
}

type DiscoverySettingsDraft = {
  enabled: boolean
  aiConfigId: string
  maxQueriesPerRun: string
  maxCandidates: string
  maxOutputTokens: string
}

function routeIdentity(platform: string, targetType: string, capability: string): string {
  return `${platform} / ${targetType} / ${capability}`
}

function revisionCertificationLabel(revision: ApifyActorRevisionSummary): string {
  if (revision.lifecycle === 'certified') return '已完成 Route 认证，可用于 Primary、Backup 1 或 Backup 2'
  if (revision.lifecycle === 'probationary') {
    return '已通过首个参考 Canary，可进入两路快速主备；完成完整观察后可升级为 certified'
  }
  if (revision.lifecycle === 'static_valid') return '仅完成静态校验，尚未取得成功的 Route 参考 Canary'
  if (revision.lifecycle === 'legacy_builtin') return '旧版兼容 Revision，仅保留既有 Route 运行'
  return '当前 Revision 不能进入 Active Pool'
}


function actorPricingLabel(revision: ApifyActorRevisionSummary): string {
  const pricing = revision.pricing
  if (!pricing || pricing.billing_unit === 'unknown') return '定价快照不可用'
  if (pricing.billing_unit === 'free') return '免费 Actor'
  const minimum = pricing.unit_price_min_usd
  const maximum = pricing.unit_price_max_usd
  const price = minimum === null || minimum === undefined
    ? '标价未提供'
    : maximum !== null && maximum !== undefined && Math.abs(maximum - minimum) > 1e-9
      ? `${formatActorUsd(minimum, true)}–${formatActorUsd(maximum, true)}`
      : formatActorUsd(minimum, true)
  const unit = pricing.billing_unit === 'dataset_item' ? '每 Dataset 行' : '每计费事件'
  const cap = pricing.minimum_run_cap_usd
  return `${price} ${unit}${cap !== null && cap !== undefined
    ? ` · Actor 最低 Run 上限 ${formatActorUsd(cap, true)}`
    : ''}`
}

function shortRevision(revisionId: string | null | undefined): string {
  if (!revisionId) return '未绑定'
  return revisionId.length > 16 ? `${revisionId.slice(0, 8)}…${revisionId.slice(-6)}` : revisionId
}

function discoveryReasonLabel(reason: string): string {
  return discoveryReasonLabels[reason] || '候选未通过当前安全规则'
}

function discoveryFailureTitle(phase: string | null | undefined): string {
  if (phase === 'store' || phase === 'metadata') return 'Store / Actor 元数据读取需要处理'
  if (phase === 'input_validation') return '固定 Build 输入校验需要处理'
  if (phase === 'ai_generation') return 'Discovery AI 生成需要处理'
  if (phase === 'static_validation') return 'Manifest 静态校验需要处理'
  if (phase === 'route_canary') return '本轮 Route Canary 已停止'
  return '发现任务需要处理'
}

function canaryDurationLabel(durationMs: number | null | undefined): string {
  if (durationMs === null || durationMs === undefined) return '耗时未知'
  return `耗时 ${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)} 秒`
}

function routeStatusIcon(tone: 'neutral' | 'success' | 'warning' | 'danger') {
  if (tone === 'success') return <Icons.CircleCheck size={14} aria-hidden="true" />
  if (tone === 'danger') return <Icons.CircleX size={14} aria-hidden="true" />
  if (tone === 'warning') return <Icons.TriangleAlert size={14} aria-hidden="true" />
  return <Icons.CircleDashed size={14} aria-hidden="true" />
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3">
    <p className="type-meta text-muted">{label}</p>
    <p className="type-page-title mt-1 break-words tabular-nums">{value}</p>
    {detail && <p className="type-meta mt-1 break-words text-muted">{detail}</p>}
  </div>
}

function RouteList({
  selectedRouteId,
  onSelect,
  routes,
}: {
  selectedRouteId: string
  onSelect: (routeId: string) => void
  routes: ApifyActorRouteSummary[]
}) {
  return <Table variant="secondary" className="max-w-full">
    <Table.ScrollContainer className="max-w-full overflow-x-auto" data-testid="actor-ops-route-scroll">
      <Table.Content aria-label="ActorOps 路由列表">
        <Table.Header>
          <Table.Column isRowHeader>平台 / 目标 / 能力</Table.Column>
          <Table.Column>支持状态</Table.Column>
          <Table.Column>运行状态</Table.Column>
          <Table.Column>可用度</Table.Column>
          <Table.Column>费用上限</Table.Column>
          <Table.Column>操作</Table.Column>
        </Table.Header>
        <Table.Body
          items={routes}
          renderEmptyState={() => <div className="p-6 text-center text-muted">尚未建立 Actor Route</div>}
        >
          {(route) => {
            const support = supportPresentation[route.support_status]
            const runtime = runtimePresentation[route.runtime_status]
            return <Table.Row id={route.route_id}>
              <Table.Cell>
                <div className="min-w-56">
                  <p className="type-control">{routeIdentity(route.platform, route.target_type, route.capability)}</p>
                  <code className="type-meta mt-1 block break-all text-muted">{route.route_key}</code>
                  <p className="type-meta mt-1 text-muted">{route.mode === 'fallback' ? '原生优先，Actor 回退' : 'Actor 主链路'}</p>
                </div>
              </Table.Cell>
              <Table.Cell>
                <StatusIndicator
                  label={support.label}
                  tone={support.tone}
                  icon={routeStatusIcon(support.tone)}
                />
              </Table.Cell>
              <Table.Cell>
                <StatusIndicator
                  label={runtime.label}
                  tone={runtime.tone}
                  icon={routeStatusIcon(runtime.tone)}
                />
              </Table.Cell>
              <Table.Cell>
                <div className="min-w-36">
                  <p className="type-control tabular-nums">{route.runnable_slots}/3 可用</p>
                  <p className="type-meta mt-1 text-muted">{route.publisher_count} 个发布者</p>
                </div>
              </Table.Cell>
              <Table.Cell>
                <p className="min-w-28 type-control tabular-nums">{formatActorUsd(route.per_run_cap_usd)} / Run</p>
              </Table.Cell>
              <Table.Cell>
                <Button
                  size="sm"
                  variant={selectedRouteId === route.route_id ? 'secondary' : 'ghost'}
                  aria-current={selectedRouteId === route.route_id ? 'true' : undefined}
                  onPress={() => onSelect(route.route_id)}
                >{selectedRouteId === route.route_id ? '正在查看' : '查看详情'}</Button>
              </Table.Cell>
            </Table.Row>
          }}
        </Table.Body>
      </Table.Content>
    </Table.ScrollContainer>
  </Table>
}

function ActorPoolPlan({
  detail,
  actionPending,
  onConfirm,
}: {
  detail: ApifyActorRouteDetail
  actionPending: boolean
  onConfirm: () => void
}) {
  const recommendation = detail.activation_recommendation
  const activeSlots = detail.slots.filter((slot) => slot.revision)
  const alreadyActive = recommendation?.already_active ?? activeSlots.length === 3
  const expedited = recommendation?.activation_mode === 'expedited_2of3'
  const displaySlots = alreadyActive
    ? detail.slots
    : recommendation?.ready
      ? recommendation.slots.map((slot) => ({ ...slot, runnable: false }))
      : []

  if (!alreadyActive && !recommendation?.ready) {
    const runnable = recommendation?.runnable_actor_count
      ?? recommendation?.backup_2_actor_count
      ?? 0
    const publishers = recommendation?.publisher_count ?? 0
    return <div className="grid gap-3">
      <HeroNotice title="候选审批尚未完成，你现在无需配置" status="warning" role="status">
        至少需要两个成功试跑、Actor 不同且发布者不同的固定 Build。满足后系统会自动生成快速主备方案；这里不会要求选择 Revision 或手工排槽。
      </HeroNotice>
      <div className="grid gap-3 min-[640px]:grid-cols-3">
        <Metric label="成功试跑 Actor" value={`${Math.min(runnable, 2)}/2`} detail="每个 Actor 至少成功一次 Canary" />
        <Metric label="不同 Actor 候选" value={`${Math.min(runnable, 2)}/2`} detail="主用和备用不能是同一 Actor" />
        <Metric label="候选发布者" value={`${Math.min(publishers, 2)}/2`} detail="两路必须来自不同发布者" />
      </div>
    </div>
  }

  return <div className="grid gap-3">
    <HeroNotice
      title={alreadyActive
        ? expedited ? '两路 Actor 主备已生效' : 'Actor 主备已生效'
        : expedited ? '两路主备已可快速启用' : '系统已完成候选审批'}
      status={alreadyActive ? 'success' : 'default'}
      role="status"
    >
      {alreadyActive
        ? expedited
          ? '当前 Route 以两个成功试跑的固定 Build 降级运行；少于两路仍会自动阻断，第三槽可后续热补位。'
          : '当前 Route 已按 2+1 规则运行；日常故障切换由系统自动完成。'
        : expedited
          ? '以下两个 Actor 均已成功试跑，来自不同发布者并固定 Build。第三槽先留空，你无需继续付费认证即可确认生效。'
          : '以下方案已由后端重新校验 2+1、Actor 唯一、发布者分散和固定 Build。你只需确认一次即可生效。'}
    </HeroNotice>
    <ol className="grid gap-3 min-[760px]:grid-cols-3" aria-label={alreadyActive ? '当前 Actor 主备方案' : '系统推荐 Actor 主备方案'}>
      {displaySlots.map((slot) => {
        const revision = slot.revision
        return <li key={slot.slot} className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="type-meta text-muted">{slotDisplayLabels[slot.slot]}</p>
            <StatusIndicator
              label={revision ? lifecycleLabels[revision.lifecycle] : '未绑定'}
              tone={revision?.lifecycle === 'certified'
                ? 'success'
                : revision?.lifecycle === 'probationary' || revision?.lifecycle === 'legacy_builtin'
                  ? 'warning'
                  : 'neutral'}
              icon={alreadyActive && slot.runnable
                ? <Icons.CircleCheck size={13} aria-hidden="true" />
                : <Icons.CircleDashed size={13} aria-hidden="true" />}
            />
          </div>
          <p className="type-control mt-2 break-words">{revision?.actor_public_name || revision?.actor_id || '待后续补位'}</p>
          <p className="type-meta mt-1 break-words text-muted">{revision ? `${revision.publisher || '发布者未知'} · Build ${revision.build_number || revision.build_id || 'legacy'}` : '当前不参与运行，也不会产生费用'}</p>
          <p className="type-meta mt-2 text-muted">最近 Canary：{revision?.last_canary_status || (revision ? '尚未记录' : '无需验证')}</p>
        </li>
      })}
    </ol>
    {!alreadyActive && <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="type-meta text-muted">
        {detail.mode === 'fallback' ? '原生链路优先，只有允许回退的故障才调用 Actor。' : '该来源类型启用后以 Actor 为主链路。'}
        {' '}单次费用最高 {formatActorUsd(detail.per_run_cap_usd)}。
      </p>
      <Button size="sm" isDisabled={actionPending} onPress={onConfirm}>
        {expedited ? '确认先启用两路主备' : '确认启用 Actor 主备'}
      </Button>
    </div>}
  </div>
}

function DiscoveryPanel({
  detail,
  queryEnabled,
  activeBatch,
  onBatchCanary,
}: {
  detail: ApifyActorRouteDetail
  queryEnabled: boolean
  activeBatch: ApifyActorCanaryBatch | null
  onBatchCanary: (plan: ApifyActorCanaryPlan) => void
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
    queryKey: queryKeys.apifyActorCanaryPlan(user.id, runId),
    queryFn: ({ signal }) => api.apifyActorCanaryPlan(runId, signal),
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
        detail={`${run.candidate_count ?? run.candidates.length}/3 Actor · ${publisherCount}/2 发布者；付费验证只统计真实启动`}
      />
    </div>
    {run.error_code && <HeroNotice title={discoveryFailureTitle(run.failure_phase)} status="warning">
      {discoveryReasonLabel(run.error_code)}。安全错误码：<code>{run.error_code}</code>
    </HeroNotice>}
    {displayedBatch && <HeroNotice
      title={displayedBatch.stop_reason === 'apify_start_not_created'
        ? 'Apify 已确认未创建 Run：本次费用 $0，系统没有自动重跑'
        : displayedBatch.status === 'activation_ready'
        ? '两路主备验证完成，可以确认启用'
        : paidBatchRunning
          ? `正在串行验证主备（${displayedBatch.success_count}/2 成功）`
          : displayedBatch.status === 'partial'
            ? '本批候选未凑齐两路，系统正在补位发现（不会启动 Actor）'
            : '主备验证批次已结束'}
      status={displayedBatch.status === 'activation_ready' ? 'success' : paidBatchRunning ? 'warning' : 'default'}
    >
      实际费用 {displayedBatch.actual_cost_usd === null || displayedBatch.actual_cost_usd === undefined
        ? '待远端对账'
        : formatActorUsd(displayedBatch.actual_cost_usd, true)}；
      未启动或不再需要的候选费用为 $0。批次状态：<code>{displayedBatch.status}</code>。
    </HeroNotice>}
    {!detail.activation_recommendation?.ready && !paidBatchRunning && planQuery.data?.ready && <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-separator bg-surface-secondary p-3">
      <div>
        <p className="type-control">一次确认，系统验证两路主备</p>
        <p className="type-meta mt-1 text-muted">
          服务器已选择 {planQuery.data.items.length} 个候选，严格串行；两位不同发布者成功后立即停止。全部候选总封顶 {formatActorUsd(planQuery.data.max_total_charge_usd, true)}。
        </p>
      </div>
      <Button
        size="sm"
        isDisabled={paidBatchRunning}
        onPress={() => onBatchCanary(planQuery.data)}
      ><Icons.FlaskConical size={14} aria-hidden="true" />验证两路主备</Button>
    </div>}
    {!detail.activation_recommendation?.ready && planQuery.isError && <HeroNotice title="当前候选还不能组成安全的两路主备" status="warning">
      无需反复刷新或逐个试跑；系统会保留已有成功证据，并在候选用尽时自动创建不会启动 Actor 的补位发现任务。
    </HeroNotice>}
    {Boolean(run.rejections?.length) && <HeroNotice title="确定性淘汰摘要" status="default">
      <ul className="list-disc space-y-1 pl-5 type-meta text-muted">
        {run.rejections?.map((item) => <li key={item.reason}>
          {discoveryReasonLabel(item.reason)} · <code>{item.reason}</code> · {item.count} 个
        </li>)}
      </ul>
    </HeroNotice>}
    <ol className="grid gap-2" aria-label="Actor 发现候选">
      {run.candidates.map((candidate) => <li
        key={candidate.revision.revision_id}
        className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="type-control">
              {candidate.rank ? `#${candidate.rank} · ` : ''}
              {candidate.revision.actor_public_name || candidate.revision.actor_id}
            </p>
            <p className="type-meta mt-1 break-words text-muted">
              {candidate.revision.publisher} · Build {candidate.revision.build_number || candidate.revision.build_id || '未固定'}
              {' · '}{lifecycleLabels[candidate.revision.lifecycle]}
            </p>
            <code className="type-meta mt-1 block break-all text-muted">{shortRevision(candidate.revision.revision_id)}</code>
            <div className="mt-2 grid gap-1 type-meta text-muted">
              <p>所属 Route：{routeIdentity(detail.platform, detail.target_type, detail.capability)} · <code>{detail.route_key}</code></p>
              <p>参考来源：Route 认证公开参考来源（真实目标已脱敏）</p>
              <p>Actor 定价：{actorPricingLabel(candidate.revision)}</p>
              <p>本次单次上限：{formatActorUsd(Math.min(
                detail.per_run_cap_usd,
                Math.max(0, run.budget_cap_usd - (run.spent_usd ?? 0)),
              ), true)}</p>
              <p>认证进度：{revisionCertificationLabel(candidate.revision)}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusIndicator
              label={candidate.canary_in_flight
                ? `Canary ${candidate.validation_status || '运行中'}`
                : candidate.awaiting_approval
                  ? '等待付费审批'
                  : candidate.validation_status === 'failed'
                    ? 'Canary 失败'
                    : candidate.status}
              tone={candidate.rejection_reasons?.length
                ? 'danger'
                : candidate.canary_in_flight || candidate.awaiting_approval ? 'warning' : 'neutral'}
              icon={candidate.rejection_reasons?.length
                ? <Icons.CircleX size={13} aria-hidden="true" />
                : <Icons.CircleDashed size={13} aria-hidden="true" />}
            />
          </div>
        </div>
        {Boolean(candidate.rejection_reasons?.length) && <ul className="mt-2 list-disc space-y-1 pl-5 type-meta text-muted">
          {candidate.rejection_reasons?.map((reason) => <li key={reason}>
            {discoveryReasonLabel(reason)} · <code>{reason}</code>
          </li>)}
        </ul>}
        {candidate.validation_status === 'failed' && <div className="mt-2 rounded-control border border-separator bg-surface-primary p-3 type-meta text-muted">
          <p className="text-default">{discoveryReasonLabel(candidate.validation_outcome || 'unknown')}</p>
          <p className="mt-1 break-words">
            安全错误码：<code>{candidate.validation_outcome || 'unknown'}</code>
            {' · '}{canaryDurationLabel(candidate.validation_duration_ms)}
            {' · '}远端终态 {candidate.actor_run_status || '未知'}
            {' · '}实际费用 {candidate.validation_cost_usd === null || candidate.validation_cost_usd === undefined
              ? '未知'
              : formatActorUsd(candidate.validation_cost_usd, true)}
            {candidate.validation_cost_final ? '（已终结）' : '（待对账）'}
          </p>
        </div>}
      </li>)}
    </ol>
  </div>
}

function RevisionHistory({
  detail,
  onRollback,
  actionPending,
}: {
  detail: ApifyActorRouteDetail
  onRollback: (revision: ApifyActorRevisionSummary) => void
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
            onPress={() => onRollback(revision)}
          ><Icons.RotateCcw size={14} aria-hidden="true" />回滚到此 Revision</Button>
        </li>)}
      </ol>}
  </div>
}

function SourceSupportPanel({
  detail,
  queryEnabled,
  onCanary,
}: {
  detail: ApifyActorRouteDetail
  queryEnabled: boolean
  onCanary: (target: CanaryTarget) => void
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [sourceInput, setSourceInput] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [activationConfirmation, setActivationConfirmation] = useState('')
  const [sourceCanaryCapDraft, setSourceCanaryCapDraft] = useState('')
  const query = useQuery({
    queryKey: queryKeys.apifyActorSourceSupport(user.id, sourceId),
    queryFn: ({ signal }) => api.apifyActorSourceSupport(sourceId, signal),
    enabled: queryEnabled && Boolean(sourceId),
    retry: false,
    refetchInterval: (current) => current.state.data?.slots.some((slot) => (
      ['queued', 'running'].includes(slot.status)
    )) ? 3_000 : false,
  })
  const support = query.data
  const supportSourceId = support?.source_id
  const supportGeneration = support?.generation
  const sourceRemainingBudget = support?.remaining_budget_usd
  const sourceCanaryMaximum = Math.min(
    detail.per_run_cap_usd,
    sourceRemainingBudget ?? 0,
  )
  const sourceCanaryCapValue = Number(sourceCanaryCapDraft)
  const sourceCanaryCapValid = Number.isFinite(sourceCanaryCapValue)
    && sourceCanaryCapValue > 0
    && sourceCanaryCapValue <= sourceCanaryMaximum + 1e-9
  useEffect(() => {
    if (!supportSourceId || sourceRemainingBudget === undefined) return
    const nextCap = Math.min(
      0.02,
      detail.per_run_cap_usd,
      sourceRemainingBudget,
    )
    // Source/binding budget changes are the reset boundary for paid input.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSourceCanaryCapDraft(String(nextCap))
  }, [detail.per_run_cap_usd, sourceRemainingBudget, supportGeneration, supportSourceId])
  const activate = useMutation({
    mutationFn: ({ support, confirmation }: {
      support: ApifyActorSourceSupport
      confirmation: string
    }) => api.activateApifyActorSourceBinding(support.source_id, {
      expected_generation: support.generation,
      confirmation,
    }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.apifyActorSourceSupport(user.id, result.source_id),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.apifyActorRoutes(user.id),
      })
      setActivationConfirmation('')
      actionToast.success('来源 Actor Route 已启用')
    },
    onError: (caught) => {
      void query.refetch()
      actionToast.danger('来源启用失败', {
        description: safeActorActionError(caught, '来源状态或 generation 已变化，请刷新后重试。'),
      })
    },
  })

  const embedded = detail.source_validations ?? []
  const configuredRouteSlots = detail.slots.filter((slot) => slot.revision)
  const routeConfiguredForSources = detail.support_status === 'supported'
    && detail.runnable_slots >= detail.min_runtime_healthy
    && configuredRouteSlots.length >= detail.min_runtime_healthy
    && configuredRouteSlots.every((slot) => (
      slot.revision
      && ['probationary', 'certified'].includes(slot.revision.lifecycle)
    ))
  const requiredConfirmation = support?.activation_confirmation || '确认首次启用'
  const activeSupportSlots = support?.slots.filter((slot) => slot.revision_id) ?? []
  const requiredSourceCanaries = activeSupportSlots.length || detail.runnable_slots
  const allSlotsPassed = Boolean(
    support
    && activeSupportSlots.length >= detail.min_runtime_healthy
    && activeSupportSlots.every((slot) => slot.status === 'passed'),
  )
  const revisionMap = new Map((detail.revisions ?? []).map((revision) => [revision.revision_id, revision]))

  function submitLookup(event: FormEvent) {
    event.preventDefault()
    const trimmed = sourceInput.trim()
    if (!trimmed) return
    if (trimmed === sourceId) {
      void query.refetch()
      return
    }
    setSourceId(trimmed)
  }

  return <div className="grid gap-4">
    <div className="grid gap-3 min-[720px]:grid-cols-3">
      <Metric label="已就绪来源" value={String(detail.source_validation_summary?.ready ?? 0)} />
      <Metric label="待验证来源" value={String(detail.source_validation_summary?.pending ?? 0)} />
      <Metric label="验证失败来源" value={String(detail.source_validation_summary?.failed ?? 0)} />
    </div>

    {embedded.length > 0 && <Table variant="secondary" className="max-w-full">
      <Table.ScrollContainer className="max-w-full overflow-x-auto">
        <Table.Content aria-label="Route 来源级验证进度">
          <Table.Header>
            <Table.Column isRowHeader>来源</Table.Column>
            <Table.Column>绑定状态</Table.Column>
            <Table.Column>Primary</Table.Column>
            <Table.Column>Backup 1</Table.Column>
            <Table.Column>Backup 2</Table.Column>
          </Table.Header>
          <Table.Body items={embedded}>
            {(source) => <Table.Row id={source.source_id}>
              <Table.Cell>
                <p className="min-w-44 type-control">{source.source_id}</p>
              </Table.Cell>
              <Table.Cell><p className="min-w-32 type-control">{source.binding_status}</p></Table.Cell>
              {slotOrder.map((slotName) => <Table.Cell key={slotName}>
                <p className="min-w-28 type-control">{source.slots.find((slot) => slot.slot === slotName)?.status || 'pending'}</p>
              </Table.Cell>)}
            </Table.Row>}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>}

    {!routeConfiguredForSources && embedded.length === 0 && <HeroNotice title="此步骤尚未解锁" status="warning">
      这里不是添加账号的入口。请先让至少两个不同发布者的 Actor 成功试跑并确认启用；之后在订阅页创建具体来源，系统会按当前实际运行槽位验证。
    </HeroNotice>}

    {(routeConfiguredForSources || embedded.length > 0) && <form className="flex min-w-0 flex-col gap-3 min-[640px]:flex-row min-[640px]:items-end" onSubmit={submitLookup}>
      <TextField fullWidth value={sourceInput} onChange={setSourceInput}>
        <Label>按来源 ID 查看当前主备验证</Label>
        <Input autoComplete="off" placeholder="仅提交 opaque source_id" />
        <Description>界面不会读取或显示真实目标、Actor input、Run ID 或 Dataset ID。</Description>
      </TextField>
      <Button type="submit" variant="secondary" isDisabled={!sourceInput.trim() || query.isFetching}>
        {query.isFetching ? '读取中…' : '读取验证状态'}
      </Button>
    </form>}

    {query.isError && <HeroNotice title="来源验证状态读取失败" status="warning">
      请确认来源 ID 有效且当前账户有管理权限。
    </HeroNotice>}
    {support && <div className="grid gap-3 rounded-control border border-separator p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="type-control">来源 {support.source_id}</p>
          <p className="type-meta mt-1 text-muted">绑定状态 {support.binding_status} · generation {support.generation}</p>
        </div>
        <StatusIndicator
          label={allSlotsPassed
            ? `${requiredSourceCanaries}/${requiredSourceCanaries} 已验证`
            : `尚未完成 ${requiredSourceCanaries}/${requiredSourceCanaries}`}
          tone={allSlotsPassed ? 'success' : 'warning'}
          icon={allSlotsPassed
            ? <Icons.CircleCheck size={13} aria-hidden="true" />
            : <Icons.TriangleAlert size={13} aria-hidden="true" />}
        />
      </div>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        <Metric
          label="来源验证预算"
          value={`${formatActorUsd(support.remaining_budget_usd, true)} 剩余`}
          detail={`实际已终结 ${formatActorUsd(support.spent_usd, true)} · 预留 ${formatActorUsd(support.reserved_usd, true)} / 总上限 ${formatActorUsd(support.budget_cap_usd, true)}`}
        />
        <TextField
          fullWidth
          value={sourceCanaryCapDraft}
          onChange={setSourceCanaryCapDraft}
          isInvalid={Boolean(sourceCanaryCapDraft) && !sourceCanaryCapValid}
        >
          <Label>来源 Canary 单次上限（USD）</Label>
          <Input type="number" min={0.000001} max={sourceCanaryMaximum} step={0.001} />
          <Description>独立于 Route 配置；不得超过本来源剩余验证预算或 Route 单次上限。</Description>
          {Boolean(sourceCanaryCapDraft) && !sourceCanaryCapValid && <FieldError>
            请输入大于 0 且不超过 {formatActorUsd(sourceCanaryMaximum, true)} 的上限。
          </FieldError>}
        </TextField>
      </div>
      <ol className="grid gap-2 min-[720px]:grid-cols-3" aria-label="来源当前主备 Canary 状态">
        {slotOrder.map((slotName) => {
          const slot = support.slots.find((item) => item.slot === slotName)
          const revision = slot?.revision_id
            ? revisionMap.get(slot.revision_id)
            : undefined
          return <li key={slotName} className="rounded-control bg-surface-secondary p-3">
            <p className="type-control">{slotLabels[slotName]}</p>
            <p className="type-meta mt-1 text-muted">{slot?.status || 'pending'}</p>
            <p className="type-meta mt-1 text-muted">{formatActorDateTime(slot?.last_canary_at ?? null)}</p>
            {slot && revision && slot.status !== 'passed' && slot.can_canary !== false && <Button
              size="sm"
              variant="secondary"
              className="mt-2"
              isDisabled={!sourceCanaryCapValid}
              onPress={() => onCanary({
                kind: 'source',
                sourceId: support.source_id,
                revision,
                expectedGeneration: support.generation,
                capUsd: sourceCanaryCapValue,
                routeKey: detail.route_key,
                routeLabel: routeIdentity(detail.platform, detail.target_type, detail.capability),
                routeMode: detail.mode,
                actorPricingLabel: actorPricingLabel(revision),
                buildLabel: revision.build_number || revision.build_id || '未固定',
              })}
            ><Icons.FlaskConical size={14} aria-hidden="true" />验证此槽</Button>}
          </li>
        })}
      </ol>
      {allSlotsPassed && !['ready_2of2', 'ready_3of3'].includes(support.binding_status) && <form
        className="grid gap-3 border-t border-separator pt-3 min-[720px]:grid-cols-[1fr_auto]"
        onSubmit={(event) => {
          event.preventDefault()
          if (activationConfirmation !== requiredConfirmation || activate.isPending) return
          activate.mutate({ support, confirmation: activationConfirmation })
        }}
      >
        <TextField
          fullWidth
          value={activationConfirmation}
          onChange={setActivationConfirmation}
          isDisabled={activate.isPending}
        >
          <Label>首次启用确认</Label>
          <Input placeholder={requiredConfirmation} autoComplete="off" />
          <Description>请输入“{requiredConfirmation}”。路由启用与每次付费 Canary 分开确认。</Description>
        </TextField>
        <Button
          type="submit"
          className="min-[720px]:self-end"
          isDisabled={activationConfirmation !== requiredConfirmation || activate.isPending}
        >{activate.isPending ? '启用中…' : '确认首次启用'}</Button>
      </form>}
    </div>}
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

function SupportCheckForm({
  catalogGeneration,
  supportProfiles,
  disabled,
  onCreated,
}: {
  catalogGeneration: number
  supportProfiles: ApifyActorSupportProfile[]
  disabled: boolean
  onCreated: (routeId: string | null, runId: string | null) => void
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [profileId, setProfileId] = useState('x/profile/items')
  const [forceDiscovery, setForceDiscovery] = useState(false)
  const selectedProfile = supportProfiles.find((profile) => profile.id === profileId) ?? supportProfiles[0]
  const mutation = useMutation({
    mutationFn: () => {
      if (!selectedProfile) throw new Error('没有可用的 Actor Route Profile')
      return api.requestApifyActorSupportCheck({
        platform: selectedProfile.platform,
        target_type: selectedProfile.target_type,
        capability: selectedProfile.capability,
        expected_generation: catalogGeneration,
        force_discovery: forceDiscovery,
      })
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sourceCapabilities(user.id),
      })
      onCreated(result.route_id ?? null, result.discovery_run_id ?? null)
      actionToast.success(result.discovery_run_id ? 'Actor 发现请求已创建' : '已找到可用 Route')
    },
    onError: (caught) => actionToast.danger('支持检查请求失败', {
      description: safeActorActionError(caught, '请求内容或 generation 已变化，请刷新后重试。'),
    }),
  })

  return <form
    className="grid gap-3 rounded-control border border-separator bg-surface-secondary p-3 min-[760px]:grid-cols-[minmax(0,1fr)_auto]"
    onSubmit={(event) => {
      event.preventDefault()
      if (!selectedProfile || mutation.isPending) return
      mutation.mutate()
    }}
  >
    <HeroSelect
      label="支持 Profile"
      value={selectedProfile?.id ?? ''}
      onChange={setProfileId}
      isDisabled={disabled || mutation.isPending}
      options={supportProfiles.map((profile) => ({
        id: profile.id,
        label: profile.label,
        description: `${profile.platform}/${profile.target_type}/${profile.capability} · ${profile.mode}`,
      }))}
    />
    {(user.role === 'owner' || user.role === 'admin') && <Switch
      className="min-[760px]:col-span-1"
      isSelected={forceDiscovery}
      isDisabled={disabled || mutation.isPending}
      onChange={setForceDiscovery}
    >
      <Switch.Content>
        <Switch.Control><Switch.Thumb /></Switch.Control>
        {forceDiscovery ? '强制重新发现已有 Route' : '仅检查现有支持'}
      </Switch.Content>
    </Switch>}
    <Button
      type="submit"
      className="self-end"
      isDisabled={disabled || mutation.isPending || !selectedProfile}
    >{mutation.isPending ? '检查中…' : '请求支持检查'}</Button>
  </form>
}

export function HeroActorOpsControlPlane({ queryEnabled = true }: { queryEnabled?: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [selectedRouteId, setSelectedRouteId] = useState('')
  const [routeCapDraft, setRouteCapDraft] = useState('')
  const [canaryTarget, setCanaryTarget] = useState<CanaryApprovalTarget | null>(null)
  const [canaryError, setCanaryError] = useState('')
  const [batchTarget, setBatchTarget] = useState<CanaryBatchApprovalTarget | null>(null)
  const [batchError, setBatchError] = useState('')
  const [activeBatchId, setActiveBatchId] = useState('')
  const [activationOpen, setActivationOpen] = useState(false)
  const [rollbackRevision, setRollbackRevision] = useState<ApifyActorRevisionSummary | null>(null)
  const [rollbackSlot, setRollbackSlot] = useState<ApifyActorSlotName>('primary')
  const routesQuery = useQuery({
    queryKey: queryKeys.apifyActorRoutes(user.id),
    queryFn: ({ signal }) => api.apifyActorRoutes(signal),
    enabled: queryEnabled,
    retry: false,
    refetchInterval: queryEnabled ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })
  const detailQuery = useQuery({
    queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId),
    queryFn: ({ signal }) => api.apifyActorRoute(selectedRouteId, signal),
    enabled: queryEnabled && Boolean(selectedRouteId),
    retry: false,
    refetchInterval: queryEnabled && selectedRouteId ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })
  const batchQuery = useQuery({
    queryKey: queryKeys.apifyActorCanaryBatch(user.id, activeBatchId),
    queryFn: ({ signal }) => api.apifyActorCanaryBatch(activeBatchId, signal),
    enabled: queryEnabled && Boolean(activeBatchId),
    retry: false,
    refetchInterval: (current) => {
      const status = current.state.data?.status
      return status && ['queued', 'preflighting', 'running'].includes(status)
        ? 3_000
        : false
    },
  })
  const capabilityFingerprint = (routesQuery.data?.routes ?? [])
    .map((route) => [
      route.route_id,
      route.generation,
      route.support_status,
      route.runnable_slots,
    ].join(':'))
    .join('|')
  const hasRouteCatalog = routesQuery.data !== undefined

  useEffect(() => {
    if (!hasRouteCatalog) return
    void queryClient.invalidateQueries({
      queryKey: queryKeys.sourceCapabilities(user.id),
    })
  }, [capabilityFingerprint, hasRouteCatalog, queryClient, user.id])

  useEffect(() => {
    const routes = routesQuery.data?.routes ?? []
    if (routes.length === 0) {
      // Server route removal invalidates the selected opaque id.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedRouteId('')
      return
    }
    if (!selectedRouteId || !routes.some((route) => route.route_id === selectedRouteId)) {
      // Server route creation supplies the first valid selection.
      setSelectedRouteId(routes[0].route_id)
    }
  }, [routesQuery.data, selectedRouteId])

  useEffect(() => {
    const detail = detailQuery.data
    if (!detail) return
    // Route generation is the reset boundary for the CAS-controlled cap draft.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRouteCapDraft(String(detail.per_run_cap_usd))
  }, [detailQuery.data])

  const updatePool = useMutation({
    mutationFn: ({ detail, draft, rollbackRevisionId, perRunCapUsd }: {
      detail: ApifyActorRouteDetail
      draft: PoolDraft
      rollbackRevisionId?: string
      perRunCapUsd?: number
    }) => (
      api.updateApifyActorRouteActivePool(detail.route_id, {
        expected_generation: detail.generation,
        ...(rollbackRevisionId
          ? { rollback_revision_id: rollbackRevisionId }
          : {}),
        ...(perRunCapUsd !== undefined
          ? { per_run_cap_usd: perRunCapUsd }
          : {}),
        slots: slotOrder.map((slot) => ({ slot, revision_id: draft[slot] })),
      })
    ),
    onSuccess: (detail) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, detail.route_id), detail)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCapabilities(user.id) })
      setRollbackRevision(null)
      actionToast.success('三槽 Actor Pool 已更新')
    },
    onError: (caught, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, variables.detail.route_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCapabilities(user.id) })
      actionToast.danger('Actor Pool 更新失败', {
        description: safeActorActionError(caught, 'Route generation 已变化或三槽规则未通过，请刷新后重试。'),
      })
    },
  })

  const activatePool = useMutation({
    mutationFn: (detail: ApifyActorRouteDetail) => (
      api.activateApifyActorRouteRecommendedPool(detail.route_id, {
        expected_generation: detail.generation,
        confirmation: '确认启用 Actor 主备',
      })
    ),
    onSuccess: (detail) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, detail.route_id), detail)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCapabilities(user.id) })
      setActivationOpen(false)
      actionToast.success('Actor 主备已启用')
    },
    onError: (caught, detail) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, detail.route_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCapabilities(user.id) })
      actionToast.danger('Actor 主备未能启用', {
        description: safeActorActionError(caught, '候选认证或 Route generation 已变化，请刷新后重试。'),
      })
    },
  })

  const canaryBatch = useMutation({
    mutationFn: (target: CanaryBatchApprovalTarget) => (
      api.createApifyActorCanaryBatch(target.plan.run_id, {
        expected_generation: target.plan.generation,
        expected_plan_hash: target.plan.plan_hash,
        approval_id: target.approvalId,
        confirmation: '确认付费验证主备',
        max_candidates: target.plan.max_candidates,
        max_total_charge_usd: target.plan.max_total_charge_usd,
      })
    ),
    onSuccess: (response) => {
      setActiveBatchId(response.batch.batch_id)
      setBatchTarget(null)
      setBatchError('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.apifyActorDiscoveryRun(user.id, response.batch.discovery_run_id),
      })
      actionToast.success('两路主备验证已提交，将严格串行执行')
    },
    onError: (caught) => {
      setBatchError(safeActorActionError(
        caught,
        '验证计划已变化或已有批次运行；页面会刷新最新状态，不会重复付费。',
      ))
    },
  })

  const canary = useMutation({
    mutationFn: async (target: CanaryApprovalTarget) => {
      const payload: ApifyActorPaidCanaryRequest = {
        expected_generation: target.expectedGeneration,
        approval_id: target.approvalId,
        confirmation: '确认付费试跑',
        max_total_charge_usd: target.capUsd,
      }
      if (target.kind === 'discovery') {
        return {
          kind: target.kind,
          result: await api.canaryApifyActorDiscoveryCandidate(
            target.runId,
            target.candidate.revision.revision_id,
            payload,
          ),
          target,
        } as const
      }
      return {
        kind: target.kind,
        result: await api.canaryApifyActorSourceRevision(
          target.sourceId,
          target.revision.revision_id,
          payload,
        ),
        target,
      } as const
    },
    onSuccess: (response) => {
      if (response.kind === 'discovery') {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.apifyActorDiscoveryRun(
            user.id,
            response.target.runId,
          ),
        })
      } else {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.apifyActorSourceSupport(
            user.id,
            response.target.sourceId,
          ),
        })
      }
      setCanaryTarget(null)
      setCanaryError('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCapabilities(user.id) })
      if (selectedRouteId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId) })
      }
      actionToast.success('付费 Canary 已提交')
    },
    onError: (caught) => {
      setCanaryError(safeActorActionError(caught, '付费 Canary 未能提交；请先刷新状态，避免重复付费。'))
    },
  })

  const routes = routesQuery.data?.routes ?? []
  const detail = detailQuery.data
  const selectedSummary = routes.find((route) => route.route_id === selectedRouteId)
  const actionPending = updatePool.isPending || activatePool.isPending || canary.isPending || canaryBatch.isPending
  const routeCapValue = Number(routeCapDraft)
  const routeCapValid = Number.isFinite(routeCapValue) && routeCapValue > 0 && routeCapValue <= 100
  const routeCapChanged = detail !== undefined && routeCapValid
    && Math.abs(routeCapValue - detail.per_run_cap_usd) > 1e-9
  const rollbackSlots = detail?.slots ?? []
  const activePoolDraft = useMemo(() => {
    if (!detail) return null
    const slots = Object.fromEntries(
      detail.slots.map((slot) => [slot.slot, slot.revision_id]),
    ) as PoolDraft
    return slotOrder.filter((slot) => slots[slot]).length >= detail.min_runtime_healthy
      ? slots
      : null
  }, [detail])

  const rollbackDraft = useMemo(() => {
    if (!detail || !rollbackRevision) return null
    const current = Object.fromEntries(
      detail.slots.map((slot) => [slot.slot, slot.revision_id]),
    ) as PoolDraft
    const next: PoolDraft = {
      ...current,
      [rollbackSlot]: rollbackRevision.revision_id,
    }
    return next
  }, [detail, rollbackRevision, rollbackSlot])

  return <>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <Card.Title>ActorOps 路由控制面</Card.Title>
        <Card.Description className="mt-1">
          每条 Route 只需确认一次主备验证；系统串行试跑并在两路成功后停止，随后再确认启用。
        </Card.Description>
      </div>
      {selectedSummary && <div className="flex flex-wrap gap-2">
        <StatusIndicator
          label={supportPresentation[selectedSummary.support_status].label}
          tone={supportPresentation[selectedSummary.support_status].tone}
          icon={routeStatusIcon(supportPresentation[selectedSummary.support_status].tone)}
        />
        <StatusIndicator
          label={runtimePresentation[selectedSummary.runtime_status].label}
          tone={runtimePresentation[selectedSummary.runtime_status].tone}
          icon={routeStatusIcon(runtimePresentation[selectedSummary.runtime_status].tone)}
        />
      </div>}
    </div>

    {routesQuery.isPending && <div className="mt-4"><LoadingState label="正在读取 ActorOps Route" rows={3} /></div>}
    {routesQuery.isError && <div className="mt-4"><HeroNotice title="ActorOps Route 读取失败" status="warning">
      <Button size="sm" variant="ghost" onPress={() => void routesQuery.refetch()}>重试此区域</Button>
    </HeroNotice></div>}

    {routesQuery.data && <div className="mt-4 grid gap-4">
      <SupportCheckForm
        catalogGeneration={routesQuery.data.generation}
        supportProfiles={routesQuery.data.support_profiles ?? []}
        disabled={routesQuery.isFetching}
        onCreated={(routeId) => {
          void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
          if (routeId) setSelectedRouteId(routeId)
        }}
      />
      <RouteList selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} routes={routes} />
    </div>}

    {selectedRouteId && detailQuery.isPending && <div className="mt-4"><LoadingState label="正在读取 Route 三槽详情" rows={3} /></div>}
    {detailQuery.isError && <div className="mt-4"><HeroNotice title="Route 详情读取失败" status="warning">
      <Button size="sm" variant="ghost" onPress={() => void detailQuery.refetch()}>重试此 Route</Button>
    </HeroNotice></div>}

    {detail && <div className="mt-5 grid gap-6">
      <section aria-labelledby="actor-ops-active-pool-heading">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 id="actor-ops-active-pool-heading" className="type-page-title">Actor 主备方案</h3>
            <p className="type-meta mt-1 text-muted">
              {routeIdentity(detail.platform, detail.target_type, detail.capability)}
              {' · '}generation {detail.generation}
            </p>
          </div>
          <p className="type-control tabular-nums">
            {detail.runnable_slots}/3 可用 · {detail.publisher_count} 个发布者 · {formatActorUsd(detail.per_run_cap_usd)}/Run
          </p>
        </div>
        {detail.runnable_slots < detail.min_runtime_healthy && <div className="mt-3">
          <HeroNotice title="少于两个 Actor 可用，自动付费抓取已阻断" status="danger">
            {detail.blocked_reason || '请先完成补位、Canary 与管理员激活。'}
          </HeroNotice>
        </div>}
        <div className="mt-3">
          <ActorPoolPlan
            detail={detail}
            actionPending={actionPending}
            onConfirm={() => setActivationOpen(true)}
          />
          {detail.activation_recommendation?.already_active && activePoolDraft && <details className="mt-3 rounded-control border border-separator bg-surface-secondary p-3">
            <summary className="type-meta cursor-pointer text-muted">调整 Route 单次费用上限</summary>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div className="max-w-sm flex-1">
                <TextField
                  fullWidth
                  value={routeCapDraft}
                  onChange={setRouteCapDraft}
                  isDisabled={actionPending}
                  isInvalid={Boolean(routeCapDraft) && !routeCapValid}
                >
                  <Label>Route 单次费用上限（USD）</Label>
                  <Input type="number" min={0.000001} max={100} step={0.001} />
                  <Description>管理员明确调整后按 generation 热加载；商城价格不会自动放宽此上限。</Description>
                  {Boolean(routeCapDraft) && !routeCapValid && <FieldError>请输入大于 0 且不超过 100 的 USD 上限。</FieldError>}
                </TextField>
              </div>
              <Button
                size="sm"
                isDisabled={!routeCapValid || !routeCapChanged || actionPending}
                onPress={() => updatePool.mutate({
                  detail,
                  draft: activePoolDraft,
                  perRunCapUsd: routeCapValue,
                })}
              >{updatePool.isPending ? '保存中…' : '保存费用上限'}</Button>
            </div>
          </details>}
        </div>
      </section>

      <section className="border-t border-separator pt-5" aria-labelledby="actor-ops-discovery-heading">
        <h3 id="actor-ops-discovery-heading" className="type-page-title">AI 发现与候选审批</h3>
        <p className="type-meta mt-1 text-muted">展示进度与淘汰原因；候选由后端选择，不再要求你手工逐个审批 Revision。</p>
        <div className="mt-3"><DiscoveryPanel
          detail={detail}
          queryEnabled={queryEnabled}
          activeBatch={batchQuery.data ?? null}
          onBatchCanary={(plan) => setBatchTarget({
            plan,
            approvalId: crypto.randomUUID(),
          })}
        /></div>
      </section>

      <section className="border-t border-separator pt-5" aria-labelledby="actor-ops-source-validation-heading">
        <h3 id="actor-ops-source-validation-heading" className="type-page-title">来源级 Actor 验证</h3>
        <p className="type-meta mt-1 text-muted">新来源串行验证当前实际运行的 2 或 3 个 Actor；后续补位只复验变化槽位。</p>
        <div className="mt-3"><SourceSupportPanel
          detail={detail}
          queryEnabled={queryEnabled}
          onCanary={(target) => setCanaryTarget({
            ...target,
            approvalId: crypto.randomUUID(),
          })}
        /></div>
      </section>

      <section className="border-t border-separator pt-5" aria-labelledby="actor-ops-revision-heading">
        <h3 id="actor-ops-revision-heading" className="type-page-title">Revision 差异与回滚</h3>
        <p className="type-meta mt-1 text-muted">旧 Build 和 Manifest 保留为不可变 Revision；回滚也使用当前 generation。</p>
        <div className="mt-3">
          <RevisionHistory detail={detail} onRollback={(revision) => {
            const matching = detail.slots.find((slot) => slot.revision?.actor_id === revision.actor_id)
            setRollbackSlot(matching?.slot ?? 'primary')
            setRollbackRevision(revision)
          }} actionPending={actionPending} />
        </div>
      </section>

      <section className="border-t border-separator pt-5" aria-labelledby="actor-ops-ai-settings-heading">
        <h3 id="actor-ops-ai-settings-heading" className="type-page-title">Actor Discovery AI 设置</h3>
        <div className="mt-3"><DiscoverySettingsPanel queryEnabled={queryEnabled} /></div>
      </section>
    </div>}

    <Modal isOpen={activationOpen} onOpenChange={(open) => {
      if (!open && !activatePool.isPending) setActivationOpen(false)
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开 Actor 主备启用确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!activatePool.isPending} isKeyboardDismissDisabled={activatePool.isPending}>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>确认启用 Actor 主备</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-3" aria-busy={activatePool.isPending}>
                <HeroNotice title="系统将在提交时重新校验候选" status="warning" role="status">
                  不接受浏览器指定的 Revision。后端优先选择完整 2+1；暂时不足时允许两个已成功试跑、Actor 与发布者均不同的固定 Build 先以降级模式上线。
                </HeroNotice>
                {detail && <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                  <div><dt className="text-muted">Route / 来源类型</dt><dd className="type-control mt-1 break-words">{routeIdentity(detail.platform, detail.target_type, detail.capability)} · {detail.mode === 'fallback' ? '原生优先，Actor 回退' : 'Actor 主链路'}</dd></div>
                  <div><dt className="text-muted">生效范围</dt><dd className="type-control mt-1">下一次任务开始读取新 generation；运行中的旧任务仍使用冻结配置。</dd></div>
                  <div><dt className="text-muted">单次 Actor 费用上限</dt><dd className="type-control mt-1 tabular-nums">{formatActorUsd(detail.per_run_cap_usd)}</dd></div>
                </dl>}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={activatePool.isPending} onPress={() => setActivationOpen(false)}>取消</Button>
              <Button
                type="button"
                isDisabled={!detail?.activation_recommendation?.ready || detail.activation_recommendation.already_active || activatePool.isPending}
                onPress={() => detail && activatePool.mutate(detail)}
              >{activatePool.isPending
                ? '启用中…'
                : detail?.activation_recommendation?.activation_mode === 'expedited_2of3'
                  ? '确认先启用两路主备'
                  : '确认启用 Actor 主备'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>

    <Modal isOpen={Boolean(batchTarget)} onOpenChange={(open) => {
      if (!open && !canaryBatch.isPending) {
        setBatchTarget(null)
        setBatchError('')
      }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开两路主备付费验证确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!canaryBatch.isPending} isKeyboardDismissDisabled={canaryBatch.isPending}>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>确认付费验证两路主备</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-3" aria-busy={canaryBatch.isPending}>
                <HeroNotice title="一次确认，最多串行验证三个候选" status="warning" role="status">
                  每次启动前先免费检查 Actor 与精确 Build；两位不同发布者成功后立即停止。未启动、Build 已失效或不再需要的候选费用为 $0，不计入失败次数。
                </HeroNotice>
                {batchTarget && <>
                  <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                    <div><dt className="text-muted">所属 Route / 来源类型</dt><dd className="type-control mt-1 break-words">{routeIdentity(batchTarget.plan.platform, batchTarget.plan.target_type, batchTarget.plan.capability)} · <code>{batchTarget.plan.route_key}</code> · {batchTarget.plan.mode === 'fallback' ? '原生优先，Actor 回退' : 'Actor 主链路'}</dd></div>
                    <div><dt className="text-muted">本批总费用上限</dt><dd className="type-control mt-1 tabular-nums">{formatActorUsd(batchTarget.plan.max_total_charge_usd, true)}</dd></div>
                    <div><dt className="text-muted">本轮剩余额度</dt><dd className="type-control mt-1 tabular-nums">还可计入 {batchTarget.plan.attempts_remaining} 次真实启动 · 费用余额 {formatActorUsd(batchTarget.plan.budget_remaining_usd, true)}</dd></div>
                    <div><dt className="text-muted">停止条件</dt><dd className="type-control mt-1">两个不同 Actor、来自两个不同发布者且均通过内容合同。</dd></div>
                  </dl>
                  <ol className="grid gap-2" aria-label="本批 Actor 验证计划">
                    {batchTarget.plan.items.map((item) => <li key={item.revision_id} className="rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                      <p className="type-control break-words">#{item.ordinal} · {item.publisher} · {item.actor_id}</p>
                      <p className="mt-1 break-words text-muted">Build {item.build_number} · 单次封顶 {formatActorUsd(item.authorized_cap_usd, true)}</p>
                      <p className="mt-1 break-words text-muted">商城定价：{item.pricing?.billing_unit === 'free'
                        ? '免费 Actor'
                        : item.pricing?.unit_price_min_usd !== null && item.pricing?.unit_price_min_usd !== undefined
                          ? `${formatActorUsd(item.pricing.unit_price_min_usd, true)} 起 / ${item.pricing.billing_unit === 'dataset_item' ? 'Dataset 行' : '计费事件'}`
                          : '定价快照未提供；仍受单次封顶保护'}</p>
                    </li>)}
                  </ol>
                </>}
                {batchError && <HeroNotice title={batchError} status="danger" />}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={canaryBatch.isPending} onPress={() => {
                setBatchTarget(null)
                setBatchError('')
              }}>取消</Button>
              <Button
                type="button"
                isDisabled={!batchTarget?.plan.ready || canaryBatch.isPending}
                onPress={() => batchTarget && canaryBatch.mutate(batchTarget)}
              >{canaryBatch.isPending ? '提交中…' : '确认付费验证主备'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>

    <Modal isOpen={Boolean(canaryTarget)} onOpenChange={(open) => {
      if (!open && !canary.isPending) {
        setCanaryTarget(null)
        setCanaryError('')
      }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开付费 Canary 确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!canary.isPending} isKeyboardDismissDisabled={canary.isPending}>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>确认付费 Canary</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-3" aria-busy={canary.isPending}>
                <HeroNotice title="此操作会产生一次 Apify 调用" status="warning" role="status">
                  指定精确 Build，串行执行一次；本次最高费用 {formatActorUsd(canaryTarget?.capUsd ?? null)}。
                  提交后不会自动重试或并发竞速。
                </HeroNotice>
                {canaryTarget && <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                  <div><dt className="text-muted">所属 Route / 源类型</dt><dd className="type-control mt-1 break-words">{canaryTarget.routeLabel} · <code>{canaryTarget.routeKey}</code> · {canaryTarget.routeMode === 'fallback' ? '原生失败时 Actor 回退' : 'Actor 主链路'}</dd></div>
                  <div><dt className="text-muted">本次验证来源</dt><dd className="type-control mt-1 break-words">{canaryTarget.kind === 'discovery'
                    ? 'Route 认证公开参考来源（真实目标已脱敏）'
                    : `具体来源 ${canaryTarget.sourceId}（真实目标不回显）`}</dd></div>
                  <div><dt className="text-muted">Actor / Build</dt><dd className="type-control mt-1 break-words">{canaryTarget.kind === 'discovery'
                    ? canaryTarget.candidate.revision.actor_public_name || canaryTarget.candidate.revision.actor_id
                    : canaryTarget.revision.actor_public_name || canaryTarget.revision.actor_id} · Build {canaryTarget.buildLabel}</dd></div>
                  <div><dt className="text-muted">Actor 商城定价</dt><dd className="type-control mt-1 break-words">{canaryTarget.actorPricingLabel}</dd></div>
                  <div><dt className="text-muted">本次付费封顶</dt><dd className="type-control mt-1 tabular-nums">{formatActorUsd(canaryTarget.capUsd, true)}</dd></div>
                  {canaryTarget.kind === 'discovery' && <div><dt className="text-muted">Route 认证预算</dt><dd className="type-control mt-1 tabular-nums">已审批/记录 {formatActorUsd(canaryTarget.routeSpentUsd, true)} / 总上限 {formatActorUsd(canaryTarget.routeBudgetUsd, true)}</dd></div>}
                </dl>}
                {canaryError && <HeroNotice title={canaryError} />}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button
                type="button"
                variant="ghost"
                isDisabled={canary.isPending}
                onPress={() => {
                  setCanaryTarget(null)
                  setCanaryError('')
                }}
              >取消</Button>
              <Button
                type="button"
                isDisabled={!canaryTarget || canary.isPending || (canaryTarget?.capUsd ?? 0) <= 0}
                onPress={() => canaryTarget && canary.mutate(canaryTarget)}
              >{canary.isPending ? '提交中…' : '确认付费试跑'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>

    <Modal isOpen={Boolean(rollbackRevision)} onOpenChange={(open) => {
      if (!open && !updatePool.isPending) setRollbackRevision(null)
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开 Revision 回滚确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!updatePool.isPending} isKeyboardDismissDisabled={updatePool.isPending}>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>回滚不可变 Revision</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-4">
                <HeroNotice title="回滚会创建新的 Route generation" status="warning" role="status">
                  运行中的旧 generation 可结束，但过期结果不能写入新缓存或 Feed。
                </HeroNotice>
                <p className="type-control break-all">{rollbackRevision?.revision_id}</p>
                <HeroSelect
                  label="回滚到槽位"
                  value={rollbackSlot}
                  onChange={(value) => setRollbackSlot(value as ApifyActorSlotName)}
                  isDisabled={updatePool.isPending}
                  options={slotOrder.map((slot) => ({
                    id: slot,
                    label: slotLabels[slot],
                    description: rollbackSlots.find((item: ApifyActorRouteActiveSlot) => item.slot === slot)?.revision?.actor_public_name || '未绑定',
                  }))}
                />
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={updatePool.isPending} onPress={() => setRollbackRevision(null)}>取消</Button>
              <Button
                type="button"
                isDisabled={!detail || !rollbackDraft || updatePool.isPending}
                onPress={() => detail && rollbackDraft && rollbackRevision && updatePool.mutate({
                  detail,
                  draft: rollbackDraft,
                  rollbackRevisionId: rollbackRevision.revision_id,
                })}
              >{updatePool.isPending ? '回滚中…' : '确认回滚'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </>
}
