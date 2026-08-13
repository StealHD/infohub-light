import { useRef, useState } from 'react'

import type { ApifyActorRouteDetail, ApifyActorSlotName } from '../../api/types'
import { Button, Input, Label, Modal, StatusIndicator, TextField } from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'

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

export function ActorOpsPoolSlots({
  detail, pending, onOperation, onRemove,
}: {
  detail: ApifyActorRouteDetail
  pending: boolean
  onOperation: (goal: 'add_slot' | 'replace_slot', slot: ApifyActorSlotName) => void
  onRemove: (target: ActorOpsPoolTarget, trigger: HTMLButtonElement | null) => void
}) {
  return <ol className="grid gap-3 min-[768px]:grid-cols-3" aria-label="当前 Actor 主备槽位">
    {order.map((name) => {
      const slot = detail.slots.find((item) => item.slot === name)
      const revision = slot?.revision
      const actions = slot?.actions
      const status = slotStatus(slot)
      return <PoolSlot
        key={name} name={name} revision={revision} actions={actions} status={status} pending={pending}
        onOperation={onOperation} onRemove={onRemove}
      />
    })}
  </ol>
}

function PoolSlot({ name, revision, actions, status, pending, onOperation, onRemove }: {
  name: ApifyActorSlotName
  revision: ApifyActorRouteDetail['slots'][number]['revision']
  actions: ApifyActorRouteDetail['slots'][number]['actions']
  status: ReturnType<typeof slotStatus>
  pending: boolean
  onOperation: (goal: 'add_slot' | 'replace_slot', slot: ApifyActorSlotName) => void
  onRemove: (target: ActorOpsPoolTarget, trigger: HTMLButtonElement | null) => void
}) {
  const removeRef = useRef<HTMLButtonElement | null>(null)
  const reason = !revision ? actions?.add_reason : actions?.replace_reason || actions?.remove_reason
  return <li className="min-w-0 rounded-control border border-separator bg-default p-3">
    <div className="flex items-center justify-between gap-2"><span className="type-control">{labels[name]}</span><StatusIndicator label={status.label} tone={status.tone} /></div>
    <p className="type-control mt-3 break-words">{revision?.actor_public_name || (revision ? `${revision.publisher} Actor` : '当前为空')}</p>
    <p className="type-meta mt-1 break-words text-muted">{revision ? `发布者 ${revision.publisher} · ${status.note}` : status.note}</p>
    <div className="mt-3 flex flex-wrap gap-2">
      {!revision && <Button size="sm" variant="secondary" isDisabled={!actions?.add || pending} onPress={() => onOperation('add_slot', name)}>添加 Actor</Button>}
      {revision && <Button size="sm" variant="secondary" isDisabled={!actions?.replace || pending} onPress={() => onOperation('replace_slot', name)}>替换</Button>}
      {revision && <Button ref={removeRef} size="sm" variant="ghost" isDisabled={!actions?.remove || pending} onPress={() => onRemove({ slot: name, label: revision.actor_public_name || `${revision.publisher} Actor` }, removeRef.current)}>移出主备池</Button>}
    </div>
    {reason && <p className="mt-2 type-meta text-muted">{unavailable(reason)}</p>}
  </li>
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
