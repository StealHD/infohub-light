import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type {
  ApifyActorDiscoveryCandidate,
  ApifyActorCanaryBatch,
  ApifyActorCanaryPlan,
  ApifyActorDiscoverySettingsPatch,
  ApifyActorPaidCanaryRequest,
  ApifyActorPoolCandidate,
  ApifyActorPoolGoal,
  ApifyActorRevisionSummary,
  ApifyActorRouteActiveSlot,
  ApifyActorRouteDetail,
  ApifyActorRouteRuntimeStatus,
  ApifyActorRouteSummary,
  ApifyActorRouteSupportStatus,
  ApifyActorSlotName,
  ApifyActorSourceSupport,
  ApifyActorSupportProfile,
  ApifyActorValidationProfileRequest,
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
  Table,
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
import { humanActorError, type HumanActorError } from './actorOpsPresentation'

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
  proposed: '检查中',
  static_valid: '基础检查通过 · 待实际验证',
  probationary: '观察中 · 可运行',
  certified: '已正式认证',
  legacy_builtin: '兼容模式 · 待升级',
  quarantined: '已隔离',
  superseded: '历史版本',
  rejected: '不可使用',
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

type CandidateProfileDraft = {
  timeoutSeconds: string
  sampleItems: string
  maxChargeUsd: string
}

function HumanActorErrorNotice({ error }: { error: HumanActorError }) {
  return <HeroNotice title={error.reason} status="danger" role="alert">
    <p><strong>影响：</strong>{error.impact}</p>
    <p className="mt-1"><strong>下一步：</strong>{error.next}</p>
    {error.diagnostic && <SettingsDisclosure title="诊断信息" description="仅包含可安全复制的错误代码。"><code className="break-all type-meta">{error.diagnostic}</code></SettingsDisclosure>}
  </HeroNotice>
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

function poolCandidatePricingLabel(candidate: ApifyActorPoolCandidate): string {
  const pricing = candidate.pricing
  if (!pricing || pricing.billing_unit === 'unknown') return '计费方式待验证计划确认'
  if (pricing.billing_unit === 'free') return 'Actor 标价免费'
  if (pricing.billing_unit === 'dataset_item') return '按结果条目计费'
  return '按 Actor 计费事件计费'
}

function poolCandidateUnavailableLabel(reason: string | null | undefined): string {
  if (reason === 'actor_already_active') return '已经在当前主备中'
  if (reason === 'candidate_validation_in_progress') return '另一次验证正在进行'
  if (reason === 'candidate_exact_build_missing') return '尚未固定可验证版本'
  if (reason === 'candidate_not_validated') return '基础检查尚未通过'
  if (reason === 'actor_upgrade_inspection_running') return '正在为这个当前 Actor 生成安全新版'
  if (reason === 'actor_upgrade_revision_unavailable') return '尚未通过安全升级检查；当前兼容版本继续运行'
  if (reason === 'actor_validation_sample_limit_reached') return '3 条样本仍未通过，升级已停止'
  if (reason === 'actor_validation_retry_not_permitted') return '上次失败不允许通过提价、换 Actor 或重复付费绕过'
  return '当前不满足安全条件'
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
  return <>
    <div className="hidden min-[768px]:block">
      <Table variant="secondary" className="max-w-full">
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
    </div>
    <div className="min-[768px]:hidden">
      {routes.length === 0
        ? <SettingsGroup ariaLabel="ActorOps 路由列表（移动端）"><SettingsItem label="尚未建立 Actor Route" description="支持检查完成后会在这里显示可管理的 Route。" density="compact" /></SettingsGroup>
        : <SettingsGroup ariaLabel="ActorOps 路由列表（移动端）">{routes.map((route) => {
          const support = supportPresentation[route.support_status]
          const runtime = runtimePresentation[route.runtime_status]
          const selected = selectedRouteId === route.route_id
          return <SettingsItem
            key={route.route_id}
            label={routeIdentity(route.platform, route.target_type, route.capability)}
            description={route.route_key}
            density="compact"
            className={selected ? 'bg-default' : ''}
            trailing={<Button size="sm" variant={selected ? 'secondary' : 'ghost'} aria-current={selected ? 'true' : undefined} onPress={() => onSelect(route.route_id)}>{selected ? '正在查看' : '查看详情'}</Button>}
          >
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={runtime.tone} icon={routeStatusIcon(runtime.tone)}>{runtime.label}</StatusBadge>
              <StatusBadge tone={support.tone} icon={routeStatusIcon(support.tone)}>{support.label}</StatusBadge>
              <span className="type-meta text-muted">{route.runnable_slots}/3 可用 · {route.publisher_count} 个发布者</span>
              <span className="type-meta text-muted">{formatActorUsd(route.per_run_cap_usd)} / Run</span>
            </span>
          </SettingsItem>
        })}</SettingsGroup>}
    </div>
  </>
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
    {showApprovalAction && !detail.activation_recommendation?.ready && !paidBatchRunning && planQuery.data?.ready && <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-separator bg-surface-secondary p-3">
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

type ActorOpsTaskTab = 'pool' | 'sources' | 'operations'

type GuidedNextAction =
  | 'start_discovery'
  | 'select_candidates'
  | 'approve_canary'
  | 'approve_activation'
  | 'open_sources'
  | 'open_operations'
  | 'refresh'
  | 'none'

const taskTabs = new Set<ActorOpsTaskTab>(['pool', 'sources', 'operations'])
const routeProfileOrder = ['x/profile/items', 'instagram/profile/items', 'youtube/channel/items'] as const

const routeProductNames: Record<string, { label: string; description: string }> = {
  'x/profile/items': { label: 'X 用户动态', description: 'Actor 主抓取' },
  'instagram/profile/items': { label: 'Instagram 主页内容', description: 'Actor 主抓取' },
  'youtube/channel/items': { label: 'YouTube 频道视频', description: '原生优先 · Actor 故障回退' },
}

const workflowPresentation: Record<string, {
  title: string
  description: string
  status: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
  action: GuidedNextAction
  cta?: string
}> = {
  setup_discovery_required: {
    title: '尚未建立 Actor 主备',
    description: '系统会先免费搜索并检查候选，不会启动 Actor 或产生费用。',
    status: '未建立', tone: 'neutral', action: 'start_discovery', cta: '开始建立主备',
  },
  setup_discovery_running: {
    title: '正在搜索可用 Actor',
    description: '系统正在检查商城候选、固定 Build 和输出结构；无需停留本页。',
    status: '建立中', tone: 'warning', action: 'none',
  },
  setup_candidate_selection_required: {
    title: '选择 3 个 Actor 建立完整主备',
    description: '候选已经完成免费检查。选择 3 个不同 Actor；服务端会固定安全版本和槽位顺序。',
    status: '待选择', tone: 'warning', action: 'select_candidates', cta: '选择 Actor',
  },
  setup_canary_approval_required: {
    title: '候选已选择，下一步验证完整主备',
    description: '系统会严格按你的选择串行验证 3 个 Actor；验证期间不会提前启用。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认付费验证',
  },
  setup_canary_running: {
    title: '正在验证完整主备',
    description: '系统正在按计划串行执行；没有成功确认前不会切换线路。',
    status: '待付费验证', tone: 'warning', action: 'none',
  },
  setup_activation_approval_required: {
    title: '完整主备验证通过',
    description: '确认后以完整 3/3 主备开始运行；验证完成前没有自动启用。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认启用',
  },
  backup_2_discovery_required: {
    title: '补齐第三路备用',
    description: '当前两路已可自动切换。系统会免费搜索第三个不同发布者的 Actor；无需填写 Actor ID。',
    status: '两路可用', tone: 'warning', action: 'start_discovery', cta: '开始补齐备用 2',
  },
  backup_2_discovery_running: {
    title: '正在寻找第三路备用',
    description: '现有两路继续运行，不受补位影响。',
    status: '补位中', tone: 'warning', action: 'none',
  },
  backup_2_candidate_selection_required: {
    title: '选择第三个备用 Actor',
    description: '选择 1 个不与现有主备重复的候选。确认生效前，现有两路始终继续运行。',
    status: '两路可用', tone: 'warning', action: 'select_candidates', cta: '补充备用 Actor',
  },
  backup_2_canary_approval_required: {
    title: '第三路候选已就绪',
    description: '第一步：确认一次限额付费验证；现有两路继续运行。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认第三路验证',
  },
  backup_2_canary_running: {
    title: '正在验证第三路备用',
    description: 'Route 和已批准来源正在串行预验证；现有两路继续服务。',
    status: '补位中', tone: 'warning', action: 'none',
  },
  backup_2_activation_approval_required: {
    title: '第三路验证通过',
    description: '第二步：确认加入备用 2；下一任务热加载，现有两路不变。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认补位生效',
  },
  legacy_discovery_required: {
    title: '升级当前 3 个 Actor',
    description: '只检查上面正在使用的 3 个 Actor，为它们固定新版 Build 并旁路验证。任一 Actor 无法安全升级就停止，不选择替补。',
    status: '兼容模式', tone: 'warning', action: 'start_discovery', cta: '开始升级当前 3 个 Actor',
  },
  legacy_discovery_running: {
    title: '正在升级当前 3 个 Actor',
    description: '系统正在为上面的 Actor 生成固定 Build；当前兼容线路继续运行，不会重复创建搜索任务。',
    status: '兼容模式', tone: 'warning', action: 'none',
  },
  legacy_candidate_selection_required: {
    title: '确认当前 Actor 升级',
    description: '只允许上面的 3 个当前 Actor 进入新版方案；三者必须全部通过，并覆盖至少两个发布者。',
    status: '兼容模式', tone: 'warning', action: 'select_candidates', cta: '继续升级当前 Actor',
  },
  legacy_canary_approval_required: {
    title: '新版主备候选已就绪',
    description: '第一步：确认新版方案和现有来源的串行付费验证；兼容线路继续运行。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认新版验证',
  },
  legacy_canary_running: {
    title: '正在验证新版主备',
    description: '旁路方案正在完成 Route 与来源预验证；当前兼容池始终可见。',
    status: '兼容模式', tone: 'warning', action: 'none',
  },
  legacy_activation_approval_required: {
    title: '新版主备验证通过',
    description: '第二步：确认后原子切换到固定 Build；运行中的任务仍使用旧 generation。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认切换',
  },
  probation_observing: {
    title: '主备配置完成',
    description: '所选 Actor 已验证并可运行；稳定性认证会在后台继续，不会阻塞配置，也无需手动转正。',
    status: '配置完成', tone: 'success', action: 'none',
  },
  source_validation_required: {
    title: '有来源等待启用',
    description: '主备已可运行，下一步只需验证具体来源。',
    status: '配置完成', tone: 'success', action: 'open_sources', cta: '前往来源启用',
  },
  runtime_degraded_monitoring: {
    title: '正在使用备用线路',
    description: '系统已自动切换并持续观察恢复；无需手动换路。',
    status: '已切换备用', tone: 'warning', action: 'none',
  },
  blocked_unknown_start: {
    title: '需要先核对 Apify 运行',
    description: '启动结果不确定，系统已阻止继续付费。请先核对状态；不要重复提交。',
    status: '需要核对', tone: 'danger', action: 'refresh', cta: '刷新核对结果',
  },
  budget_blocked: {
    title: '费用保护已暂停',
    description: '系统已停止新的付费启动；可在运行与告警中查看当前状态。',
    status: '费用已暂停', tone: 'danger', action: 'open_operations', cta: '查看运行与费用',
  },
  complete: {
    title: '主备配置完成',
    description: '三路可用，故障时系统自动串行切换。',
    status: '配置完成', tone: 'success', action: 'none',
  },
}

const unknownWorkflowPresentation = {
  title: '状态需要刷新',
  description: '当前没有可安全执行的操作。刷新后仍会以服务端状态为准。',
  status: '需要核对',
  tone: 'warning' as const,
  action: 'refresh' as const,
  cta: '刷新状态',
}

function routeProfileId(route: Pick<ApifyActorRouteSummary, 'platform' | 'target_type' | 'capability'>): string {
  return `${route.platform}/${route.target_type}/${route.capability}`
}

function sourceStatusPresentation(status: string): { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } {
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

function guidedSlotStatus(
  slot: ApifyActorSlotName,
  revision: ApifyActorRevisionSummary | null | undefined,
): { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger'; note: string } {
  if (!revision) return { label: '空缺', tone: 'neutral', note: '当前不参与运行，也不产生费用' }
  if (revision.lifecycle === 'legacy_builtin') return { label: '兼容版本', tone: 'warning', note: '当前仍可运行；可在旁路完成升级' }
  if (['quarantined', 'rejected'].includes(revision.lifecycle)) return { label: '需要处理', tone: 'danger', note: '当前不会参与新的运行' }
  if (revision.lifecycle === 'probationary') {
    return {
      label: slot === 'primary' ? '运行中' : '备用可用',
      tone: 'success',
      note: '已验证，可运行；系统会继续观察稳定性，无需手动转正',
    }
  }
  if (revision.lifecycle === 'certified') return {
    label: slot === 'primary' ? '运行中' : '备用可用',
    tone: 'success',
    note: slot === 'primary' ? '当前主用 Actor' : '故障时自动切换',
  }
  return { label: '需要处理', tone: 'warning', note: '尚未完成实际验证' }
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
  const [routeCapDraftState, setRouteCapDraftState] = useState<{
    routeId: string
    generation: number
    value: string
  } | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [discoverySettingsOpen, setDiscoverySettingsOpen] = useState(false)
  const [candidatePickerOpen, setCandidatePickerOpen] = useState(false)
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[] | null>(null)
  const [candidateProfileDrafts, setCandidateProfileDrafts] = useState<Record<string, CandidateProfileDraft>>({})
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
    enabled: queryEnabled && Boolean(selectedRouteId) && tab !== 'operations',
    retry: false,
    refetchInterval: (current) => {
      const kind = current.state.data?.workflow?.kind || ''
      return /(running|discovery_running|canary_running)/.test(kind) ? 3_000 : APIFY_ACTOR_ROUTE_REFRESH_MS
    },
  })
  const detail = detailQuery.data
  const workflow = detail?.workflow ?? selectedSummary?.workflow
  const next = workflowPresentation[workflow?.kind || ''] ?? unknownWorkflowPresentation
  const candidateGoal: ApifyActorPoolGoal = workflow?.goal || 'initial_pool'
  const workflowFailure = workflowFailureNotice(workflow?.progress, candidateGoal)
  const candidatesQuery = useQuery({
    queryKey: queryKeys.apifyActorPoolCandidates(user.id, selectedRouteId, candidateGoal),
    queryFn: ({ signal }) => api.apifyActorPoolCandidates(selectedRouteId, candidateGoal, signal),
    enabled: queryEnabled && candidatePickerOpen && Boolean(selectedRouteId),
    retry: false,
  })

  const preferredCandidateIds = candidateGoal === 'upgrade_legacy' && candidatePickerOpen
    ? (candidatesQuery.data?.candidates ?? [])
      .filter((candidate) => candidate.selectable && candidate.existing_actor_upgrade)
      .slice(0, candidatesQuery.data?.required_selection_count ?? 3)
      .map((candidate) => candidate.candidate_id)
    : []
  const hasPreferredActorUpgrades = preferredCandidateIds.length > 0
  const activeSelectedCandidateIds = selectedCandidateIds ?? preferredCandidateIds

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

  function restoreSourceActivationFocus() {
    window.requestAnimationFrame(() => (
      sourceActivationTriggerRef.current ?? sourceDetailHeadingRef.current
    )?.focus())
  }

  function refreshSelected() {
    void routesQuery.refetch()
    if (tab !== 'operations') void detailQuery.refetch()
  }

  function profileDraft(candidate: ApifyActorPoolCandidate): CandidateProfileDraft {
    const options = candidate.validation_options ?? {
      timeout_seconds: 300,
      timeout_min_seconds: 180,
      timeout_max_seconds: 900,
      sample_items: 1 as const,
      allowed_sample_items: [1] as Array<1 | 3 | 5>,
      max_charge_usd: 0.02,
      max_charge_limit_usd: 0.10,
      supports_sample_items: false,
      options_hash: '',
    }
    return candidateProfileDrafts[candidate.candidate_id] ?? {
      timeoutSeconds: String(options?.timeout_seconds ?? 300),
      sampleItems: String(options?.sample_items ?? 1),
      maxChargeUsd: String(options?.max_charge_usd ?? 0.02),
    }
  }

  function updateCandidateProfile(
    candidateId: string,
    field: keyof CandidateProfileDraft,
    value: string,
  ) {
    const candidate = candidatesQuery.data?.candidates.find((item) => item.candidate_id === candidateId)
    if (!candidate) return
    setCandidateError(null)
    setCandidateProfileDrafts((current) => ({
      ...current,
      [candidateId]: { ...profileDraft(candidate), [field]: value },
    }))
  }

  function candidateProfileRequest(candidate: ApifyActorPoolCandidate): ApifyActorValidationProfileRequest | null {
    const options = candidate.validation_options
    if (!options) return null
    const draft = profileDraft(candidate)
    const timeoutSeconds = Number(draft.timeoutSeconds)
    const sampleItems = Number(draft.sampleItems)
    const maxChargeUsd = Number(draft.maxChargeUsd)
    if (!Number.isInteger(timeoutSeconds)
      || timeoutSeconds < options.timeout_min_seconds
      || timeoutSeconds > options.timeout_max_seconds
      || !options.allowed_sample_items.includes(sampleItems as 1 | 3 | 5)
      || !Number.isFinite(maxChargeUsd)
      || maxChargeUsd <= 0
      || maxChargeUsd > options.max_charge_limit_usd) return null
    return {
      candidate_id: candidate.candidate_id,
      timeout_seconds: timeoutSeconds,
      sample_items: sampleItems as 1 | 3 | 5,
      max_charge_usd: maxChargeUsd,
      options_hash: options.options_hash,
    }
  }

  function candidateHasUsefulProfileChange(candidate: ApifyActorPoolCandidate): boolean {
    if (!candidate.requires_profile_change || !candidate.last_failure) return true
    const profile = candidateProfileRequest(candidate)
    if (!profile) return false
    const failure = candidate.last_failure
    if (failure.code === 'apify_actor_run_timed_out') {
      return profile.timeout_seconds > failure.timeout_seconds
    }
    if (['suspicious_empty', 'apify_actor_suspicious_empty'].includes(failure.code)) {
      return Boolean(candidate.validation_options?.supports_sample_items)
        && profile.sample_items > failure.sample_items
    }
    return false
  }

  const discovery = useMutation({
    mutationFn: async () => {
      if (!selectedSummary) throw new Error('route unavailable')
      return api.refreshApifyActorPoolCandidates(
        selectedSummary.route_id,
        selectedSummary.generation,
        candidateGoal,
      )
    },
    onSuccess: () => {
      setCandidatePickerOpen(false)
      setSelectedCandidateIds([])
      setCandidateError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      if (selectedRouteId) void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, selectedRouteId) })
      actionToast.success('正在免费更新候选，不会启动 Actor')
    },
    onError: (caught) => setCandidateError(humanActorError(caught)),
  })

  const prepareManualPlan = useMutation({
    mutationFn: async () => {
      const candidates = candidatesQuery.data
      if (!candidates?.run_id || activeSelectedCandidateIds.length !== candidates.required_selection_count) {
        throw new Error('candidate selection incomplete')
      }
      const selected = activeSelectedCandidateIds.map((candidateId) => (
        candidates.candidates.find((candidate) => candidate.candidate_id === candidateId)
      ))
      const profiles = selected.map((candidate) => candidate ? candidateProfileRequest(candidate) : null)
      if (profiles.some((profile) => profile === null)) throw new Error('candidate validation profile invalid')
      return api.createApifyActorManualCanaryPlan(candidates.run_id, {
        goal: candidates.goal,
        candidate_ids: activeSelectedCandidateIds,
        candidate_validation_profiles: profiles as ApifyActorValidationProfileRequest[],
        expected_generation: candidates.generation,
        target_slot_count: 3,
      })
    },
    onSuccess: (plan) => {
      if (!plan.ready) {
        setCandidateError({
          reason: '所选 Actor 还不能组成安全主备',
          impact: '未启动验证，不会收费；现有配置保持不变。',
          next: '返回候选列表，调整选择后再继续。',
        })
        return
      }
      setCandidatePickerOpen(false)
      setCandidateError(null)
      setBatchError(null)
      setBatchTarget({ plan, approvalId: crypto.randomUUID() })
    },
    onError: (caught) => {
      const error = humanActorError(caught, '调整候选后重新生成验证计划。')
      setCandidateError(error)
      if (caught instanceof ApiError && [
        'apify_actor_route_generation_conflict',
        'apify_actor_manual_candidate_stale',
      ].includes(caught.code)) refreshSelected()
    },
  })

  const preparePlan = useMutation({
    mutationFn: async () => {
      const runId = workflow?.run_id || detail?.discovery_run_id
      const goal = workflow?.goal || 'initial_pool'
      if (!runId) throw new Error('plan unavailable')
      return queryClient.fetchQuery({
        queryKey: queryKeys.apifyActorCanaryPlan(user.id, runId, goal),
        queryFn: ({ signal }) => api.apifyActorCanaryPlan(runId, goal, signal),
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
        target_slot_count: 3 as const,
      } : {}),
    }),
    onSuccess: (response) => {
      setActiveBatchId(response.batch.batch_id)
      setBatchTarget(null)
      setBatchError(null)
      setSelectedCandidateIds([])
      restoreFocus(batchTriggerRef)
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
        restoreFocus(batchTriggerRef)
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
    mutationFn: ({ target, draft, rollbackRevisionId, perRunCapUsd }: {
      target: ApifyActorRouteDetail
      draft: PoolDraft
      rollbackRevisionId?: string
      perRunCapUsd?: number
    }) => api.updateApifyActorRouteActivePool(target.route_id, {
      expected_generation: target.generation,
      ...(rollbackRevisionId ? { rollback_revision_id: rollbackRevisionId } : {}),
      ...(perRunCapUsd !== undefined ? { per_run_cap_usd: perRunCapUsd } : {}),
      slots: slotOrder.map((slot) => ({ slot, revision_id: draft[slot] })),
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      setRollbackRevision(null)
      actionToast.success('高级 Route 设置已更新')
    },
    onError: (caught) => {
      refreshSelected()
      actionToast.danger('高级 Route 设置更新失败', {
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

  const reconcileValidation = useMutation({
    mutationFn: async (candidateId: string) => {
      if (!selectedSummary) throw new Error('route unavailable')
      return api.reconcileApifyActorValidation(
        selectedSummary.route_id,
        selectedSummary.generation,
        candidateId,
      )
    },
    onSuccess: () => {
      setCandidateError(null)
      void candidatesQuery.refetch()
      refreshSelected()
      actionToast.success('已重新读取原运行状态，没有重新启动 Actor')
    },
    onError: (caught) => setCandidateError(humanActorError(
      caught,
      '稍后再次核对；系统不会重新启动 Actor，也不会新增费用。',
    )),
  })

  const actionPending = discovery.isPending || preparePlan.isPending || prepareManualPlan.isPending || canaryBatch.isPending
    || activatePool.isPending || updatePool.isPending || sourceCanary.isPending || sourceActivate.isPending
    || reconcileValidation.isPending
  const activePoolDraft = useMemo(() => detail ? Object.fromEntries(
    detail.slots.map((slot) => [slot.slot, slot.revision_id]),
  ) as PoolDraft : null, [detail])
  const rollbackDraft = useMemo(() => {
    if (!activePoolDraft || !rollbackRevision) return null
    return { ...activePoolDraft, [rollbackSlot]: rollbackRevision.revision_id }
  }, [activePoolDraft, rollbackRevision, rollbackSlot])
  const routeCapDraft = detail && routeCapDraftState?.routeId === detail.route_id
    && routeCapDraftState.generation === detail.generation
    ? routeCapDraftState.value
    : detail ? String(detail.per_run_cap_usd) : ''
  const routeCapValue = Number(routeCapDraft)
  const routeCapValid = Number.isFinite(routeCapValue) && routeCapValue > 0 && routeCapValue <= 100
  const routeCapChanged = Boolean(detail && routeCapValid && Math.abs(routeCapValue - detail.per_run_cap_usd) > 1e-9)
  const candidateRequiredCount = candidatesQuery.data?.required_selection_count
    ?? (candidateGoal === 'complete_third' ? 1 : 3)
  const selectedCandidates = activeSelectedCandidateIds.map((candidateId) => (
    candidatesQuery.data?.candidates.find((candidate) => candidate.candidate_id === candidateId)
  )).filter((candidate): candidate is ApifyActorPoolCandidate => Boolean(candidate))
  const candidateSelectionComplete = activeSelectedCandidateIds.length === candidateRequiredCount
    && selectedCandidates.length === activeSelectedCandidateIds.length
    && selectedCandidates.every((candidate) => (
      candidateProfileRequest(candidate) !== null
      && candidateHasUsefulProfileChange(candidate)
    ))
  const sourceCatalog = new Map((catalogQuery.data?.sources ?? []).map((source) => [source.id, source]))
  const pendingSourceCount = detail?.source_validation_summary?.pending ?? 0
  const workflowPendingSourceCount = typeof workflow?.progress?.pending_sources === 'number'
    ? Math.max(0, Math.trunc(workflow.progress.pending_sources))
    : pendingSourceCount
  const candidateShortfall = Boolean(
    workflow?.blockers?.includes('candidate_shortfall')
    && next.action === 'start_discovery',
  )
  const eligibleCandidateCount = typeof workflow?.progress?.eligible_candidate_count === 'number'
    ? Math.max(0, Math.trunc(workflow.progress.eligible_candidate_count))
    : null
  const requiredSuccessCount = typeof workflow?.progress?.required_selection_count === 'number'
    ? Math.max(1, Math.trunc(workflow.progress.required_selection_count))
    : typeof workflow?.progress?.required_success_count === 'number'
      ? Math.max(1, Math.trunc(workflow.progress.required_success_count))
    : null
  const nextTitle = workflow?.kind === 'source_validation_required' && workflowPendingSourceCount > 0
    ? `有 ${workflowPendingSourceCount} 个来源等待启用`
    : candidateShortfall
      ? workflow?.goal === 'upgrade_legacy'
        ? '当前 Actor 尚未全部升级'
        : workflow?.goal === 'complete_third'
          ? '第三路备用候选不足'
          : '主备候选不足'
    : next.title
  const nextDescription = candidateShortfall
    ? workflow?.goal === 'upgrade_legacy'
      ? '上面的当前 Actor 仍继续运行。重新检查只会尝试为这 3 个 Actor 生成安全新版；任一 Actor 未通过就停止，不选择替补。免费检查不会启动 Actor。'
      : `${eligibleCandidateCount !== null && requiredSuccessCount !== null
        ? `当前找到 ${eligibleCandidateCount}/${requiredSuccessCount} 个符合条件的候选。`
        : '当前符合条件的候选还不足。'}已通过的候选会保留；继续免费搜索不会启动 Actor 或产生费用。`
    : next.description
  const nextCta = candidateShortfall
    ? workflow?.goal === 'upgrade_legacy' ? '查看当前 Actor 升级状态' : '继续免费搜索候选'
    : next.cta

  function performNextAction() {
    if (actionPending) return
    if (candidateShortfall && workflow?.goal === 'upgrade_legacy') {
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

  function openSourceCanary(slot: ApifyActorSourceSupport['slots'][number]) {
    if (!detail || !sourceSupportQuery.data || !slot.revision_id) return
    const revision = detail.revisions.find((item) => item.revision_id === slot.revision_id)
    if (!revision) return
    setCanaryError('')
    setCanaryTarget({
      kind: 'source',
      sourceId: sourceSupportQuery.data.source_id,
      revision,
      expectedGeneration: sourceSupportQuery.data.generation,
      capUsd: Math.min(detail.per_run_cap_usd, sourceSupportQuery.data.remaining_budget_usd),
      routeKey: detail.route_key,
      routeLabel: routeProductNames[selectedProfileId]?.label || selectedProfileId,
      routeMode: detail.mode,
      actorPricingLabel: actorPricingLabel(revision),
      buildLabel: revision.build_number || revision.build_id || '未固定',
      approvalId: crypto.randomUUID(),
    })
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
        <div className="sticky top-0 z-10 -mx-1 overflow-visible bg-transparent px-1 py-1 backdrop-blur-sm">
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
              <Card variant="secondary" className="grid gap-4 border border-separator p-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div><Card.Title>当前主备</Card.Title><Card.Description className="mt-1">{detail.runnable_slots}/3 路可用 · {detail.mode === 'fallback' ? '原生优先，Actor 故障回退' : 'Actor 主抓取'}</Card.Description></div>
                  <StatusIndicator label={next.status} tone={next.tone} />
                </div>
                <ol className="grid gap-3 min-[768px]:grid-cols-3" aria-label="当前 Actor 主备槽位">
                  {slotOrder.map((name) => {
                    const slot = detail.slots.find((item) => item.slot === name)
                    const revision = slot?.revision
                    const slotStatus = guidedSlotStatus(name, revision)
                    return <li key={name} className="min-w-0 rounded-control border border-separator bg-default p-3">
                      <div className="flex items-center justify-between gap-2"><span className="type-control">{slotDisplayLabels[name]}</span><StatusIndicator label={slotStatus.label} tone={slotStatus.tone} /></div>
                      <p className="type-control mt-3 break-words">{revision?.actor_public_name || (revision ? `${revision.publisher} Actor` : '当前为空')}</p>
                      <p className="type-meta mt-1 break-words text-muted">{revision ? `发布者 ${revision.publisher} · ${slotStatus.note}` : slotStatus.note}</p>
                    </li>
                  })}
                </ol>
              </Card>

              <Card variant="secondary" className="grid gap-4 border border-separator p-4 shadow-sm" data-testid="actorops-next-action">
                <div className="flex flex-col gap-4 min-[720px]:flex-row min-[720px]:items-center min-[720px]:justify-between">
                  <div className="min-w-0"><Card.Title>{nextTitle}</Card.Title><Card.Description className="mt-1 max-w-3xl">{nextDescription}</Card.Description></div>
                  {nextCta && <Button
                    ref={next.action === 'select_candidates' ? candidateTriggerRef : next.action === 'approve_canary' ? batchTriggerRef : next.action === 'approve_activation' ? activationTriggerRef : undefined}
                    className="w-full shrink-0 min-[720px]:w-auto"
                    isDisabled={actionPending}
                    onPress={performNextAction}
                  >{actionPending ? '处理中…' : nextCta}</Button>}
                </div>
                {workflowFailure && <HumanActorErrorNotice error={workflowFailure} />}
                {workflow?.kind && /(setup|backup_2|legacy)_(discovery|candidate|canary|activation)/.test(workflow.kind) && <div className="grid gap-2 border-t border-separator pt-3 type-meta text-muted min-[640px]:grid-cols-3" aria-label="配置流程">
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
                  {activePoolDraft && <SettingsDisclosure title="Route 单次费用上限" description="使用当前 generation 保存，商城价格不会自动放宽。">
                    <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-end">
                      <TextField fullWidth value={routeCapDraft} onChange={(value) => detail && setRouteCapDraftState({ routeId: detail.route_id, generation: detail.generation, value })} isDisabled={actionPending} isInvalid={Boolean(routeCapDraft) && !routeCapValid}>
                        <Label>单次费用上限（USD）</Label><Input type="number" min={0.000001} max={100} step={0.001} /><Description>仅影响后续 Actor Run。</Description>{Boolean(routeCapDraft) && !routeCapValid && <FieldError>请输入大于 0 且不超过 100 的数值。</FieldError>}
                      </TextField>
                      <Button size="sm" isDisabled={!routeCapChanged || actionPending} onPress={() => updatePool.mutate({ target: detail, draft: activePoolDraft, perRunCapUsd: routeCapValue })}>保存费用上限</Button>
                    </div>
                  </SettingsDisclosure>}
                  <SettingsDisclosure title="Revision 差异与回滚" description="Build 与 Manifest 保持不可变；回滚同样受 generation 保护。">
                    <RevisionHistory detail={detail} actionPending={actionPending} onRollback={(revision) => {
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
                  const status = sourceStatusPresentation(row.binding_status)
                  return <SettingsItem key={row.source_id} density="compact" label={source?.display_name || sourceShortLabel(row.source_id)} description={source ? sourceShortLabel(row.source_id) : '已脱敏来源；真实目标不会在此显示'} icon={<Icons.RadioTower size={17} aria-hidden="true" />} trailing={<div className="flex items-center gap-2"><StatusIndicator label={status.label} tone={status.tone} /><Button size="sm" variant="ghost" onPress={() => replaceQuery('sources', row.source_id)}>{status.tone === 'success' ? '查看' : '继续验证'}</Button></div>} />
                })}
              </SettingsGroup>}
              {selectedSourceId && selectedSourceValid && <Card variant="secondary" className="grid gap-4 border border-separator p-4" aria-label={`来源 ${selectedSourceId} 验证详情`}>
                <div ref={sourceDetailHeadingRef} tabIndex={-1} data-testid="actorops-source-detail-heading" className="outline-none"><Card.Title>{sourceCatalog.get(selectedSourceId)?.display_name || sourceShortLabel(selectedSourceId)}</Card.Title><Card.Description className="mt-1">只显示当前主备的验证进度；真实目标保持隐藏。</Card.Description></div>
                {sourceSupportQuery.isPending && <LoadingState label="正在读取来源验证" rows={2} />}
                {sourceSupportQuery.data && <>
                  <ol className="grid gap-2 min-[720px]:grid-cols-3" aria-label="来源主备验证槽位">{sourceSupportQuery.data.slots.map((slot) => <li key={slot.slot} className="rounded-control border border-separator bg-default p-3"><p className="type-control">{slotDisplayLabels[slot.slot]}</p><p className="type-meta mt-1 text-muted">{slot.status === 'passed' ? '已通过' : ['queued', 'running'].includes(slot.status) ? '验证中' : slot.status === 'blocked' ? '需先升级主备' : slot.status === 'failed' ? '需要处理' : '待验证'} · {formatActorDateTime(slot.last_canary_at ?? null)}</p></li>)}</ol>
                  <p className="type-meta text-muted">实际费用 {formatActorUsd(sourceSupportQuery.data.spent_usd, true)} · 已预留 {formatActorUsd(sourceSupportQuery.data.reserved_usd, true)} · 剩余 {formatActorUsd(sourceSupportQuery.data.remaining_budget_usd, true)}</p>
                  {(() => {
                    const nextAction = sourceSupportQuery.data.next_action
                    if (nextAction?.kind === 'upgrade_pool_required') return <HeroNotice title="先升级 Actor 主备" status="warning" role="alert"><p>当前兼容 Actor 没有固定 Build，无法安全验证这个来源；继续提交也不会成功。</p><p className="mt-1"><strong>影响：</strong>没有启动新的 Actor，现有抓取继续运行。</p><p className="mt-1"><strong>下一步：</strong>回到主备配置升级原 Actor，升级生效后再验证来源。</p><Button className="mt-3" size="sm" variant="secondary" onPress={() => replaceQuery('pool')}>前往主备配置</Button></HeroNotice>
                    const waiting = sourceSupportQuery.data.slots.some((slot) => ['queued', 'running'].includes(slot.status))
                    const nextSlot = sourceSupportQuery.data.slots.find((slot) => slot.can_canary)
                    if (waiting) return <HeroNotice title="来源验证正在运行" status="warning" role="status">完成后会自动显示下一项安全操作。</HeroNotice>
                    if (nextSlot) return <div className="flex flex-col gap-3 rounded-control border border-separator bg-default p-3 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between"><div><p className="type-control">下一步：验证{slotDisplayLabels[nextSlot.slot]}</p><p className="type-meta mt-1 text-muted">一次限额付费 Canary，不会并发调用其他 Actor。</p></div><Button ref={canaryTriggerRef} className="w-full min-[640px]:w-auto" onPress={() => openSourceCanary(nextSlot)}>查看并确认付费验证</Button></div>
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
            {operationsContent}
          </div>}
        </Tabs.Panel>
      </Tabs>}
    </div>

    <Modal isOpen={candidatePickerOpen} onOpenChange={(open) => {
      if (!open && !prepareManualPlan.isPending && !discovery.isPending) {
        setCandidatePickerOpen(false)
        setSelectedCandidateIds([])
        setCandidateError(null)
        restoreFocus(candidateTriggerRef)
      }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开 Actor 候选列表</Modal.Trigger>
      <Modal.Backdrop isDismissable={!prepareManualPlan.isPending && !discovery.isPending} isKeyboardDismissDisabled={prepareManualPlan.isPending || discovery.isPending}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{candidateGoal === 'complete_third' ? '选择第三个备用 Actor' : candidateGoal === 'upgrade_legacy' ? '升级当前 3 个 Actor' : '选择 3 个 Actor'}</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-4" aria-busy={candidatesQuery.isPending || prepareManualPlan.isPending || discovery.isPending}>
          <HeroNotice title="选择候选不会产生费用" status="default" role="status">{candidateGoal === 'upgrade_legacy'
            ? hasPreferredActorUpgrades
              ? '可安全升级的当前 Actor 已自动选中。只允许这 3 个当前 Actor；任一未通过就停止。'
              : candidatesQuery.data
                ? '上面的 3 个当前 Actor 已列出。点击“重新检查当前 Actor（免费）”只会生成它们的安全新版，不会寻找替补。'
                : '系统只检查上面的 3 个当前 Actor；无法形成安全新版时保持兼容池并停止。'
            : '系统已经按当前抓取类型、发布者分散和费用上限完成免费筛选。你只选择成员，服务端负责安全槽位顺序和固定版本。'}</HeroNotice>
          {candidateGoal === 'upgrade_legacy' && <dl className="grid gap-3 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
            <div><dt className="type-control">可扩大召回</dt><dd className="mt-1 text-muted">直接检查当前 Primary、Backup 1、Backup 2；最多 3 个内容导向查询；有效候选检查上限 30；可信空结果样本只允许从 1 扩到 3。</dd></div>
            <div><dt className="type-control">不可放宽底线</dt><dd className="mt-1 text-muted">必须公开可运行、精确成功 Build、输入与 Dataset Schema 可验证、Manifest 路径真实、单次不超过 $0.02；3 个 Actor 必须唯一且至少两个发布者，付费 Canary 必须返回有效内容或可信空结果。</dd></div>
          </dl>}
          {candidatesQuery.isPending && <LoadingState label="正在读取可选 Actor" rows={3} />}
          {candidatesQuery.isError && <HumanActorErrorNotice error={humanActorError(candidatesQuery.error)} />}
          {candidatesQuery.data && <>
            <div className="flex items-center justify-between gap-3 type-meta text-muted"><span>请选择 {candidateRequiredCount} 个</span><span aria-live="polite">已选 {activeSelectedCandidateIds.length}/{candidateRequiredCount}</span></div>
            {candidatesQuery.data.candidates.length > 0 ? <div className="grid gap-2" role="group" aria-label="可选 Actor">
              {candidatesQuery.data.candidates.map((candidate) => {
                const selected = activeSelectedCandidateIds.includes(candidate.candidate_id)
                const failure = candidate.last_failure
                const draft = profileDraft(candidate)
                const statusReadFailure = failure && [
                  'apify_run_status_unavailable',
                  'apify_actor_run_status_unavailable',
                  'apify_run_reconcile_required',
                ].includes(failure.code)
                const contractFailure = failure && [
                  'apify_actor_contract_mismatch',
                  'apify_actor_identity_mismatch',
                ].includes(failure.code)
                return <div key={candidate.candidate_id} className="rounded-control border border-separator bg-surface-secondary p-3">
                  <Checkbox isSelected={selected} isDisabled={!candidate.selectable || (candidateRequiredCount > 1 && activeSelectedCandidateIds.length >= candidateRequiredCount && !selected) || prepareManualPlan.isPending} onChange={(value) => toggleCandidate(candidate.candidate_id, value)}>
                    <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><span className="min-w-0"><span className="block type-control break-words">{candidate.actor_public_name}{candidate.existing_actor_upgrade && <span className="ml-2 rounded-full bg-success/15 px-2 py-0.5 type-meta text-success">当前 Actor</span>}</span><span className="mt-1 block type-meta text-muted">发布者 {candidate.publisher} · {poolCandidatePricingLabel(candidate)} · {candidateGoal === 'upgrade_legacy' ? '固定单次上限' : '可调单次上限最高'} {formatActorUsd(candidate.max_validation_charge_usd, true)}</span></span></Checkbox.Content>
                  </Checkbox>
                  {!candidate.selectable && <p className="type-meta mt-2 pl-7 text-warning">{candidate.existing_actor_upgrade ? '当前状态：' : '不可选择：'}{poolCandidateUnavailableLabel(candidate.unavailable_reason)}</p>}
                  {failure && <div className="mt-3 grid gap-3 rounded-control border border-warning/40 bg-default p-3">
                    <div className="type-meta">
                      <p className="type-control text-warning">{failure.code === 'apify_actor_run_timed_out'
                        ? `验证超过 ${Math.max(1, Math.round((failure.duration_seconds ?? failure.timeout_seconds) / 60))} 分钟`
                        : ['suspicious_empty', 'apify_actor_suspicious_empty'].includes(failure.code)
                          ? '运行已完成，但返回 0 条内容'
                          : statusReadFailure
                            ? '原运行结果还没有确认'
                            : contractFailure
                              ? '字段或来源身份没有匹配成功'
                              : failure.code === 'apify_actor_metadata_only'
                                ? '这个 Actor 只返回元数据，不能抓取内容'
                                : '上次验证没有通过'}</p>
                      <p className="mt-1 text-muted">耗时 {failure.duration_seconds ?? 0} 秒 · Dataset {failure.dataset_row_count ?? '未知'} 条 · {failure.cost_final ? `已结算 ${formatActorUsd(failure.actual_cost_usd, true)}` : '费用待对账'}</p>
                      <p className="mt-1 text-muted">当前参数：等待 {failure.timeout_seconds} 秒 · 样本 {failure.sample_items} 条 · 单次上限 {formatActorUsd(failure.max_charge_usd, true)}</p>
                      <p className="mt-2"><strong>下一步：</strong>{failure.code === 'apify_actor_run_timed_out'
                        ? candidateGoal === 'upgrade_legacy'
                          ? '当前 Actor 的升级在这里停止；不能通过提价、延长等待或更换 Actor 绕过。'
                          : failure.timeout_seconds < 900
                          ? '增加等待时间；如果 Actor 需要更高启动预算，再同步提高单次费用上限。'
                          : '等待时间已经是 15 分钟上限，请选择另一个候选。'
                        : ['suspicious_empty', 'apify_actor_suspicious_empty'].includes(failure.code)
                          ? candidateGoal === 'upgrade_legacy'
                            ? candidate.validation_options?.supports_sample_items && failure.sample_items < 3
                              ? '保持 300 秒等待和 $0.02 上限，只把验证样本从 1 扩大到 3。'
                              : '3 条样本仍未通过，当前 Actor 的升级停止；不扩大到 5、不换 Actor。'
                            : candidate.validation_options?.supports_sample_items
                              ? failure.sample_items < 5
                              ? '延长等待无效；把验证样本扩大到 3 或 5 条。'
                              : '已经使用 5 条最大样本，延长等待无效；请选择另一个候选。'
                              : '这个 Actor 不支持扩大样本，请选择另一个候选。'
                          : statusReadFailure
                            ? '免费重新读取同一个 Run 和 Dataset，不会重新启动 Actor。'
                            : contractFailure
                              ? candidateGoal === 'upgrade_legacy'
                                ? '可免费重新检查同一个当前 Actor；仍不匹配就停止升级，不换 Actor。'
                                : '免费更新当前抓取类型的候选并重新生成字段映射；仍不匹配就换 Actor。'
                              : candidateGoal === 'upgrade_legacy'
                                ? '当前 Actor 的升级停止；系统不会原样重复付费或换 Actor。'
                                : '请选择另一个候选；系统不会原样重复付费。'}</p>
                    </div>
                    {candidateGoal !== 'upgrade_legacy' && failure.code === 'apify_actor_run_timed_out' && failure.timeout_seconds < 900 && <div className="grid gap-3 min-[640px]:grid-cols-2">
                      <TextField fullWidth value={draft.timeoutSeconds} onChange={(value) => updateCandidateProfile(candidate.candidate_id, 'timeoutSeconds', value)} isDisabled={!selected || prepareManualPlan.isPending}>
                        <Label>等待时间（秒）</Label><Input type="number" min={180} max={900} step={60} /><Description>只对新计划生效；范围 180–900 秒。</Description>
                      </TextField>
                      <TextField fullWidth value={draft.maxChargeUsd} onChange={(value) => updateCandidateProfile(candidate.candidate_id, 'maxChargeUsd', value)} isDisabled={!selected || prepareManualPlan.isPending}>
                        <Label>单次费用上限（USD）</Label><Input type="number" min={0.000001} max={0.10} step={0.005} /><Description>不会自动放宽，最高 $0.10。</Description>
                      </TextField>
                    </div>}
                    {['suspicious_empty', 'apify_actor_suspicious_empty'].includes(failure.code) && candidate.validation_options?.supports_sample_items && (candidateGoal === 'upgrade_legacy' ? failure.sample_items < 3 : failure.sample_items < 5) && <HeroSelect label="验证样本数" value={draft.sampleItems} onChange={(value) => updateCandidateProfile(candidate.candidate_id, 'sampleItems', value)} isDisabled={!selected || prepareManualPlan.isPending} options={candidate.validation_options.allowed_sample_items.map((value) => ({ id: String(value), label: `${value} 条` }))} />}
                    {statusReadFailure && <Button size="sm" variant="secondary" isDisabled={reconcileValidation.isPending} onPress={() => reconcileValidation.mutate(candidate.candidate_id)}>{reconcileValidation.isPending ? '正在核对…' : '重新核对运行状态（免费）'}</Button>}
                    {contractFailure && <Button size="sm" variant="secondary" isDisabled={discovery.isPending} onPress={() => discovery.mutate()}>{discovery.isPending ? '正在更新候选与字段映射…' : '更新候选与字段映射（免费）'}</Button>}
                    {candidate.requires_profile_change && selected && !candidateHasUsefulProfileChange(candidate) && <p className="type-meta text-danger" role="alert">必须按上面的建议修改参数，原样验证已被禁止。</p>}
                  </div>}
                </div>
              })}
            </div> : <HeroNotice title="暂时没有可选 Actor" status="warning">{candidateGoal === 'upgrade_legacy' ? '当前 3 个 Actor 尚未全部满足安全升级条件。升级已停止，现有兼容池不会改变。' : '当前没有同时满足来源能力、发布者分散和费用上限的候选。现有线路不会改变。'}</HeroNotice>}
          </>}
          {candidateError && <HumanActorErrorNotice error={candidateError} />}
        </div></Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={prepareManualPlan.isPending || discovery.isPending} onPress={() => { setCandidatePickerOpen(false); setSelectedCandidateIds([]); setCandidateError(null); restoreFocus(candidateTriggerRef) }}>取消</Button>
          <Button variant="secondary" isDisabled={prepareManualPlan.isPending || discovery.isPending} onPress={() => discovery.mutate()}>{candidateGoal === 'upgrade_legacy' ? discovery.isPending ? '正在检查当前 Actor…' : '重新检查当前 Actor（免费）' : discovery.isPending ? '正在更新…' : '更新候选（免费）'}</Button>
          <Button isDisabled={!candidateSelectionComplete || prepareManualPlan.isPending || discovery.isPending} onPress={() => prepareManualPlan.mutate()}>{prepareManualPlan.isPending ? '正在核对…' : '继续'}</Button>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>

    <Modal isOpen={Boolean(batchTarget)} onOpenChange={(open) => {
      if (!open && !canaryBatch.isPending) { setBatchTarget(null); setBatchError(null); restoreFocus(batchTriggerRef) }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开付费验证确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!canaryBatch.isPending} isKeyboardDismissDisabled={canaryBatch.isPending}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>验证所选 Actor</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-3" aria-busy={canaryBatch.isPending}><HeroNotice title="严格串行，并受总费用上限保护" status="warning" role="status">这是确认 1/2。验证通过并确认生效前，当前配置不会改变；未启动或不再需要的项费用为 $0。</HeroNotice>{batchTarget && <><dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta"><div><dt className="text-muted">抓取类型</dt><dd className="mt-1">{routeProductNames[routeProfileId(batchTarget.plan)]?.label || routeIdentity(batchTarget.plan.platform, batchTarget.plan.target_type, batchTarget.plan.capability)}</dd></div><div><dt className="text-muted">本批总费用上限</dt><dd className="mt-1 tabular-nums">{formatActorUsd(batchTarget.plan.max_total_charge_usd, true)}</dd></div><div><dt className="text-muted">来源预验证</dt><dd className="mt-1">{batchTarget.plan.source_count ?? 0} 个已启用来源 · 最多 {batchTarget.plan.source_validation_count ?? 0} 次缺失验证</dd></div><div><dt className="text-muted">验证边界</dt><dd className="mt-1">只验证你选择的 Actor；系统不会静默换人或超出总费用上限。</dd></div></dl><ol className="grid gap-2">{batchTarget.plan.items.map((item) => <li key={item.revision_id} className="rounded-control border border-separator bg-surface-secondary p-3 type-meta"><p className="type-control">{item.actor_public_name || `${item.publisher} Actor`}</p><p className="mt-1 text-muted">发布者 {item.publisher} · 单次封顶 {formatActorUsd(item.authorized_cap_usd, true)}{item.already_validated ? ' · 已有成功证据可复用' : ''}</p>{item.validation_profile && <p className="mt-1 text-muted">等待 {item.validation_profile.timeout_seconds} 秒 · 样本 {item.validation_profile.sample_items} 条 · 参数费用上限 {formatActorUsd(item.validation_profile.max_charge_usd, true)}</p>}</li>)}</ol></>}{batchError && <HumanActorErrorNotice error={batchError} />}</div></Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={canaryBatch.isPending} onPress={() => { setBatchTarget(null); setBatchError(null); restoreFocus(batchTriggerRef) }}>取消</Button><Button isDisabled={!batchTarget?.plan.ready || canaryBatch.isPending} onPress={() => batchTarget && canaryBatch.mutate(batchTarget)}>{canaryBatch.isPending ? '提交中…' : `确认验证（最高 ${formatActorUsd(batchTarget?.plan.max_total_charge_usd ?? null, true)}）`}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>

    <Modal isOpen={Boolean(activationTarget)} onOpenChange={(open) => {
      if (!open && !activatePool.isPending) { setActivationTarget(null); setActivationError(null); restoreFocus(activationTriggerRef) }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开主备生效确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!activatePool.isPending} isKeyboardDismissDisabled={activatePool.isPending}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{activationTarget?.workflow?.goal === 'complete_third' ? '确认补齐备用 2' : activationTarget?.workflow?.goal === 'upgrade_legacy' ? '确认切换到新版主备' : '确认启用 Actor 主备'}</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-3" aria-busy={activatePool.isPending}><HeroNotice title="这是确认 2/2" status="warning" role="status">槽位和已预验证来源会在同一事务中生效；运行中的任务继续使用原配置。</HeroNotice>{activationTarget && <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta"><div><dt className="text-muted">当前方案</dt><dd className="mt-1">{activationTarget.slots.filter((slot) => slot.revision_id).length}/3 路</dd></div><div><dt className="text-muted">生效后</dt><dd className="mt-1">{activationTarget.workflow?.goal === 'complete_third' ? '补齐为 3/3，原主用与备用 1 不变' : activationTarget.workflow?.goal === 'upgrade_legacy' ? '零中断切换为新版 3/3 主备' : '启用完整 3/3 主备'}</dd></div><div><dt className="text-muted">停机影响</dt><dd className="mt-1">无停机；只有下一任务读取新配置。</dd></div></dl>}{activationError && <HumanActorErrorNotice error={activationError} />}</div></Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={activatePool.isPending} onPress={() => { setActivationTarget(null); setActivationError(null); restoreFocus(activationTriggerRef) }}>取消</Button><Button isDisabled={!activationTarget || activatePool.isPending} onPress={() => activationTarget && activatePool.mutate(activationTarget)}>{activatePool.isPending ? '生效中…' : '确认生效'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>

    <Modal isOpen={Boolean(canaryTarget)} onOpenChange={(open) => {
      if (!open && !sourceCanary.isPending) { setCanaryTarget(null); setCanaryError(''); restoreFocus(canaryTriggerRef) }
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开来源付费验证确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!sourceCanary.isPending} isKeyboardDismissDisabled={sourceCanary.isPending}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>确认来源付费验证</Modal.Heading></Modal.Header><Modal.Body><div className="grid gap-3"><HeroNotice title="只验证下一缺失槽位" status="warning" role="status">精确 Build 串行执行一次；不会显示真实目标，也不会自动重试。</HeroNotice>{canaryTarget && <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta"><div><dt className="text-muted">Actor / Build</dt><dd className="mt-1">{canaryTarget.kind === 'source' ? canaryTarget.revision.actor_public_name || `${canaryTarget.revision.publisher} Actor` : ''} · {canaryTarget.buildLabel}</dd></div><div><dt className="text-muted">本次封顶</dt><dd className="mt-1">{formatActorUsd(canaryTarget.capUsd, true)}</dd></div></dl>}{canaryError && <HeroNotice title={canaryError} status="danger" />}</div></Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={sourceCanary.isPending} onPress={() => { setCanaryTarget(null); setCanaryError(''); restoreFocus(canaryTriggerRef) }}>取消</Button><Button isDisabled={!canaryTarget || sourceCanary.isPending} onPress={() => canaryTarget && sourceCanary.mutate(canaryTarget)}>{sourceCanary.isPending ? '提交中…' : '确认付费试跑'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>

    <Modal isOpen={sourceActivationOpen} onOpenChange={(open) => { if (!open && !sourceActivate.isPending) { setSourceActivationOpen(false); restoreSourceActivationFocus() } }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开来源首次启用确认</Modal.Trigger><Modal.Backdrop isDismissable={!sourceActivate.isPending} isKeyboardDismissDisabled={sourceActivate.isPending}><Modal.Container><Modal.Dialog><Modal.Header><Modal.Heading>确认首次启用来源</Modal.Heading></Modal.Header><Modal.Body><HeroNotice title="所有当前主备均已验证" status="success" role="status">确认后该来源开始使用当前 Actor 主备；后续槽位变化只复验变化部分。</HeroNotice></Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={sourceActivate.isPending} onPress={() => { setSourceActivationOpen(false); restoreSourceActivationFocus() }}>取消</Button><Button isDisabled={sourceActivate.isPending} onPress={() => sourceActivate.mutate()}>{sourceActivate.isPending ? '启用中…' : '确认首次启用'}</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>

    <Modal isOpen={Boolean(rollbackRevision)} onOpenChange={(open) => { if (!open && !updatePool.isPending) setRollbackRevision(null) }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开 Revision 回滚确认</Modal.Trigger><Modal.Backdrop isDismissable={!updatePool.isPending} isKeyboardDismissDisabled={updatePool.isPending}><Modal.Container><Modal.Dialog><Modal.Header><Modal.Heading>回滚不可变 Revision</Modal.Heading></Modal.Header><Modal.Body><div className="grid gap-4"><HeroNotice title="回滚会创建新的 Route generation" status="warning" role="status">运行中的旧任务可结束，但过期结果不能写入新缓存。</HeroNotice><p className="type-control break-all">{rollbackRevision?.revision_id}</p><HeroSelect label="回滚到槽位" value={rollbackSlot} onChange={(value) => setRollbackSlot(value as ApifyActorSlotName)} isDisabled={updatePool.isPending} options={slotOrder.map((slot) => ({ id: slot, label: slotDisplayLabels[slot] }))} /></div></Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={updatePool.isPending} onPress={() => setRollbackRevision(null)}>取消</Button><Button isDisabled={!detail || !rollbackDraft || updatePool.isPending} onPress={() => detail && rollbackDraft && rollbackRevision && updatePool.mutate({ target: detail, draft: rollbackDraft, rollbackRevisionId: rollbackRevision.revision_id })}>{updatePool.isPending ? '回滚中…' : '确认回滚'}</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
  </>
}

/** @deprecated Temporary compatibility export for downstream tests and one-version legacy surfaces. */
export function LegacyHeroActorOpsControlPlane({ queryEnabled = true }: { queryEnabled?: boolean }) {
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
  const [discoverySettingsOpen, setDiscoverySettingsOpen] = useState(false)
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
          {detail.activation_recommendation?.already_active && activePoolDraft && <SettingsDisclosure title="调整 Route 单次费用上限" description="管理员明确调整后按当前 generation 热加载。" className="mt-3">
            <div className="flex flex-wrap items-end gap-3">
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
          </SettingsDisclosure>}
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

      <section className="border-t border-separator pt-5" aria-label="Revision 差异与回滚">
        <SettingsDisclosure title="Revision 差异与回滚" description="旧 Build 和 Manifest 保留为不可变 Revision；回滚也使用当前 generation。">
          <RevisionHistory detail={detail} onRollback={(revision) => {
            const matching = detail.slots.find((slot) => slot.revision?.actor_id === revision.actor_id)
            setRollbackSlot(matching?.slot ?? 'primary')
            setRollbackRevision(revision)
          }} actionPending={actionPending} />
        </SettingsDisclosure>
      </section>

      <section className="border-t border-separator pt-5" aria-label="Actor Discovery AI 设置">
        <SettingsDisclosure
          title="Actor Discovery AI 设置"
          description="继承工作区 AI 配置；仅在展开后读取和编辑低频参数。"
          onOpenChange={setDiscoverySettingsOpen}
        ><DiscoverySettingsPanel queryEnabled={queryEnabled && discoverySettingsOpen} /></SettingsDisclosure>
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
