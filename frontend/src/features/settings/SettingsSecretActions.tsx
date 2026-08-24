import { useId, useRef, useState, type FormEvent } from 'react'

import type { SecretRef } from '../../api/types'
import { useActionFeedback } from '../../app/ActionFeedback'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Icons, Input, Label, Modal, Popover, StatusNotice, TextField } from '../../design-system'
import { secretActionError } from './settingsSecretsModel'

export function SecretActions({ secret, lifecycleLocked = false, lifecycleDescription = '请先安全排空，再轮换或删除。', compact = false, onChanged }: {
  secret: SecretRef
  lifecycleLocked?: boolean
  lifecycleDescription?: string
  compact?: boolean
  onChanged: (secretId: string, action: 'rotate' | 'delete' | 'connection') => void
}) {
  const { api } = useAppContext()
  const feedback = useActionFeedback()
  const [rotateOpen, setRotateOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [value, setValue] = useState('')
  const [rotateError, setRotateError] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const moreTriggerRef = useRef<HTMLButtonElement>(null)
  const rotateTriggerRef = useRef<HTMLButtonElement>(null)
  const deleteTriggerRef = useRef<HTMLButtonElement>(null)
  const lifecycleDescriptionId = useId()
  const rotating = feedback.isPending('secret-rotate', secret.id)
  const removing = feedback.isPending('secret-delete', secret.id)

  function closeRotate() {
    setRotateOpen(false)
    setRotateError('')
    setValue('')
    queueMicrotask(() => (compact ? moreTriggerRef.current : rotateTriggerRef.current)?.focus())
  }

  function closeDelete() {
    setDeleteOpen(false)
    setDeleteError('')
    queueMicrotask(() => (compact ? moreTriggerRef.current : deleteTriggerRef.current)?.focus())
  }

  async function rotate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitted = value
    setValue('')
    setRotateError('')
    if (!submitted) {
      setRotateError('新 Key 值不能为空。')
      return
    }
    feedback.begin('secret-rotate', secret.id)
    try {
      await api.rotateSecret(secret.id, submitted)
      feedback.succeed('secret-rotate', secret.id, `${secret.name} 已轮换。`)
      closeRotate()
      actionToast.success('Key 已轮换', { description: secret.name })
      onChanged(secret.id, 'rotate')
    } catch (caught) {
      const message = secretActionError(caught, '轮换失败，请稍后重试。')
      setRotateError(message)
      feedback.fail('secret-rotate', secret.id, message)
    }
  }

  async function remove() {
    setDeleteError('')
    feedback.begin('secret-delete', secret.id)
    try {
      await api.deleteSecret(secret.id)
      feedback.succeed('secret-delete', secret.id, `${secret.name} 已删除。`)
      closeDelete()
      actionToast.success('Key 已删除', { description: secret.name })
      onChanged(secret.id, 'delete')
    } catch (caught) {
      const message = secretActionError(caught, '删除失败。')
      setDeleteError(message)
      feedback.fail('secret-delete', secret.id, message)
    }
  }

  const rotateControl = <Button ref={rotateTriggerRef} size="sm" variant="ghost" className={compact ? 'w-full justify-start' : undefined} isDisabled={lifecycleLocked} aria-describedby={lifecycleLocked ? lifecycleDescriptionId : undefined} aria-label={`轮换 ${secret.name}`} onPress={() => { setMoreOpen(false); setRotateOpen(true) }}><Icons.RefreshCw size={14} aria-hidden="true" />{compact ? '轮换 Key' : '轮换'}</Button>
  const deleteControl = <Button ref={deleteTriggerRef} size="sm" variant={compact ? 'ghost' : 'danger'} className={compact ? 'w-full justify-start text-danger' : undefined} isDisabled={lifecycleLocked || secret.used_by.length > 0 || removing} aria-describedby={lifecycleLocked ? lifecycleDescriptionId : undefined} aria-label={`删除 ${secret.name}`} onPress={() => { setMoreOpen(false); setDeleteOpen(true) }}><Icons.Trash2 size={14} aria-hidden="true" />{compact ? '删除 Key' : '删除'}</Button>

  return <div className="grid gap-2">
    {lifecycleLocked && <span id={lifecycleDescriptionId} className="sr-only">{lifecycleDescription}</span>}
    {compact
      ? <Popover isOpen={moreOpen} onOpenChange={setMoreOpen}>
          <Popover.Trigger<'button'> ref={moreTriggerRef} aria-label={`更多 Key 操作：${secret.name}`} className="inline-flex size-8 items-center justify-center rounded-[var(--inteliscope-radius-compact)] text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus" render={(triggerProps) => <button {...triggerProps} type="button" />}><Icons.MoreHorizontal size={16} aria-hidden="true" /></Popover.Trigger>
          <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-36 p-0"><Popover.Dialog aria-label={`${secret.name} Key 操作`} className="grid gap-0.5 p-2">{rotateControl}{deleteControl}</Popover.Dialog></Popover.Content>
        </Popover>
      : <div className="flex flex-wrap gap-2">{rotateControl}{deleteControl}</div>}
    <Modal isOpen={rotateOpen} onOpenChange={(open) => {
      if (rotating) return
      if (open) setRotateOpen(true)
      else closeRotate()
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开轮换 Key</Modal.Trigger>
      <Modal.Backdrop isDismissable={!rotating} isKeyboardDismissDisabled={rotating}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{`轮换 ${secret.name}`}</Modal.Heading></Modal.Header>
        <Modal.Body><form id={`rotate-secret-${secret.id}`} className="grid gap-3" onSubmit={rotate}><TextField fullWidth value={value} onChange={setValue} isRequired><Label>新 Key 值</Label><Input type="password" autoComplete="new-password" placeholder="粘贴新 Key（不会回显）" /></TextField>{rotateError && <StatusNotice title={rotateError} status="warning" />}</form></Modal.Body>
        <Modal.Footer><Button type="button" variant="ghost" isDisabled={rotating} onPress={closeRotate}>取消轮换</Button><Button type="submit" form={`rotate-secret-${secret.id}`} isDisabled={rotating}>{rotating ? '轮换中…' : '确认轮换'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
    <Modal isOpen={deleteOpen} onOpenChange={(open) => {
      if (removing) return
      if (open) setDeleteOpen(true)
      else closeDelete()
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开删除 Key</Modal.Trigger>
      <Modal.Backdrop isDismissable={!removing} isKeyboardDismissDisabled={removing}><Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{`删除 ${secret.name}？`}</Modal.Heading></Modal.Header>
        <Modal.Body><p>删除后无法恢复；如需再次使用，必须重新添加 Key。</p>{deleteError && <div className="mt-3"><StatusNotice title={deleteError} status="warning" /></div>}</Modal.Body>
        <Modal.Footer><Button type="button" variant="ghost" isDisabled={removing} onPress={closeDelete}>取消删除</Button><Button type="button" variant="danger" isDisabled={removing} onPress={() => void remove()}>{removing ? '删除中…' : '确认删除'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </div>
}
