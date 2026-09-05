import { useState } from 'react'

import {
  Button,
  Checkbox,
  Icons,
  Input,
  Label,
  Modal,
  StableAsyncButton,
  StatusIndicator,
  StatusNotice,
  TextField,
} from '../../design-system'

export function AdminAuthorizationDialog({
  open,
  connecting,
  error,
  onOpenChange,
  onConnect,
}: {
  open: boolean
  connecting: boolean
  error: string
  onOpenChange: (open: boolean) => void
  onConnect: (token: string) => Promise<boolean>
}) {
  const [token, setToken] = useState('')
  const [trustedDomain, setTrustedDomain] = useState(false)

  async function connect() {
    if (!trustedDomain || !token.trim()) return
    if (await onConnect(token)) changeOpen(false)
  }

  function changeOpen(next: boolean) {
    if (!next && connecting) return
    if (!next) {
      setToken('')
      setTrustedDomain(false)
    }
    onOpenChange(next)
  }

  return <Modal isOpen={open} onOpenChange={changeOpen}>
    <Modal.Backdrop isDismissable={!connecting} isKeyboardDismissDisabled={connecting}>
      <Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>临时管理授权</Modal.Heading></Modal.Header>
        <Modal.Body>
          <div className="grid gap-4">
            <div className="flex items-start gap-3 rounded-[var(--inteliscope-radius-card)] bg-default/60 p-3">
              <Icons.ShieldCheck size={20} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
              <p className="type-body text-muted">建立独立的 operator.admin 设备连接。Token、私钥和响应只留在内存，关闭页面或空闲 10 分钟后销毁。</p>
            </div>
            <Checkbox isSelected={trustedDomain} onChange={setTrustedDomain}>
              <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>这是我的独立 Gateway 或独立信任域；共享 Gateway 不应授权管理操作</Checkbox.Content>
            </Checkbox>
            <TextField fullWidth value={token} onChange={setToken} isRequired>
              <Label>Gateway admin token</Label>
              <Input type="password" autoComplete="new-password" aria-label="Gateway admin token" />
            </TextField>
            {error && <StatusNotice title="管理连接失败" status="danger">{error}</StatusNotice>}
            <p className="type-meta text-muted">临时设备若未能由 Gateway 清理，请前往 OpenClaw 设备管理页手动移除。</p>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={connecting} onPress={() => changeOpen(false)}>取消</Button>
          <StableAsyncButton pending={connecting} pendingContent="授权中…" isDisabled={!trustedDomain || !token.trim()} onPress={connect}>授权本次操作</StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}

export function AdminConnectedNotice({ onClose }: { onClose: () => void }) {
  return <div className="flex min-w-0 items-center gap-3 rounded-[var(--inteliscope-radius-control)] border border-success/30 bg-success/10 px-3 py-2">
    <StatusIndicator tone="success" label="临时管理连接已授权" />
    <Button size="sm" variant="ghost" className="ml-auto shrink-0" onPress={onClose}>立即销毁</Button>
  </div>
}
