import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Icons, Input, Label, Modal, Popover, TextField } from '../../design-system'
import { actorOpsV2CandidateLabel, type ActorOpsV2CandidateView, type ActorOpsV2RouteView } from './actorOpsV2RouteModel'
import { ActorOpsV2ReplacementDrawer } from './ActorOpsV2ReplacementDrawer'

export function ActorOpsV2RouteControls({ route }: { route: ActorOpsV2RouteView }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [candidate, setCandidate] = useState<ActorOpsV2CandidateView | null>(null)
  const [replaceOpen, setReplaceOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.actorOpsV2Routes(user.id) })
  const promote = useMutation({
    mutationFn: (target: ActorOpsV2CandidateView) => api.promoteActorOpsV2Candidate(route.route_id, target.candidate_id, { expected_route_generation: route.generation, expected_candidate_generation: target.generation, confirmation: '确认设为主用 Actor' }),
    onSuccess: () => { void refresh(); setCandidate(null); actionToast.success('已切换当前主用', { description: '没有启动 Actor，也没有产生费用。' }) },
    onError: (error) => { setCandidate(null); actionToast.danger(actionError(error, '未能切换主用，请刷新后重试。')) },
  })
  const reconcile = useMutation({
    mutationFn: () => api.reconcileActorOpsV2Bindings(route.route_id, { expected_route_generation: route.generation }),
    onSuccess: () => { void refresh(); actionToast.success('已完成来源检查', { description: '通过本地证据的来源已自动启用；不会抓取或启动 Actor。' }) },
    onError: (error) => actionToast.danger(actionError(error, '未能重新检查来源，请刷新后重试。')),
  })
  const metadata = useMutation({
    mutationFn: () => api.refreshActorOpsV2Metadata(route.route_id, { expected_route_generation: route.generation }),
    onSuccess: () => actionToast.success('已排队更新商城信息', { description: '仅读取 Apify 公开信息，不启动 Actor。' }),
    onError: (error) => actionToast.danger(actionError(error, '未能更新商城信息。')),
  })
  const discovery = useMutation({
    mutationFn: () => api.discoverActorOpsV2Candidates(route.route_id, { expected_route_generation: route.generation }),
    onSuccess: () => actionToast.success('已开始免费搜索候选', { description: '搜索不会启动 Actor 或产生费用。' }),
    onError: (error) => actionToast.danger(actionError(error, '未能开始免费搜索候选。')),
  })
  return <div className="flex items-center gap-1.5">
    <PriceCapControl route={route} onSaved={refresh} />
    <Popover isOpen={moreOpen} onOpenChange={setMoreOpen}>
      <Popover.Trigger<'button'> type="button" className="inline-flex size-8 items-center justify-center rounded-lg text-muted outline-none hover:bg-surface-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus" aria-label="Actor 路由更多操作"><Icons.MoreHorizontal size={17} aria-hidden="true" /></Popover.Trigger>
      <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-44 p-0">
        <Popover.Dialog aria-label="Actor 路由更多操作" className="grid gap-0.5 p-2">
          {route.standby_candidates.map((item) => <Button key={item.candidate_id} size="sm" variant="ghost" className="justify-start" onPress={() => { setMoreOpen(false); setCandidate(item) }}>设为主用</Button>)}
          {route.active_candidate && <Button size="sm" variant="ghost" className="justify-start" onPress={() => { setMoreOpen(false); setReplaceOpen(true) }}>替换主用 Actor</Button>}
          <Button size="sm" variant="ghost" className="justify-start" isDisabled={metadata.isPending} onPress={() => { setMoreOpen(false); metadata.mutate() }}>更新商城信息</Button>
          <Button size="sm" variant="ghost" className="justify-start" isDisabled={discovery.isPending} onPress={() => { setMoreOpen(false); discovery.mutate() }}>免费更新候选</Button>
          {route.binding_summary.pending_count > 0 && <Button size="sm" variant="ghost" className="justify-start" isDisabled={reconcile.isPending} onPress={() => { setMoreOpen(false); reconcile.mutate() }}>重新检查准备中的来源</Button>}
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
    <ConfirmDialog target={candidate} pending={promote.isPending} onClose={() => setCandidate(null)} onConfirm={() => candidate && promote.mutate(candidate)} />
    <ActorOpsV2ReplacementDrawer route={route} open={replaceOpen} onOpenChange={setReplaceOpen} onUpdated={refresh} />
  </div>
}

