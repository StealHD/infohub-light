import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ActorOpsV2Candidate, ActorOpsV2ReplacementPlan, ActorOpsV2RouteDetail } from '../../api/actorOpsV2Types'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Drawer, StatusNotice } from '../../design-system'
import { ActorOpsV2CandidateCard } from './ActorOpsV2CandidateCard'
import { ActorOpsV2DiscoveryProgress, ActorOpsV2ReplacementProgress, ActorOpsV2WorkflowSteps } from './ActorOpsV2WorkflowProgress'
import { actorOpsV2CandidateHasPublicIdentity, actorOpsV2CandidateIssueLabel, actorOpsV2CandidateLabel, actorOpsV2MappingIssueLabel, compareActorOpsV2ReplacementCandidates, type ActorOpsV2CandidateView, type ActorOpsV2RouteView } from './actorOpsV2RouteModel'
import { replacementError, replacementFailureCostMessage, replacementRequestError } from './actorOpsV2ReplacementErrors'

export type ActorOpsV2ReplacementTarget = {
  candidate: ActorOpsV2CandidateView | null
  assignment: 'active' | 'standby'
  priority: number
  slotLabel: string
}

const ACTIVE_PLAN_STATUSES = ['previewed', 'authorized', 'running', 'ready']
const REVALIDATABLE_ERRORS = new Set([
  'actorops_replacement_contract_mismatch',
  'actorops_replacement_published_at_invalid',
  'actorops_replacement_target_identity_mismatch',
  'actorops_replacement_output_url_invalid',
  'actorops_replacement_output_outside_window',
])

