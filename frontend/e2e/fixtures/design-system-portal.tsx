import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import { Button, DesignSystemProvider, Modal, Skeleton, Tooltip } from '../../src/design-system'

declare global {
  interface Window {
    unmountDesignSystemFixture: () => void
  }
}

function PortalFixture() {
  return <MemoryRouter>
    <DesignSystemProvider>
      <div data-testid="static-surface">静态内容</div>
      <Skeleton animationType="pulse" data-testid="continuous-skeleton">加载中</Skeleton>
      <span className="spinner" data-testid="continuous-spinner" />
      <Button data-testid="finite-button">保存</Button>

      <Modal isOpen>
        <Modal.Trigger><button type="button">弹窗目标</button></Modal.Trigger>
        <Modal.Backdrop>
          <Modal.Container>
            <Modal.Dialog>
              <Modal.Heading>真实 Portal 弹窗</Modal.Heading>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>

      <Tooltip isOpen delay={0} closeDelay={0}>
        <Tooltip.Trigger><button type="button">提示目标</button></Tooltip.Trigger>
        <Tooltip.Content>真实 Portal 提示</Tooltip.Content>
      </Tooltip>
    </DesignSystemProvider>
  </MemoryRouter>
}

const root = createRoot(document.getElementById('root')!)
root.render(<PortalFixture />)
window.unmountDesignSystemFixture = () => root.unmount()
