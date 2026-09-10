import { useLayoutEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Modal, StableAsyncButton } from '../../design-system'
import { queryKeys } from '../../api/queryKeys'
import { useAgentConnectionContext } from './AgentConnectionContext'

export function DisconnectAgent({ disabled }: { disabled: boolean }) {
  const { api, userId } = useAgentConnectionContext()
  const client = useQueryClient()
  const identity = useRef(userId)
  useLayoutEffect(() => { identity.current = userId }, [userId])
  const [dialog, setDialog] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function disconnect() {
    const owner = userId
    setPending(true)
    setError('')
    try {
      const state = await api.revokeAgentConnection()
      await client.cancelQueries({ queryKey: queryKeys.agentConnection(owner) })
      client.setQueryData(queryKeys.agentConnection(owner), state)
      await client.invalidateQueries({ queryKey: queryKeys.agentConnection(owner) })
      if (identity.current === owner) setDialog(null)
    } catch {
      if (identity.current === owner) setError('解除结果尚未确认，请刷新接入状态核对；不要立即重新接入。')
    } finally {
      setPending(false)
    }
  }
  return <Modal isOpen={dialog === userId} onOpenChange={(open) => {
    if (!pending) { setDialog(open ? userId : null); setError('') }
  }}>
    <Button variant="ghost" isDisabled={disabled}>解除接入</Button>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}>
      <Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>解除 Agent 接入？</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body text-muted">这会撤销当前账号授权、请求停止运行，并清理 OpenClaw 专属配置和凭据。所有浏览器失效，历史会话、订阅与工作目录保留。已产生的费用和外部操作不能追回。清理完成后才能重新接入，不迁移旧会话，也不关闭共享 OpenClaw 服务。</p>
          {error && <p role="alert" className="type-body">{error}</p>}</Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => setDialog(null)}>取消</Button>
          <StableAsyncButton variant="danger" pending={pending} pendingContent="正在解除"
            onPress={disconnect}>确认解除</StableAsyncButton></Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}