export function ActorOpsV2ReplacementDrawer({ route, target, targets = [], open, onOpenChange, onUpdated }: {
  route: ActorOpsV2RouteView; target: ActorOpsV2ReplacementTarget | null
  targets?: ActorOpsV2ReplacementTarget[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onUpdated: () => Promise<unknown>
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<ActorOpsV2CandidateView | null>(null)
  const [selectedTarget, setSelectedTarget] = useState<ActorOpsV2ReplacementTarget | null>(target)
  const [plan, setPlan] = useState<ActorOpsV2ReplacementPlan | null>(null)
  const [dismissedPlanId, setDismissedPlanId] = useState('')
  const [trackedDiscoveryId, setTrackedDiscoveryId] = useState('')
  const [selectionMode, setSelectionMode] = useState<'auto' | 'manual'>('auto')
  const { candidateKey, detailKey } = replacementQueryKeys(user.id, route.route_id)
  const candidatesQuery = useQuery({
    queryKey: candidateKey,
    queryFn: ({ signal }) => api.actorOpsV2Candidates(route.route_id, signal),
    enabled: open,
    retry: false,
    refetchInterval: open ? 3_000 : false,
  })
  const detailQuery = useQuery({
    queryKey: detailKey,
    queryFn: ({ signal }) => api.actorOpsV2Route(route.route_id, signal),
    enabled: open,
    retry: false,
    refetchInterval: open ? 3_000 : false,
  })
  const activeTarget = selectedTarget || target
  const resumablePlan = latestDrawerPlan(detailQuery.data, activeTarget, dismissedPlanId)
  const trackedPlan = plan || resumablePlan
  const planQuery = useQuery({
    queryKey: queryKeys.actorOpsV2Replacement(user.id, route.route_id, trackedPlan?.plan_id || ''),
    queryFn: ({ signal }) => api.actorOpsV2Replacement(route.route_id, trackedPlan?.plan_id || '', signal),
    enabled: open && Boolean(trackedPlan?.plan_id) && ['authorized', 'running'].includes(trackedPlan?.status || ''),
    retry: false,
    refetchInterval: (query) => {
      const latest = unwrapPlan(query.state.data)
      return latest && ['failed', 'cancelled', 'ready', 'applied'].includes(latest.status) ? false : 3_000
    },
  })
  const visiblePlan = unwrapPlan(planQuery.data) || plan || resumablePlan
  const candidateList = useMemo(() => replacementCandidates(candidatesQuery.data), [candidatesQuery.data])
  const recommended = candidateList.systemCandidates[0] || candidateList.staticCandidates[0] || candidateList.sampleCandidates[0] || null
  const effectiveSelected = selectionMode === 'manual' ? selected : recommended
  const [cap, total] = replacementCaps(route)
  const refreshDrawer = () => refreshReplacementDrawer(queryClient, candidateKey, detailKey)
  useReplacementFailureNotice(visiblePlan, user.id, route.route_id, onUpdated)
  const close = (next: boolean) => { onOpenChange(next); if (!next) { setSelected(null); setSelectedTarget(null); setPlan(null); setSelectionMode('auto') } }
  const actions = useReplacementActions({
    api, route, target: activeTarget, plan: visiblePlan, cap, total,
    refresh: refreshDrawer,
    onUpdated,
    onPlan: setPlan,
    onDiscovery: (discoveryId) => { setTrackedDiscoveryId(discoveryId); setSelectionMode('auto') },
    onApplied: () => close(false),
  })
  const [currentSlot, differentSlot] = replacementSlotState(visiblePlan, activeTarget)
  const actionVerb = activeTarget?.candidate === null && !differentSlot ? '补充' : activeTarget ? '替换' : '管理'
  const discoveryView = latestDiscovery(detailQuery.data, trackedDiscoveryId)
  return <Drawer isOpen={open} onOpenChange={close}>
    <Drawer.Trigger aria-hidden="true" aria-label="Actor 管理抽屉" className="hidden">管理 Actor</Drawer.Trigger>
    <Drawer.Backdrop variant="blur"><Drawer.Content placement="right"><Drawer.Dialog aria-label="管理 Actor" className="flex h-full w-[min(500px,100vw)] flex-col bg-surface outline-none"><Drawer.Header className="border-b border-separator px-5 py-4"><Drawer.Heading>{actionVerb}{activeTarget ? currentSlot : ''} Actor</Drawer.Heading><p className="mt-1 type-meta text-muted">搜索、选择、实测和应用都在这里连续完成，关闭后也可恢复。</p></Drawer.Header><Drawer.Body className="min-h-0 flex-1 overflow-y-auto p-5">
      <ActorOpsV2WorkflowSteps plan={visiblePlan} />
      {differentSlot && <StatusNotice title="路线已有替换计划" status="warning">当前正在处理{currentSlot}槽位；同一路线一次只允许一个替换计划，请先完成或取消它。</StatusNotice>}
      {!visiblePlan ? <CandidateSelection
        targets={targets.length ? targets : target ? [target] : []}
        selectedTarget={activeTarget}
        systemCandidates={candidateList.systemCandidates}
        staticCandidates={candidateList.staticCandidates}
        sampleCandidates={candidateList.sampleCandidates}
        blockedCandidates={candidateList.blockedCandidates}
        mappingCandidates={candidateList.mappingCandidates}
        incompleteCount={candidateList.incompleteCount}
        loading={candidatesQuery.isLoading}
        selected={effectiveSelected}
        cap={cap}
        total={total}
        discovery={discoveryView}
        busy={actions.preview.isPending || actions.discovery.isPending || actions.metadata.isPending}
        onTarget={setSelectedTarget}
        onSelect={(candidate) => { setSelectionMode('manual'); setSelected(candidate) }}
        onPreview={() => effectiveSelected && actions.preview.mutate(effectiveSelected)}
        onDiscover={() => actions.discovery.mutate()}
        onMetadata={() => actions.metadata.mutate()}
      /> : <PlanStep
        plan={visiblePlan}
        slotLabel={currentSlot}
        busy={actions.authorize.isPending || actions.apply.isPending || actions.cancel.isPending || actions.revalidate.isPending}
        onAuthorize={() => actions.authorize.mutate()}
        onApply={() => actions.apply.mutate()}
        onCancel={() => actions.cancel.mutate()}
        onRevalidate={() => actions.revalidate.mutate()}
        onReset={() => { setDismissedPlanId(visiblePlan.plan_id); setPlan(null) }}
      />}
    </Drawer.Body></Drawer.Dialog></Drawer.Content></Drawer.Backdrop>
  </Drawer>
}

function replacementSlotState(
  plan: ActorOpsV2ReplacementPlan | null,
  target: ActorOpsV2ReplacementTarget | null,
): [string, boolean] {
  return [plan ? replacementSlotLabel(plan) : target?.slotLabel || 'Actor', Boolean(plan && target && !planMatchesTarget(plan, target))]
}

function replacementQueryKeys(userId: string, routeId: string) {
  return {
    candidateKey: queryKeys.actorOpsV2Candidates(userId, routeId),
    detailKey: queryKeys.actorOpsV2Route(userId, routeId),
  }
}

type ReplacementActionsOptions = {
  api: ReturnType<typeof useAppContext>['api']
  route: ActorOpsV2RouteView
  target: ActorOpsV2ReplacementTarget | null
  plan: ActorOpsV2ReplacementPlan | null
  cap: number
  total: number
  refresh: () => Promise<unknown>
  onUpdated: () => Promise<unknown>
  onPlan: (plan: ActorOpsV2ReplacementPlan) => void
  onDiscovery: (discoveryId: string) => void
  onApplied: () => void
}

function useReplacementActions({ api, route, target, plan, cap, total, refresh, onUpdated, onPlan, onDiscovery, onApplied }: ReplacementActionsOptions) {
  const refreshAll = () => { void refresh(); void onUpdated() }
  const acceptPlan = (value: unknown) => {
    const next = unwrapPlan(value)
    if (next) onPlan(next)
    refreshAll()
    return next
  }
  const preview = useMutation({
    mutationFn: (candidate: ActorOpsV2CandidateView) => {
      if (!target) throw new Error('replacement target is missing')
      return api.createActorOpsV2Replacement(route.route_id, {
        target_assignment: target.assignment,
        target_priority: target.priority,
        candidate_id: candidate.candidate_id,
        expected_route_generation: route.generation,
        expected_candidate_generation: candidate.generation,
        idempotency_key: crypto.randomUUID(),
        per_probe_cap_usd: cap,
        total_cap_usd: total,
      })
    },
    onSuccess: acceptPlan,
    onError: (error) => actionToast.danger(replacementRequestError(error, '未能创建替换计划。')),
  })
  const authorize = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error('replacement plan is missing')
      return api.authorizeActorOpsV2Replacement(route.route_id, plan.plan_id, { expected_generation: plan.generation, confirmation: '确认实测替换 Actor' })
    },
    onSuccess: (value) => { acceptPlan(value); actionToast.success('已授权串行实测', { description: '系统一次只会测试一个来源。' }) },
    onError: (error) => actionToast.danger(replacementRequestError(error, '未能授权实测。')),
  })
  const apply = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error('replacement plan is missing')
      return api.applyActorOpsV2Replacement(route.route_id, plan.plan_id, { expected_generation: plan.generation, confirmation: '确认替换 Actor' })
    },
    onSuccess: () => { refreshAll(); onApplied(); actionToast.success('已替换 Actor', { description: '旧 Actor 已转为未分配；历史运行与费用记录保持不变。' }) },
    onError: (error) => actionToast.danger(replacementRequestError(error, '替换条件已变化，请刷新后重试。')),
  })
  const cancel = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error('replacement plan is missing')
      return api.cancelActorOpsV2Replacement(route.route_id, plan.plan_id, { expected_generation: plan.generation })
    },
    onSuccess: (value) => { acceptPlan(value); actionToast.success('已取消替换计划') },
    onError: (error) => actionToast.danger(replacementRequestError(error, '未能取消替换计划。')),
  })
  const revalidate = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error('replacement plan is missing')
      return api.revalidateActorOpsV2Replacement(route.route_id, plan.plan_id, { expected_generation: plan.generation, idempotency_key: crypto.randomUUID() })
    },
    onSuccess: (value) => showRevalidationToast(acceptPlan(value)),
    onError: (error) => actionToast.danger(replacementRequestError(error, '历史 Dataset 未通过当前字段规则。')),
  })
  const discovery = useMutation({
    mutationFn: () => api.discoverActorOpsV2Candidates(route.route_id, { expected_route_generation: route.generation }),
    onSuccess: (value) => { onDiscovery(value.discovery_id); refreshAll(); actionToast.success('已开始搜索候选', { description: '进度会持续显示；搜索不会启动 Actor。' }) },
    onError: (error) => actionToast.danger(replacementRequestError(error, '未能开始免费搜索候选。')),
  })
  const metadata = useMutation({
    mutationFn: () => api.refreshActorOpsV2Metadata(route.route_id, { expected_route_generation: route.generation }),
    onSuccess: () => { void refresh(); actionToast.success('已排队更新商城信息') },
    onError: (error) => actionToast.danger(replacementRequestError(error, '未能更新商城信息。')),
  })
  return { preview, authorize, apply, cancel, revalidate, discovery, metadata }
}

