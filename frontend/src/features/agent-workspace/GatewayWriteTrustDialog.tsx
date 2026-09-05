import { Button, Modal, StatusNotice } from '../../design-system'

export function GatewayWriteTrustDialog({ open, gatewayUrl, onOpenChange, onConfirm }: {
  open: boolean
  gatewayUrl: string
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}) {
  return <Modal isOpen={open} onOpenChange={onOpenChange}>
    <Modal.Backdrop><Modal.Container size="sm"><Modal.Dialog>
      <Modal.Header><Modal.Heading>确认独立 Gateway 信任域</Modal.Heading></Modal.Header>
      <Modal.Body className="grid gap-3">
        <p className="type-body text-muted">Worktree、任务取消等写操作会改变 Gateway 管理的状态，且 Inscope 无法回滚这些副作用。</p>
        <StatusNotice title="只为当前连接解锁" status="warning">仅当这是你的独立 Gateway 或独立信任域时继续。重连或更换地址后需要重新确认。</StatusNotice>
        <p className="type-meta break-all text-muted">目标：{gatewayUrl}</p>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="ghost" onPress={() => onOpenChange(false)}>保持只读</Button>
        <Button onPress={() => { onConfirm(); onOpenChange(false) }}>这是独立信任域</Button>
      </Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}
