import { Button, Modal } from '../../design-system'
import { AgentUseCaseContent } from './AgentUseCaseContent'

export function AgentUseCasesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <Modal isOpen={open} onOpenChange={onOpenChange}>
    <Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
      <Modal.Header><Modal.Heading>OpenClaw 使用示例</Modal.Heading></Modal.Header>
      <Modal.Body><AgentUseCaseContent /></Modal.Body>
      <Modal.Footer><Button onPress={() => onOpenChange(false)}>知道了</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}