function showRevalidationToast(plan: ActorOpsV2ReplacementPlan | null) {
  actionToast.success(plan?.status === 'ready' ? '历史结果重验通过' : '历史合同已重新确认', {
    description: plan?.status === 'ready'
      ? '没有启动新的 Actor，也没有新增 Actor 费用。'
      : '没有启动新的 Actor，也没有新增 Actor 费用；旧合同故障已解除，但没有可发布内容的来源仍需重新实测。',
  })
}

function replacementCaps(route: ActorOpsV2RouteView): [number, number] {
  const cap = Math.min(route.per_run_cap_usd, 0.20)
  return [cap, Math.min(0.60, cap * Math.max(1, route.binding_summary.ready_count))]
}

function useReplacementFailureNotice(
  plan: ActorOpsV2ReplacementPlan | null,
  userId: string,
  routeId: string,
  onUpdated: () => Promise<unknown>,
) {
  const queryClient = useQueryClient()
  const terminalNoticeKey = useRef('')
  useEffect(() => {
    if (plan?.status !== 'failed') return
    const noticeKey = `${plan.plan_id}:${plan.generation}`
    if (terminalNoticeKey.current === noticeKey) return
    terminalNoticeKey.current = noticeKey
    actionToast.danger('替换未完成', {
      description: `${replacementError(plan.error_code)} ${replacementFailureCostMessage(plan.error_code)}`,
    })
    void refreshReplacementDrawer(
      queryClient,
      queryKeys.actorOpsV2Candidates(userId, routeId),
      queryKeys.actorOpsV2Route(userId, routeId),
    )
    void onUpdated()
  }, [onUpdated, plan, queryClient, routeId, userId])
}

