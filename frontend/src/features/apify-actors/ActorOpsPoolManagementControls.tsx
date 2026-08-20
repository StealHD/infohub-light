import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { ApifyActorRouteDetail, ApifyActorSlotName } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Input, Label, Modal, StatusIndicator, TextField } from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'

export { ActorStoreQuality } from './ActorOpsCandidateQuality'

const order: ApifyActorSlotName[] = ['primary', 'backup_1', 'backup_2']
const labels: Record<ApifyActorSlotName, string> = {
  primary: '主用', backup_1: '备用 1', backup_2: '备用 2',
}

function unavailable(reason: string | null | undefined): string {
  const values: Record<string, string> = {
    target_slot_required: '需要重新选择安全槽位', apify_start_outcome_unknown: '存在未确认的 Actor 启动结果',
    pool_stage_active: '当前有未完成的主备变更', actor_attempt_active: '当前有运行中的 Actor 尝试',
    freshness_active: '当前有运行中的新鲜度检查', pool_full: '主备池已满',
    add_requires_first_empty_slot: '只能填入第一个空槽', pool_runtime_minimum_incomplete: '现有主备尚未达到路线最低门槛',
    replace_requires_occupied_slot: '只能替换已占用的槽位', slot_empty: '该槽位为空',
    pool_publisher_minimum: '移出后无法满足发布者最低门槛', pool_runtime_minimum: '移出后无法满足路线最低门槛',
  }
  return values[reason || ''] || '当前操作暂不可用'
}

function slotStatus(slot: ApifyActorRouteDetail['slots'][number] | undefined) {
  const revision = slot?.revision
  const lifecycle = revision?.lifecycle || slot?.validation_status || 'unconfigured'
  const slotName = slot?.slot || 'backup_2'
  if (revision && !slot?.runnable) return {
    label: '需要处理', tone: 'danger', note: '当前不会参与新的运行；请先核对故障或旧数据状态',
  } as const
  if (lifecycle === 'probationary') return {
    label: slotName === 'primary' ? '运行中' : '备用可用', tone: 'success',
    note: '已验证，可运行；系统会继续观察稳定性，无需手动转正',
  } as const
  if (lifecycle === 'certified') return {
    label: slotName === 'primary' ? '运行中' : '备用可用', tone: 'success',
    note: slotName === 'primary' ? '当前主用 Actor' : '故障时自动切换',
  } as const
  if (lifecycle === 'legacy_builtin') return {
    label: '兼容版本', tone: 'warning', note: '当前仍可运行；可在旁路完成升级',
  } as const
  if (revision && ['quarantined', 'rejected'].includes(lifecycle)) return {
    label: '需要处理', tone: 'danger', note: '当前不会参与新的运行',
  } as const
  return {
    label: lifecycle === 'unconfigured' ? '空缺' : '需要处理',
    tone: lifecycle === 'unconfigured' ? 'neutral' : 'warning',
    note: lifecycle === 'unconfigured' ? '当前不参与运行，也不产生费用' : '尚未完成实际验证',
  } as const
}

export type ActorOpsPoolTarget = { slot: ApifyActorSlotName; label: string }
type ActorOpsPrimaryTarget = { slot: Exclude<ApifyActorSlotName, 'primary'>; label: string }

export function ActorOpsPoolSlots({
  detail, pending, onOperation, onRemove,
}: {
  detail: ApifyActorRouteDetail
  pending: boolean
  onOperation: (goal: 'add_slot' | 'replace_slot', slot: ApifyActorSlotName, trigger: HTMLButtonElement | null) => void
  onRemove: (target: ActorOpsPoolTarget, trigger: HTMLButtonElement | null) => void
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [primaryTarget, setPrimaryTarget] = useState<ActorOpsPrimaryTarget | null>(null)
  const primaryTriggerRef = useRef<HTMLButtonElement | null>(null)
  const promote = useMutation({
    mutationFn: (target: ActorOpsPrimaryTarget) => api.promoteApifyActorRouteActivePoolSlot(detail.route_id, {
      target_slot: target.slot,
      expected_generation: detail.generation,
      confirmation: '确认设为主用 Actor',
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      setPrimaryTarget(null)
      window.requestAnimationFrame(() => primaryTriggerRef.current?.focus())
      actionToast.success('已设为当前主用 Actor', { description: '没有启动 Actor，也没有产生费用。' })
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.code === 'apify_actor_route_generation_conflict') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoute(user.id, detail.route_id) })
      }
      setPrimaryTarget(null)
      window.requestAnimationFrame(() => primaryTriggerRef.current?.focus())
      actionToast.danger('未能切换主用 Actor')
    },
  })
  const operationPending = pending || promote.isPending
  return <>
    <ol className="grid gap-3 min-[768px]:grid-cols-3" aria-label="当前 Actor 主备槽位">
    {order.map((name) => {
      const slot = detail.slots.find((item) => item.slot === name)
      const revision = slot?.revision
      const actions = slot?.actions
      const status = slotStatus(slot)
      return <PoolSlot
        key={name} name={name} revision={revision} actions={actions} status={status} pending={operationPending}
        onOperation={onOperation} onRemove={onRemove}
        onPromote={(target, trigger) => { primaryTriggerRef.current = trigger; setPrimaryTarget(target) }}
      />
    })}
    </ol>
    <p className="type-meta text-muted">主用/备用是配置优先级；自动切备不会重排槽位，各来源可使用不同的实际 Actor。</p>
    <ActorOpsRoutePriceCap key={`${detail.route_id}:${detail.generation}:${detail.per_run_cap_usd}`} detail={detail} pending={operationPending} />
    <ActorOpsPromotePrimaryDialog
      target={primaryTarget}
      pending={promote.isPending}
      onClose={() => { setPrimaryTarget(null); window.requestAnimationFrame(() => primaryTriggerRef.current?.focus()) }}
      onConfirm={() => primaryTarget && promote.mutate(primaryTarget)}
    />
  </>
}

