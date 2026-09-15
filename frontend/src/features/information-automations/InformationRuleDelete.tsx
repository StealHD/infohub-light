import { useState } from 'react'
import type { InformationRule } from '../../api/informationAutomationService'
import { Button, Icons, Modal, StableAsyncButton, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import type { InformationRuleActionState } from './InformationRuleActivation'

export function InformationRuleDelete({ rule, canMutate, dirty = false, action, onDelete, compact = false }: {
  rule: InformationRule; canMutate: boolean; dirty?: boolean; action: InformationRuleActionState
  onDelete: (rule: InformationRule) => Promise<void>; compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const pending = action?.ruleId === rule.id && action.action === 'delete'
  const disabled = !canMutate || dirty || Boolean(action)
  const disabledReason = !canMutate ? '当前账号没有管理权限' : dirty ? '请先保存修改' : action ? '请等待当前操作完成' : undefined
  async function remove() {
    if (disabled) return
    setError('')
    try { await onDelete(rule); setOpen(false) }
    catch (failure) { setError(failure instanceof Error ? failure.message : '删除结果未确认，请刷新任务列表后重试。') }
  }
  return <>
    {compact ? <Tooltip delay={250}><TooltipTriggerButton aria-label={`删除任务：${rule.config.name}`} aria-description={disabledReason} title={disabledReason}
      disabled={disabled} className="size-9 shrink-0 rounded-[var(--inteliscope-radius-control)] text-danger hover:bg-default"
      onClick={() => { setError(''); setOpen(true) }}><Icons.Trash2 size={16} aria-hidden="true" /></TooltipTriggerButton>
      <Tooltip.Content {...topAnchoredTooltipProps}>删除任务</Tooltip.Content></Tooltip>
      : <Button size="sm" variant="ghost" className="text-danger" isDisabled={disabled} onPress={() => { setError(''); setOpen(true) }}><Icons.Trash2 size={15} aria-hidden="true" />删除</Button>}
    <Modal isOpen={open} onOpenChange={(value) => { if (!pending) setOpen(value) }}>
      <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}><Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>删除任务</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body break-words">删除“{rule.config.name}”？任务将从列表移除并停止后续处理，已有运行记录保留作安全回执。</p>
          {error && <p role="alert" className="type-body mt-3">{error}</p>}
        </Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => setOpen(false)}>取消</Button>
          <StableAsyncButton variant="danger" pending={pending} pendingContent="正在删除…" isDisabled={disabled} onPress={remove}>确认删除</StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </>
}