function refreshReplacementDrawer(
  queryClient: ReturnType<typeof useQueryClient>,
  candidateKey: ReturnType<typeof queryKeys.actorOpsV2Candidates>,
  detailKey: ReturnType<typeof queryKeys.actorOpsV2Route>,
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: candidateKey }),
    queryClient.invalidateQueries({ queryKey: detailKey }),
  ])
}

function CandidateSelection({ targets, selectedTarget, systemCandidates, staticCandidates, sampleCandidates, blockedCandidates, mappingCandidates, incompleteCount, loading, selected, cap, total, discovery, busy, onTarget, onSelect, onPreview, onDiscover, onMetadata }: {
  targets: ActorOpsV2ReplacementTarget[]; selectedTarget: ActorOpsV2ReplacementTarget | null
  systemCandidates: ActorOpsV2CandidateView[]; staticCandidates: ActorOpsV2CandidateView[]; sampleCandidates: ActorOpsV2CandidateView[]; blockedCandidates: ActorOpsV2CandidateView[]; mappingCandidates: ActorOpsV2CandidateView[]; incompleteCount: number; loading: boolean; selected: ActorOpsV2CandidateView | null
  cap: number; total: number; discovery: ActorOpsV2RouteDetail['discoveries'][number] | null; busy: boolean
  onTarget: (target: ActorOpsV2ReplacementTarget) => void; onSelect: (candidate: ActorOpsV2CandidateView) => void; onPreview: () => void; onDiscover: () => void; onMetadata: () => void
}) {
  const candidates = [...systemCandidates, ...staticCandidates, ...sampleCandidates]
  const recommendedId = candidates[0]?.candidate_id
  const discoveryActive = Boolean(discovery && ['queued', 'running', 'retry_wait'].includes(discovery.status))
  return <div className="grid gap-3">
    <TargetSelector targets={targets} selected={selectedTarget} onSelect={onTarget} />
    <p className="type-meta text-muted">每次实测最多 ${cap.toFixed(2)}；本计划总额最多 ${total.toFixed(2)}。只会串行测试当前选中的一个候选 Actor，不会自动换下一个。</p>
    <ActorOpsV2DiscoveryProgress discovery={discovery} />
    <div className="flex flex-wrap gap-2"><Button variant="secondary" isDisabled={busy || discoveryActive} onPress={onDiscover}>{discoveryActive ? '正在搜索候选…' : '搜索更多候选'}</Button><Button variant="ghost" isDisabled={busy} onPress={onMetadata}>更新商城信息</Button></div>
    {loading && <p className="type-meta text-muted">正在加载候选…</p>}
    {systemCandidates.length > 0 && <p className="type-control">系统可用</p>}
    {systemCandidates.map((candidate) => <ActorOpsV2CandidateCard key={candidate.candidate_id} candidate={candidate} selected={selected?.candidate_id === candidate.candidate_id} recommended={recommendedId === candidate.candidate_id} onSelect={onSelect} />)}
    {staticCandidates.length > 0 && <p className="type-control">可实测</p>}
    {staticCandidates.map((candidate) => <ActorOpsV2CandidateCard key={candidate.candidate_id} candidate={candidate} selected={selected?.candidate_id === candidate.candidate_id} recommended={recommendedId === candidate.candidate_id} onSelect={onSelect} />)}
    {sampleCandidates.length > 0 && <><p className="type-control">需要真实样本</p><p className="type-meta text-muted">授权后只启动一次 Actor；同一 Dataset 最多两轮自动映射，不会重复收费启动。</p></>}
    {sampleCandidates.map((candidate) => <ActorOpsV2CandidateCard key={candidate.candidate_id} candidate={candidate} selected={selected?.candidate_id === candidate.candidate_id} recommended={recommendedId === candidate.candidate_id} onSelect={onSelect} />)}
    {blockedCandidates.map((candidate) => <ActorOpsV2CandidateCard key={candidate.candidate_id} candidate={candidate} selected={false} onSelect={onSelect} disabled disabledReason={actorOpsV2CandidateIssueLabel(candidate) || '已确认故障'} />)}
    {mappingCandidates.map((candidate) => <ActorOpsV2CandidateCard key={candidate.candidate_id} candidate={candidate} selected={false} onSelect={onSelect} disabled disabledReason={actorOpsV2MappingIssueLabel(candidate) || '字段映射尚未完成'} />)}
    {incompleteCount > 0 && <p className="type-meta text-muted">另有 {incompleteCount} 个候选缺少可读的商城公开资料，更新商城信息后才能比较。</p>}
    {!loading && !candidates.length && <StatusNotice title="暂无可替换候选" status="warning">{mappingCandidates.length ? '已找到 Actor，但输入或输出合同仍有精确阻断；可查看每个候选的具体缺口。' : blockedCandidates.length ? '现有候选均已确认故障，请搜索新的候选。' : '先搜索候选；若候选已存在但缺少公开资料，再更新商城信息。'}</StatusNotice>}
    <Button isDisabled={!selectedTarget || !selected || busy || total <= 0} onPress={onPreview}>{busy ? '处理中…' : !selectedTarget ? '先选择替换位置' : '免费检查并准备实测'}</Button>
  </div>
}