function PriceCapControl({ route, onSaved }: { route: ActorOpsV2RouteView; onSaved: () => Promise<unknown> }) {
  const { api } = useAppContext()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(route.per_run_cap_usd.toFixed(2))
  const [confirmation, setConfirmation] = useState('')
  const cap = Number(value)
  const raised = Number.isFinite(cap) && cap > route.per_run_cap_usd
  const update = useMutation({
    mutationFn: () => api.setActorOpsV2PriceCap(route.route_id, { expected_route_generation: route.generation, cap_usd: cap, ...(raised ? { confirmation: '确认提高 Actor 费用上限' as const } : {}) }),
    onSuccess: () => { void onSaved(); setOpen(false); actionToast.success('已更新单次费用上限') },
    onError: (error) => actionToast.danger(actionError(error, '未能更新费用上限。')),
  })
  return <Popover isOpen={open} onOpenChange={(next) => { setOpen(next); if (next) { setValue(route.per_run_cap_usd.toFixed(2)); setConfirmation('') } }}>
    <Popover.Trigger<'button'> type="button" className="rounded-lg px-2 py-1 type-meta text-muted outline-none hover:bg-surface-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus" aria-label="调整单次费用上限">调整</Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-[min(280px,calc(100vw-24px))] p-0">
      <Popover.Dialog aria-label="编辑 Actor 单次费用上限" className="grid gap-3 p-4"><Popover.Heading className="type-control">单次费用上限</Popover.Heading><p className="type-meta text-muted">商城标价只读；这里限制每次实际运行最多费用。</p><TextField value={value} onChange={setValue} isDisabled={update.isPending}><Label>美元（最高 $0.20）</Label><Input inputMode="decimal" /></TextField>{raised && <TextField value={confirmation} onChange={setConfirmation} isDisabled={update.isPending}><Label>输入“确认提高 Actor 费用上限”</Label><Input /></TextField>}<div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onPress={() => setOpen(false)}>取消</Button><Button size="sm" isDisabled={!Number.isFinite(cap) || cap <= 0 || cap > 0.20 || update.isPending || (raised && confirmation !== '确认提高 Actor 费用上限')} onPress={() => update.mutate()}>{update.isPending ? '保存中…' : '保存'}</Button></div></Popover.Dialog>
    </Popover.Content>
  </Popover>
}

function ConfirmDialog({ target, pending, onClose, onConfirm }: {
  target?: ActorOpsV2CandidateView | null; pending: boolean; onClose: () => void; onConfirm: () => void
}) {
  const [value, setValue] = useState('')
  const visible = Boolean(target)
  const expected = '确认设为主用 Actor'
  const title = '设为当前主用'
  const detail = `将 ${actorOpsV2CandidateLabel(target || null)} 设为主用；不会启动 Actor，也不会产生费用。`
  return visible ? <Modal isOpen onOpenChange={(next) => { if (!next && !pending) onClose() }}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">{title}</Modal.Trigger><Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}><Modal.Container><Modal.Dialog><Modal.Header><Modal.Heading>{title}</Modal.Heading></Modal.Header><Modal.Body><div className="grid gap-3"><p className="type-control">{detail}</p><TextField fullWidth value={value} onChange={setValue} isDisabled={pending}><Label>确认短语</Label><Input placeholder={expected} /></TextField></div></Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={onClose}>取消</Button><Button isDisabled={pending || value !== expected} onPress={onConfirm}>{pending ? '处理中…' : '确认'}</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal> : null
}

function actionError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback
  const labels: Record<string, string> = { actorops_v2_candidate_switch_conflict: '路线已更新，请刷新后再切换。', actorops_v2_binding_conflict: '路线已更新，请刷新后重新检查。', actorops_v2_price_cap_confirmation_required: '提高费用上限需要输入确认短语。', actorops_v2_unavailable: 'ActorOps v2 当前不可用。' }
  return labels[error.code] || fallback
}
