import { useState } from 'react'
import { Button, Modal, StableAsyncButton, TextField, TextArea, Label } from '../../design-system'
import type { AgentAccessRequest } from '../../api/agentConnectionService'
import { useAgentConnectionContext } from './AgentConnectionContext'
import { RevokeAccess } from './RevokeAccess'
import { cleanupLabel } from './cleanupLabel'

const roleNames: Record<string, string> = { owner: '所有者', admin: '管理员', member: '成员', viewer: '只读成员' }

export function AccessRequestRow({ row, refresh }: { row: AgentAccessRequest; refresh: () => Promise<unknown> }) {
  const { api } = useAgentConnectionContext()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function act(decision: 'approved' | 'rejected' | 'retry') {
    setPending(true); setError('')
    try {
      if (decision === 'retry') await api.retryAgentAccess(row.id)
      else await api.decideAgentAccess(row.id, row.revision, decision, reason)
      setOpen(false)
      await refresh()
    } catch { setError('处理未确认或申请已变化，请刷新核对后再试。') }
    finally { setPending(false) }
  }
  const status = row.cleanup ? cleanupLabel(row.cleanup.phase) : row.state === 'pending' ? '待审核' : row.state === 'rejected' ? '已拒绝' : row.state === 'ready'
    ? '接入完成' : row.phase === 'failed' ? '配置失败' : row.phase === 'recovery' ? '待恢复'
      : row.phase === 'waiting' ? '等待安全重载' : '正在配置'
  return <div className="border-b border-separator py-4 grid gap-3 min-[768px]:grid-cols-2">
    <div className="min-w-0 grid gap-1">
      <p className="type-control break-words">{row.display_name || row.username} · {row.username}</p>
      <p className="type-meta text-muted">{roleNames[row.role || 'member'] || row.role} · {new Date(row.created_at).toLocaleString()} · {status}</p>
      {(row.reason || row.error) && <p className="type-body break-words">{row.reason || row.error}</p>}
      {error && !open && <p role="alert" className="type-body">{error}</p>}
    </div>
    <div className="flex flex-wrap items-center gap-2 min-[768px]:justify-end">
      {row.state === 'pending' && !row.cleanup && <>
        <StableAsyncButton pending={pending} pendingContent="处理中" onPress={() => act('approved')}>允许并接入</StableAsyncButton>
        <Modal isOpen={open} onOpenChange={(value) => { if (!pending) { setOpen(value); setError('') } }}>
          <Button variant="ghost" isDisabled={pending}>拒绝</Button>
          <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}>
            <Modal.Container size="sm"><Modal.Dialog>
              <Modal.Header><Modal.Heading>拒绝接入申请</Modal.Heading></Modal.Header>
              <Modal.Body><p className="type-body">申请人：{row.display_name || row.username}（{row.username}）</p>
                <TextField isRequired value={reason} onChange={setReason}><Label>拒绝原因</Label><TextArea maxLength={200} /></TextField>
                {error && <p role="alert" className="type-body">{error}</p>}</Modal.Body>
              <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => setOpen(false)}>取消</Button>
                <StableAsyncButton variant="danger" pending={pending} pendingContent="处理中" isDisabled={!reason.trim()}
                  onPress={() => act('rejected')}>确认拒绝</StableAsyncButton></Modal.Footer>
            </Modal.Dialog></Modal.Container>
          </Modal.Backdrop>
        </Modal>
      </>}
      {row.state === 'approved' && !row.cleanup && ['failed', 'recovery', 'waiting'].includes(row.phase || '') &&
        <StableAsyncButton pending={pending} pendingContent="处理中" onPress={() => act('retry')}>
          {row.phase === 'waiting' ? '继续核验' : '重试配置'}</StableAsyncButton>}
      {row.binding_id && ['approved', 'ready'].includes(row.state) && <RevokeAccess row={row} refresh={refresh} />}
    </div>
  </div>
}
