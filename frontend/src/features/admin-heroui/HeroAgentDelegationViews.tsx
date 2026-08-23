import { useRef, type ReactNode } from 'react'

import type { AgentDelegation } from '../../api/types'
import {
  Button,
  Card,
  Icons,
  Modal,
  Popover,
  Separator,
  Tooltip,
  TooltipTriggerButton,
  topAnchoredTooltipProps,
} from '../../design-system'

const oneTimeCopyIconClass = 'absolute right-2 top-2 z-10 size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11'

export function OpenClawConfigurationCard({
  title,
  description,
  configuration,
  configurationLabel,
  copyDisabled = false,
  onCopy,
}: {
  title: string
  description: string
  configuration: string
  configurationLabel: string
  copyDisabled?: boolean
  onCopy: () => void
}) {
  return <Card variant="secondary" className="min-w-0 p-4">
    <div className="flex items-center justify-between gap-2">
      <Card.Title>{title}</Card.Title>
      <Button size="sm" variant="ghost" isDisabled={copyDisabled} onPress={onCopy}><Icons.Copy size={15} />复制</Button>
    </div>
    <Card.Description className="mt-1 min-h-10">{description}</Card.Description>
    <pre aria-label={configurationLabel} tabIndex={0} className="type-meta mt-3 max-h-56 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-default p-3 [overflow-wrap:anywhere]">{configuration}</pre>
  </Card>
}

export function OneTimeCopyAction({
  label,
  disabled = false,
  onCopy,
}: {
  label: string
  disabled?: boolean
  onCopy: () => void
}) {
  return <Tooltip delay={250}>
    <TooltipTriggerButton
      aria-label={label}
      className={oneTimeCopyIconClass}
      disabled={disabled}
      onClick={onCopy}
    >
      <Icons.Copy size={15} aria-hidden="true" />
    </TooltipTriggerButton>
    <Tooltip.Content {...topAnchoredTooltipProps}>{label}</Tooltip.Content>
  </Tooltip>
}

export function OneTimeSetupCommand({
  label,
  command,
  copyLabel,
  copyDisabled = false,
  onCopy,
  className = '',
}: {
  label: string
  command: string
  copyLabel: string
  copyDisabled?: boolean
  onCopy: () => void
  className?: string
}) {
  return <div className={`relative min-w-0 ${className}`}>
    <OneTimeCopyAction label={copyLabel} disabled={copyDisabled} onCopy={onCopy} />
    <pre
      aria-label={label}
      tabIndex={0}
      className="type-meta max-h-56 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-default p-3 pr-14 [overflow-wrap:anywhere]"
    >
      {command}
    </pre>
  </div>
}

export function DialogFrame({ title, children, footer, dismissable = true, testId }: {
  title: string
  children: ReactNode
  footer: ReactNode
  dismissable?: boolean
  testId?: string
}) {
  return <Modal.Backdrop isDismissable={dismissable} isKeyboardDismissDisabled={!dismissable} data-testid={testId}>
    <Modal.Container size="lg">
      <Modal.Dialog>
        <Modal.Header><Modal.Heading>{title}</Modal.Heading></Modal.Header>
        <Modal.Body>{children}</Modal.Body>
        <Modal.Footer>{footer}</Modal.Footer>
      </Modal.Dialog>
    </Modal.Container>
  </Modal.Backdrop>
}

export type ConnectionAction = 'copy' | 'rename' | 'revoke' | 'delete'

export function ConnectionCardActions({
  connection,
  open,
  onOpenChange,
  onAction,
}: {
  connection: AgentDelegation
  open: boolean
  onOpenChange: (open: boolean) => void
  onAction: (action: ConnectionAction, trigger: HTMLButtonElement | null) => void
}) {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dangerAction = connection.status === 'active'
    ? { action: 'revoke' as const, label: '吊销连接', icon: Icons.Unplug }
    : connection.status === 'revoked'
      ? { action: 'delete' as const, label: '删除记录', icon: Icons.Trash2 }
      : null

  function choose(action: ConnectionAction) {
    onAction(action, triggerRef.current)
  }

  return <Popover isOpen={open} onOpenChange={onOpenChange}>
    <Popover.Trigger<'button'>
      ref={triggerRef}
      aria-label={`更多操作：${connection.name}`}
      className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11"
      render={(triggerProps) => <button {...triggerProps} type="button" />}
    ><Icons.MoreHorizontal size={17} aria-hidden="true" /></Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-44 p-0">
      <Popover.Dialog aria-label={`${connection.name} 连接操作`} className="grid gap-0.5 p-2">
        <Button variant="ghost" className="w-full justify-start" onPress={() => choose('copy')}>
          <Icons.Copy size={15} aria-hidden="true" />复制配置
        </Button>
        <Button variant="ghost" className="w-full justify-start" onPress={() => choose('rename')}>
          <Icons.Pencil size={15} aria-hidden="true" />重命名
        </Button>
        {dangerAction && <>
          <Separator className="my-1" />
          <Button
            variant="ghost"
            className="w-full justify-start text-danger"
            onPress={() => choose(dangerAction.action)}
          >
            <dangerAction.icon size={15} aria-hidden="true" />{dangerAction.label}
          </Button>
        </>}
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}
