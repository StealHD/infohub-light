import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Drawer, Input, Label, TextField } from '../../design-system'
import { type ActorOpsV2RouteView } from './ActorOpsV2ControlPlane'
import { actorOpsV2CandidateLabel, actorOpsV2PriceLabel, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

type ReplacementPlan = {
  plan_id: string
  status: 'previewed' | 'authorized' | 'running' | 'ready' | 'applied' | 'failed' | 'cancelled'
  generation: number
  binding_count: number
  per_probe_cap_usd: number
  total_cap_usd: number
  error_code: string | null
  candidate: ActorOpsV2CandidateView
}

export function ActorOpsV2ReplacementDrawer({ route, open, onOpenChange, onUpdated }: {
  route: ActorOpsV2RouteView
  open: boolean
  onOpenChange: (open: boolean) => void
  onUpdated: () => Promise<unknown>
}) {
  const { api } = useAppContext()
  const [selected, setSelected] = useState<ActorOpsV2CandidateView | null>(null)
  const [plan, setPlan] = useState<ReplacementPlan | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const candidatesQuery = useQuery({ queryKey: ['actorops-v2-candidates', route.route_id], queryFn: ({ signal }) => api.actorOpsV2Candidates(route.route_id, signal), enabled: open, retry: false })
  const planQuery = useQuery({ queryKey: ['actorops-v2-replacement', route.route_id, plan?.plan_id], queryFn: ({ signal }) => api.actorOpsV2Replacement(route.route_id, plan?.plan_id || '', signal), enabled: open && Boolean(plan?.plan_id) && ['authorized', 'running'].includes(plan?.status || ''), retry: false, refetchInterval: 3_000 })
  const visiblePlan = unwrapPlan(planQuery.data) || plan
  const candidates = useMemo(() => {
    const values = unwrapCandidates(candidatesQuery.data)
    return values.filter((item) => item.assignment === 'inactive' && item.store_metadata !== null && ['static_valid', 'probationary', 'certified'].includes(item.lifecycle)).sort((left, right) => {
      const leftReady = left.evidence_progress.verified_bindings >= left.evidence_progress.required_bindings ? 0 : 1
      const rightReady = right.evidence_progress.verified_bindings >= right.evidence_progress.required_bindings ? 0 : 1
      return leftReady - rightReady || actorOpsV2CandidateLabel(left).localeCompare(actorOpsV2CandidateLabel(right), 'zh-CN')
    })
  }, [candidatesQuery.data])
  const cap = Math.min(route.per_run_cap_usd, 0.20)
  const total = Math.min(0.60, cap * Math.max(1, route.binding_summary.ready_count))
  const preview = useMutation({
    mutationFn: (candidate: ActorOpsV2CandidateView) => api.createActorOpsV2Replacement(route.route_id, { target_assignment: 'active', target_priority: 0, candidate_id: candidate.candidate_id, expected_route_generation: route.route_generation, expected_candidate_generation: candidate.generation, idempotency_key: crypto.randomUUID(), per_probe_cap_usd: cap, total_cap_usd: total }),
    onSuccess: (value) => { const next = unwrapPlan(value); if (next) setPlan(next) },
    onError: (error) => actionToast.danger(errorMessage(error, '未能创建替换计划。')),
  })
  const authorize = useMutation({
    mutationFn: () => api.authorizeActorOpsV2Replacement(route.route_id, plan?.plan_id || '', { expected_generation: plan?.generation || 0, confirmation: '确认实测替换 Actor' }),
    onSuccess: (value) => { const next = unwrapPlan(value); if (next) setPlan(next); actionToast.success('已授权串行实测', { description: '系统一次只会测试一个来源。' }) },
    onError: (error) => actionToast.danger(errorMessage(error, '未能授权实测。')),
  })
  const apply = useMutation({
    mutationFn: () => api.applyActorOpsV2Replacement(route.route_id, plan?.plan_id || '', { expected_generation: plan?.generation || 0, confirmation: '确认替换 Actor' }),
    onSuccess: () => { void onUpdated(); onOpenChange(false); actionToast.success('已替换主用 Actor', { description: '没有产生新的网络调用或费用。' }) },
    onError: (error) => actionToast.danger(errorMessage(error, '替换条件已变化，请刷新后重试。')),
  })
  const close = (next: boolean) => {
    onOpenChange(next)
    if (!next) { setSelected(null); setPlan(null); setConfirmation('') }
  }
  return <Drawer isOpen={open} onOpenChange={close}>
    <Drawer.Trigger aria-hidden="true" className="hidden">替换 Actor</Drawer.Trigger>
    <Drawer.Backdrop variant="blur"><Drawer.Content placement="right"><Drawer.Dialog aria-label="替换 Actor" className="flex h-full w-[min(460px,100vw)] flex-col bg-surface outline-none"><Drawer.Header className="border-b border-separator px-5 py-4"><Drawer.Heading>替换主用 Actor</Drawer.Heading><p className="mt-1 type-meta text-muted">先免费比较候选；选定一个后才会要求授权实测。</p></Drawer.Header><Drawer.Body className="min-h-0 flex-1 overflow-y-auto p-5">
      {!visiblePlan ? <div className="grid gap-3"><p className="type-meta text-muted">每次实测最多 ${cap.toFixed(2)}；本计划总额最多 ${total.toFixed(2)}。只会串行测试当前选中的一个 Candidate，不会自动换下一个。</p>{candidatesQuery.isLoading && <p className="type-meta text-muted">正在加载候选…</p>}{candidates.map((candidate) => <button key={candidate.candidate_id} type="button" onClick={() => setSelected(candidate)} className={`grid gap-1 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:outline-2 focus-visible:outline-focus ${selected?.candidate_id === candidate.candidate_id ? 'border-focus bg-surface-secondary' : 'border-separator hover:bg-surface-secondary'}`}><span className="type-control">{actorOpsV2CandidateLabel(candidate)}</span><span className="type-meta text-muted">{actorOpsV2PriceLabel(candidate)} · 已核验 {candidate.evidence_progress.verified_bindings}/{candidate.evidence_progress.required_bindings}</span></button>)}{!candidatesQuery.isLoading && !candidates.length && <p className="type-meta text-muted">没有可替换的已映射 Candidate。请先在更多菜单免费更新候选。</p>}<Button isDisabled={!selected || preview.isPending || total <= 0} onPress={() => selected && preview.mutate(selected)}>{preview.isPending ? '创建中…' : '创建实测计划'}</Button></div> : <PlanStep plan={visiblePlan} confirmation={confirmation} setConfirmation={setConfirmation} busy={authorize.isPending || apply.isPending} onAuthorize={() => authorize.mutate()} onApply={() => apply.mutate()} />}
    </Drawer.Body></Drawer.Dialog></Drawer.Content></Drawer.Backdrop>
  </Drawer>
}

function PlanStep({ plan, confirmation, setConfirmation, busy, onAuthorize, onApply }: { plan: ReplacementPlan; confirmation: string; setConfirmation: (value: string) => void; busy: boolean; onAuthorize: () => void; onApply: () => void }) {
  if (plan.status === 'ready') return <div className="grid gap-3"><p className="type-control">{actorOpsV2CandidateLabel(plan.candidate)} 已通过全部 {plan.binding_count} 条来源的实测，费用已结算。</p><ConfirmField expected="确认替换 Actor" value={confirmation} onChange={setConfirmation} /><Button isDisabled={busy || confirmation !== '确认替换 Actor'} onPress={onApply}>{busy ? '替换中…' : '确认替换'}</Button></div>
  if (plan.status === 'previewed') return <div className="grid gap-3"><p className="type-control">将实测 {actorOpsV2CandidateLabel(plan.candidate)}。最多 ${plan.per_probe_cap_usd.toFixed(2)} / 来源，总额不超过 ${plan.total_cap_usd.toFixed(2)}。</p><ConfirmField expected="确认实测替换 Actor" value={confirmation} onChange={setConfirmation} /><Button isDisabled={busy || confirmation !== '确认实测替换 Actor'} onPress={onAuthorize}>{busy ? '授权中…' : '确认并开始实测'}</Button></div>
  if (plan.status === 'authorized' || plan.status === 'running') return <p className="type-control">正在按来源串行实测。出现未知远端结果时会停止后续付费调用，等待只读对账。</p>
  return <p className="type-control">{plan.status === 'failed' ? replacementError(plan.error_code) : '该替换计划已结束。'}</p>
}

function ConfirmField({ expected, value, onChange }: { expected: string; value: string; onChange: (value: string) => void }) {
  return <TextField value={value} onChange={onChange}><Label>确认短语</Label><Input placeholder={expected} /></TextField>
}

function unwrapCandidates(value: unknown) {
  const data = value as { candidates?: ActorOpsV2CandidateView[] } | undefined
  return Array.isArray(data?.candidates) ? data.candidates : []
}

function unwrapPlan(value: unknown) {
  const data = value as ReplacementPlan | undefined
  return data?.plan_id ? data : null
}

function replacementError(code: string | null) {
  const labels: Record<string, string> = { actorops_replacement_contract_mismatch: '返回内容无法安全映射为目标账号的更新，已停止这个 Candidate。', actorops_replacement_no_evidence: '没有取得可证明的更新内容，未自动测试其他 Candidate。', actorops_replacement_plan_stale: '来源、价格或槽位已变化，请重新创建计划。', actorops_replacement_credential_unavailable: '当前没有可用凭据，Candidate 没有被惩罚。' }
  return labels[code || ''] || '替换计划未通过；没有自动测试其他 Candidate。'
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) return replacementError(error.code) === '替换计划未通过；没有自动测试其他 Candidate。' ? fallback : replacementError(error.code)
  return fallback
}
