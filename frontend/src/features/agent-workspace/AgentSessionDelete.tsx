import { useState } from 'react'
import { Button, Modal, StableAsyncButton } from '../../design-system'
import type { OpenClawWorkspaceController, OpenClawWorkspaceSession } from '../openclaw'
import { sessionDeleteReason } from '../openclaw/workspace/openclawSessionDeletion'
import { openClawSessionTitle } from '../openclaw/chat/openclawSessionTitle'

export function AgentSessionDelete({ session, current, workspace, disabled }: {
  session: OpenClawWorkspaceSession; current: boolean; workspace: OpenClawWorkspaceController; disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const reason = sessionDeleteReason(session, current ? session.key : null, workspace.capabilities()['sessions.delete'])
    || (disabled ? '正在切换会话，请稍后重试' : null)
  async function remove() {
    if (pending || reason) return
    setPending(true); setError('')
    try { await workspace.deleteSession(session.key); setOpen(false) }
    catch (failure) { setError(failure instanceof Error ? failure.message : '删除未确认，请刷新会话列表核对。') }
    finally { setPending(false) }
  }
  return <>
    <Button variant="danger" isDisabled={Boolean(reason)} onPress={() => { setError(''); setOpen(true) }}>删除会话</Button>
    {reason && <p className="type-meta text-muted">{reason}</p>}
    <Modal isOpen={open} onOpenChange={(value) => { if (!pending) setOpen(value) }}>
      <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}><Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>删除会话</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body break-words">删除“{openClawSessionTitle(session)}”？会话及相关运行资源将由 OpenClaw 清理，此操作无法在本站撤销。</p>
          {error && <p role="alert" className="type-body mt-3">{error}</p>}
        </Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => setOpen(false)}>取消</Button>
          <StableAsyncButton variant="danger" pending={pending} pendingContent="正在删除…" isDisabled={Boolean(reason)} onPress={remove}>确认删除</StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </>
}
