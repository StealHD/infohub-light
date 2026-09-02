import { useRef, useState } from 'react'

import type { NotificationService } from '../../api/types'
import { Button, Icons, Popover, Separator, StableAsyncButton } from '../../design-system'

type PendingAction = 'test' | 'resume' | 'pause'

export function NotificationServiceActions({ service, busy, admin, onTestAndEnable, onResume, onPause, onEdit, onArchive }: {
  service: NotificationService
  busy: boolean
  admin: boolean
  onTestAndEnable: (service: NotificationService) => Promise<void>
  onResume: (service: NotificationService) => Promise<void>
  onPause: (service: NotificationService) => Promise<void>
  onEdit: (service: NotificationService) => void
  onArchive: (service: NotificationService, trigger: HTMLButtonElement | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const canManageShared = admin && !service.legacy_private
  const canManage = canManageShared || (service.legacy_private && service.can_edit)
  const canResume = Boolean(!service.enabled && service.can_enable && service.transport_ready)
  if (!canManage) return null

  async function chooseAsync(action: PendingAction, request: () => Promise<void>) {
    if (busy || pendingAction) return
    setPendingAction(action)
    try { await request() } finally {
      setPendingAction(null)
      setOpen(false)
      window.requestAnimationFrame(() => triggerRef.current?.focus())
    }
  }

  function choose(action: () => void) {
    if (busy || pendingAction) return
    setOpen(false)
    action()
  }

  const locked = busy || Boolean(pendingAction)
  const hasPrimaryAction = Boolean((canManageShared && !service.available && !canResume) || canResume || service.enabled || canManageShared)
  return <Popover isOpen={open} onOpenChange={(next) => { if (next || !pendingAction) setOpen(next) }}>
    <Popover.Trigger<'button'> ref={triggerRef} aria-label={`更多操作：${service.name}`} className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11" render={(props) => <button {...props} type="button" disabled={locked} />}><Icons.MoreHorizontal size={17} aria-hidden="true" /></Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-44 p-0">
      <Popover.Dialog aria-label={`${service.name} 通知服务操作`} className="grid gap-0.5 p-2">
        {canManageShared && !service.available && !canResume && <StableAsyncButton variant="ghost" className="w-full justify-start" isDisabled={!service.can_validate || locked} pending={pendingAction === 'test'} pendingContent={<><Icons.Send size={15} aria-hidden="true" />测试中…</>} onPress={() => chooseAsync('test', () => onTestAndEnable(service))}><Icons.Send size={15} aria-hidden="true" />{service.enabled ? '测试并恢复' : '测试并启用'}</StableAsyncButton>}
        {canResume && <StableAsyncButton variant="ghost" className="w-full justify-start" isDisabled={locked} pending={pendingAction === 'resume'} pendingContent={<><Icons.Play size={15} aria-hidden="true" />启用中…</>} onPress={() => chooseAsync('resume', () => onResume(service))}><Icons.Play size={15} aria-hidden="true" />启用</StableAsyncButton>}
        {service.enabled && <StableAsyncButton variant="ghost" className="w-full justify-start" isDisabled={locked} pending={pendingAction === 'pause'} pendingContent={<><Icons.Pause size={15} aria-hidden="true" />暂停中…</>} onPress={() => chooseAsync('pause', () => onPause(service))}><Icons.Pause size={15} aria-hidden="true" />暂停</StableAsyncButton>}
        {canManageShared && <Button variant="ghost" className="w-full justify-start" isDisabled={locked} onPress={() => choose(() => onEdit(service))}><Icons.Pencil size={15} aria-hidden="true" />编辑</Button>}
        {hasPrimaryAction && <Separator className="my-1" />}
        <Button variant="ghost" className="w-full justify-start text-danger" isDisabled={locked} onPress={() => choose(() => onArchive(service, triggerRef.current))}><Icons.Archive size={15} aria-hidden="true" />归档</Button>
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}
