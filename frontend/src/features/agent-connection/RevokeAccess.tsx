import { useState } from 'react'
import { Button, Modal, StableAsyncButton } from '../../design-system'
import type { AgentAccessRequest } from '../../api/agentConnectionService'
import { useAgentConnectionContext } from './AgentConnectionContext'

export function RevokeAccess({ row, refresh }: { row: AgentAccessRequest; refresh: () => Promise<unknown> }) {
  const { api } = useAgentConnectionContext()
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function submit(retry = false) {
    setPending(true); setError('')
    try {
      if (retry && row.cleanup) await api.retryMemberCleanup(row.id, row.cleanup.revision)
      else await api.revokeMemberAgent(row.id, row.revision)
      setOpen(false)
      await refresh()
    } catch { setError('操作未确认，请刷新核对；不要假定 OpenClaw 已完成清理。') }
    finally { setPending(false) }
  }
  if (row.cleanup) return <div className="grid gap-2">
    {row.cleanup.error && <p className="type-body text-muted">{row.cleanup.error}</p>}
    {['failed', 'recovery'].includes(row.cleanup.phase) && <StableAsyncButton pending={pending} pendingContent="正在重试" onPress={() => submit(true)}>重试清理</StableAsyncButton>}
    {error && <p role="alert" className="type-body">{error}</p>}
  </div>
  return <Modal isOpen={open} onOpenChange={(value) => { if (!pending) setOpen(value) }}>
    <Button variant="ghost">撤销接入</Button>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}>
      <Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>撤销成员接入？</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body">{row.display_name || row.username}（{row.username}）</p>
          <p className="type-body">将封禁所有浏览器访问，请求停止该成员运行，并移除 OpenClaw 专属配置和数据授权。历史会话、订阅及工作目录保留。已产生的费用与外部操作不能追回。</p>
          {error && <p role="alert" className="type-body">{error}</p>}</Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => setOpen(false)}>取消</Button>
          <StableAsyncButton variant="danger" pending={pending} pendingContent="正在撤销" onPress={() => submit()}>确认撤销</StableAsyncButton></Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}