function PlanStep({ plan, slotLabel, busy, onAuthorize, onApply, onCancel, onRevalidate, onReset }: {
  plan: ActorOpsV2ReplacementPlan; slotLabel: string; busy: boolean
  onAuthorize: () => void; onApply: () => void; onCancel: () => void; onRevalidate: () => void; onReset: () => void
}) {
  const progress = <ActorOpsV2ReplacementProgress plan={plan} />
  if (plan.status === 'ready') return <div className="grid gap-3">{progress}<p className="type-control">全部 {plan.binding_count} 条来源已通过，将把 {actorOpsV2CandidateLabel(plan.candidate)} 应用到{slotLabel}。</p><div className="flex justify-end gap-2"><Button variant="ghost" isDisabled={busy} onPress={onCancel}>取消计划</Button><Button isDisabled={busy} onPress={onApply}>{busy ? '应用中…' : `应用到${slotLabel}`}</Button></div></div>
  if (plan.status === 'previewed') return <div className="grid gap-3">{progress}<p className="type-control">免费预检已通过。实测将按来源串行进行，每个来源最多 ${plan.per_probe_cap_usd.toFixed(2)}，总额不超过 ${plan.total_cap_usd.toFixed(2)}。</p><div className="flex justify-end gap-2"><Button variant="ghost" isDisabled={busy} onPress={onCancel}>取消计划</Button><Button isDisabled={busy} onPress={onAuthorize}>{busy ? '启动中…' : `开始实测，最高 $${plan.total_cap_usd.toFixed(2)}`}</Button></div></div>
  if (plan.status === 'authorized' || plan.status === 'running') return <div className="grid gap-3">{progress}
    {plan.phase === 'dataset_revalidating' || plan.phase === 'dataset_adapting'
      ? <StatusNotice title="正在复用已付费 Dataset 重映射" status="info">本步骤只读取本次 Run 精确绑定的 Dataset，最多两轮字段修正；不会启动新的 Actor，也不会新增 Actor Run 费用。</StatusNotice>
      : plan.phase === 'cost_reconciliation'
        ? <StatusNotice title="正在核对费用事实" status="warning">费用最终确认前不会提交 Dataset 重验证据，也不会继续下一个付费调用。</StatusNotice>
        : <p className="type-control">正在按来源串行实测。出现未知远端结果时会停止后续付费调用，等待只读对账。</p>}
    <p className="type-meta text-muted">取消只会停止计划继续执行；已发起或待对账的运行、Dataset 与费用事实仍会保留。</p><Button variant="ghost" isDisabled={busy} onPress={onCancel}>取消替换计划</Button></div>
  if (plan.status === 'failed') return <div className="grid gap-3">{progress}<StatusNotice title="替换未完成" status="danger"><span>{replacementError(plan.error_code)}</span><span className="mt-1 block">{replacementFailureCostMessage(plan.error_code)}</span></StatusNotice>{REVALIDATABLE_ERRORS.has(plan.error_code || '') && <StatusNotice title="可以零费用重验" status="info">系统会只读原已结算 Dataset，并用当前字段规则重新核验；不会启动 Actor，也不会改写原费用记录。</StatusNotice>}<div className="flex flex-wrap gap-2">{REVALIDATABLE_ERRORS.has(plan.error_code || '') && <Button isDisabled={busy} onPress={onRevalidate}>{busy ? '重验中…' : '重新验证已有结果（$0 Actor 费）'}</Button>}<Button variant="secondary" isDisabled={busy} onPress={onReset}>重新选择候选</Button></div></div>
  return <div className="grid gap-3">{progress}<StatusNotice title="替换计划已取消" status="warning">未继续执行剩余步骤。</StatusNotice><Button variant="secondary" onPress={onReset}>重新选择候选</Button></div>
}