function PoolSlot({ name, revision, actions, status, pending, onOperation, onRemove, onPromote }: {
  name: ApifyActorSlotName
  revision: ApifyActorRouteDetail['slots'][number]['revision']
  actions: ApifyActorRouteDetail['slots'][number]['actions']
  status: ReturnType<typeof slotStatus>
  pending: boolean
  onOperation: (goal: 'add_slot' | 'replace_slot', slot: ApifyActorSlotName, trigger: HTMLButtonElement | null) => void
  onRemove: (target: ActorOpsPoolTarget, trigger: HTMLButtonElement | null) => void
  onPromote: (target: ActorOpsPrimaryTarget, trigger: HTMLButtonElement | null) => void
}) {
  const removeRef = useRef<HTMLButtonElement | null>(null)
  const promoteRef = useRef<HTMLButtonElement | null>(null)
  const operationRef = useRef<HTMLButtonElement | null>(null)
  const reason = !revision ? actions?.add_reason : actions?.replace_reason || actions?.promote_reason || actions?.remove_reason
  return <li data-actorops-slot={name} className="min-w-0 rounded-control border border-separator bg-default p-3">
    <div className="flex items-center justify-between gap-2"><span className="type-control">{labels[name]}</span><StatusIndicator label={status.label} tone={status.tone} /></div>
    <p className="type-control mt-3 break-words">{revision?.actor_public_name || (revision ? `${revision.publisher} Actor` : '当前为空')}</p>
    <p className="type-meta mt-1 break-words text-muted">{revision ? `发布者 ${revision.publisher} · ${status.note}` : status.note}</p>
    <div className="mt-3 flex flex-wrap gap-2">
      {!revision && <Button ref={operationRef} size="sm" variant="secondary" isDisabled={!actions?.add || pending} onPress={() => onOperation('add_slot', name, operationRef.current)}>添加 Actor</Button>}
      {revision && <Button ref={operationRef} size="sm" variant="secondary" isDisabled={!actions?.replace || pending} onPress={() => onOperation('replace_slot', name, operationRef.current)}>替换</Button>}
      {revision && name !== 'primary' && <Button ref={promoteRef} size="sm" variant="secondary" isDisabled={!actions?.promote || pending} onPress={() => onPromote({ slot: name, label: revision.actor_public_name || `${revision.publisher} Actor` }, promoteRef.current)}>设为主用</Button>}
      {revision && <Button ref={removeRef} size="sm" variant="ghost" isDisabled={!actions?.remove || pending} onPress={() => onRemove({ slot: name, label: revision.actor_public_name || `${revision.publisher} Actor` }, removeRef.current)}>移出主备池</Button>}
    </div>
    {reason && <p className="mt-2 type-meta text-muted">{unavailable(reason)}</p>}
  </li>
}

function ActorOpsRoutePriceCap({ detail, pending }: { detail: ApifyActorRouteDetail; pending: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(String(detail.per_run_cap_usd))
  const cap = Number(draft)
  const valid = Number.isFinite(cap) && cap > 0 && cap <= 0.10
  const changed = valid && Math.abs(cap - detail.per_run_cap_usd) > 1e-9
  const update = useMutation({
    mutationFn: () => api.setApifyActorRoutePriceCap(detail.route_id, {
      expected_generation: detail.generation,
      per_run_cap_usd: cap,
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.apifyActorRoute(user.id, updated.route_id), updated)
      void queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
      actionToast.success('单次费用上限已更新', { description: '只影响之后由你确认的 Actor 运行。' })
    },
    onError: () => actionToast.danger('费用上限未更新，请刷新后重试。'),
  })
  return <div className="mt-3 flex flex-col gap-2 rounded-control border border-separator bg-default p-3 min-[640px]:flex-row min-[640px]:items-end">
    <TextField fullWidth value={draft} onChange={setDraft} isDisabled={pending || update.isPending} isInvalid={Boolean(draft) && !valid}>
      <Label>单次 Actor 费用上限（USD）</Label><Input type="number" min={0.000001} max={0.10} step={0.005} />
      <p className="mt-1 type-meta text-muted">候选先按安全规则筛选；此上限最高 $0.10，不会自动运行。</p>
    </TextField>
    <Button size="sm" isDisabled={pending || update.isPending || !changed} onPress={() => update.mutate()}>{update.isPending ? '保存中…' : '保存上限'}</Button>
  </div>
}

function ActorOpsPromotePrimaryDialog({ target, pending, onClose, onConfirm }: {
  target: ActorOpsPrimaryTarget | null
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  return target
    ? <ActorOpsPromotePrimaryDialogContent key={target.slot} target={target} pending={pending} onClose={onClose} onConfirm={onConfirm} />
    : null
}

function ActorOpsPromotePrimaryDialogContent({ target, pending, onClose, onConfirm }: {
  target: ActorOpsPrimaryTarget
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const [confirmation, setConfirmation] = useState('')
  return <Modal isOpen onOpenChange={(open) => { if (!open && !pending) onClose() }}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">设为主用 Actor</Modal.Trigger>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}><Modal.Container><Modal.Dialog>
      <Modal.Header><Modal.Heading>设为当前主用 Actor</Modal.Heading></Modal.Header>
      <Modal.Body><div className="grid gap-3" aria-busy={pending}>
        <HeroNotice title="不收费，只调整当前主备顺序" status="warning" role="status">将把 {target.label} 设为主用，原主用会移动到对应备用槽。Actor、Revision、来源认证和费用历史都不变。</HeroNotice>
        <TextField fullWidth value={confirmation} onChange={setConfirmation} isDisabled={pending}><Label>确认短语</Label><Input placeholder="确认设为主用 Actor" /><p className="mt-1 type-meta text-muted">输入“确认设为主用 Actor”后才会提交。</p></TextField>
      </div></Modal.Body>
      <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => { setConfirmation(''); onClose() }}>取消</Button><Button isDisabled={pending || confirmation !== '确认设为主用 Actor'} onPress={onConfirm}>{pending ? '切换中…' : '确认设为主用'}</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}

export function ActorOpsRemovePoolDialog({ target, pending, onClose, onConfirm }: {
  target: ActorOpsPoolTarget | null
  pending: boolean
  onClose: () => void
  onConfirm: (target: ActorOpsPoolTarget) => void
}) {
  return target
    ? <ActorOpsRemovePoolDialogContent key={target.slot} target={target} pending={pending} onClose={onClose} onConfirm={onConfirm} />
    : null
}

function ActorOpsRemovePoolDialogContent({ target, pending, onClose, onConfirm }: {
  target: ActorOpsPoolTarget
  pending: boolean
  onClose: () => void
  onConfirm: (target: ActorOpsPoolTarget) => void
}) {
  const [confirmation, setConfirmation] = useState('')
  const slotsAfterRemoval = order
    .filter((slot) => slot !== target.slot)
    .map((slot) => labels[slot])
  return <Modal isOpen onOpenChange={(open) => {
    if (!open && !pending) {
      setConfirmation('')
      onClose()
    }
  }}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">确认移出 Actor</Modal.Trigger>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}><Modal.Container><Modal.Dialog>
      <Modal.Header><Modal.Heading>移出主备池</Modal.Heading></Modal.Header>
      <Modal.Body><div className="grid gap-3" aria-busy={pending}>
        <HeroNotice title="不收费，历史与认证证据会保留" status="warning" role="status">将移出 {target.label}。不会启动 Actor 或删除 Revision、Canary、费用与审计历史。</HeroNotice>
        <p className="type-meta text-muted">压紧后顺序：{slotsAfterRemoval.length ? slotsAfterRemoval.join(' → ') : '空池'}。只有没有运行中尝试、Freshness 或未完成验证阶段时才能确认移出。</p>
        <TextField fullWidth value={confirmation} onChange={setConfirmation} isDisabled={pending}><Label>确认短语</Label><Input placeholder="确认移出 Actor 主备池" /><p className="type-meta mt-1 text-muted">输入“确认移出 Actor 主备池”后才会提交。</p></TextField>
      </div></Modal.Body>
      <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => { setConfirmation(''); onClose() }}>取消</Button><Button isDisabled={pending || confirmation !== '确认移出 Actor 主备池'} onPress={() => onConfirm(target)}>{pending ? '正在移出…' : '确认移出主备池'}</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}