function TargetSelector({ targets, selected, onSelect }: {
  targets: ActorOpsV2ReplacementTarget[]
  selected: ActorOpsV2ReplacementTarget | null
  onSelect: (target: ActorOpsV2ReplacementTarget) => void
}) {
  return <section className="grid gap-2" aria-label="替换位置">
    <p className="type-control">1. 选择替换位置</p>
    <div className="flex flex-wrap gap-2">{targets.map((target) => <Button key={`${target.assignment}-${target.priority}`} size="sm" variant={selected?.assignment === target.assignment && selected.priority === target.priority ? 'secondary' : 'ghost'} aria-pressed={selected?.assignment === target.assignment && selected.priority === target.priority} onPress={() => onSelect(target)}>{target.candidate ? `替换${target.slotLabel}` : `补充${target.slotLabel}`}</Button>)}</div>
  </section>
}

function replacementCandidates(value: unknown) {
  const data = value as { candidates?: ActorOpsV2Candidate[] } | undefined
  const all = Array.isArray(data?.candidates) ? data.candidates : []
  const eligible = all.filter((item) => item.assignment === 'inactive' && item.store_metadata !== null)
  const identified = eligible.filter(actorOpsV2CandidateHasPublicIdentity)
  const selectable = identified.filter((item) => (item.probe_eligible ?? ['static_valid', 'probationary', 'certified'].includes(item.lifecycle)) && item.operational_status !== 'confirmed_failure')
  const systemCandidates = selectable.filter((item) => item.system_usable === true).sort(compareActorOpsV2ReplacementCandidates)
  const staticCandidates = selectable.filter((item) => !item.system_usable && (item.compatibility_stage === 'static_ready' || (!item.compatibility_stage && ['static_valid', 'probationary', 'certified'].includes(item.lifecycle)))).sort(compareActorOpsV2ReplacementCandidates)
  const sampleCandidates = selectable.filter((item) => item.compatibility_stage === 'sample_required').sort(compareActorOpsV2ReplacementCandidates)
  const selectedIds = new Set([...systemCandidates, ...staticCandidates, ...sampleCandidates].map((item) => item.candidate_id))
  const blockedCandidates = identified.filter((item) => item.operational_status === 'confirmed_failure').sort(compareActorOpsV2ReplacementCandidates)
  const mappingCandidates = identified.filter((item) => !selectedIds.has(item.candidate_id) && item.operational_status !== 'confirmed_failure' && item.mapping_issue_code !== null).sort(compareActorOpsV2ReplacementCandidates)
  return { systemCandidates, staticCandidates, sampleCandidates, blockedCandidates, mappingCandidates, incompleteCount: eligible.length - identified.length }
}

function latestDrawerPlan(detail: ActorOpsV2RouteDetail | undefined, target: ActorOpsV2ReplacementTarget | null, dismissedPlanId: string) {
  const plans = detail?.replacements || []
  const active = plans.find((item) => ACTIVE_PLAN_STATUSES.includes(item.status))
  if (active) return active
  return plans.find((item) => item.plan_id !== dismissedPlanId && item.status === 'failed' && REVALIDATABLE_ERRORS.has(item.error_code || '') && (!target || planMatchesTarget(item, target))) || null
}

function latestDiscovery(detail: ActorOpsV2RouteDetail | undefined, trackedId: string) {
  const discoveries = detail?.discoveries || []
  return discoveries.find((item) => item.discovery_id === trackedId)
    || discoveries.find((item) => ['queued', 'running', 'retry_wait'].includes(item.status))
    || discoveries[0]
    || null
}

function planMatchesTarget(plan: ActorOpsV2ReplacementPlan, target: ActorOpsV2ReplacementTarget) {
  return plan.target_assignment === target.assignment && plan.target_priority === target.priority
}

function replacementSlotLabel(plan: ActorOpsV2ReplacementPlan) {
  return plan.target_assignment === 'active' ? '主用' : `备用 ${plan.target_priority}`
}

function unwrapPlan(value: unknown) {
  const data = value as (ActorOpsV2ReplacementPlan & { plan?: ActorOpsV2ReplacementPlan }) | undefined
  if (data?.plan_id) return data
  return data?.plan?.plan_id ? data.plan : null
}
