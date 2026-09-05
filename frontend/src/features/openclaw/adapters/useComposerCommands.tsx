import { useState } from 'react'
import { Button, Modal, StableAsyncButton, actionToast } from '../../../design-system'
import { AgentUseCasesDialog } from '../../agent-workspace/AgentUseCasesDialog'
import { AgentWorktreeDialog } from '../../agent-workspace/AgentWorktreeDialog'
import { GatewayWriteTrustDialog } from '../../agent-workspace/GatewayWriteTrustDialog'
import type { OpenClawChatController } from '../openclawContracts'
import type { ComposerCommand } from '../ui/openclawShortcuts'

export function useComposerCommands(chat: OpenClawChatController) {
  const [dialog, setDialog] = useState<ComposerCommand | 'trust' | null>(null)
  const [trusted, setTrusted] = useState('')
  const [prompt, setPrompt] = useState('')
  const scope = chat.workspace.skillScope?.()
  const connection = JSON.stringify([chat.gatewayUrl, scope?.generation, chat.status])
  const close = (open: boolean) => { if (!open) setDialog(null) }
  function command(next: ComposerCommand, question: string) {
    if (next === 'worktree') {
      const caps = chat.workspace.capabilities()
      if (!['sessions.create', 'projects.list', 'worktrees.branches'].every((method) => caps[method as keyof typeof caps])) {
        actionToast.warning('当前 Gateway 不支持 Worktree 创建'); return
      }
      if (trusted !== connection) { setDialog('trust'); return }
      setPrompt(question)
    }
    setDialog(next)
  }
  const dialogs = <>
    <AgentUseCasesDialog open={dialog === 'help'} onOpenChange={close} />
    <GatewayWriteTrustDialog open={dialog === 'trust'} gatewayUrl={chat.gatewayUrl} onOpenChange={close} onConfirm={() => setTrusted(connection)} />
    <AgentWorktreeDialog open={dialog === 'worktree' && trusted === connection} onOpenChange={close} workspace={chat.workspace} initialPrompt={prompt} onCreated={() => setDialog(null)} />
    <Modal isOpen={dialog === 'new' || dialog === 'status'} onOpenChange={close}>
      <Modal.Backdrop><Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>{dialog === 'new' ? '新建对话？' : '当前对话状态'}</Modal.Heading></Modal.Header>
        <Modal.Body>
          {dialog === 'new' ? <p className="type-body">建立独立的新对话，不删除原会话；未发送的问题、材料、Skill 和图片会保留。</p> : <dl className="type-body grid gap-3">
            <div><dt>连接</dt><dd>{chat.status === 'connected' ? 'Gateway 已连接' : 'Gateway 未连接'}</dd></div>
            <div><dt>模型</dt><dd className="[overflow-wrap:anywhere]">{chat.models.find((item) => item.id === chat.runtimeSelection.modelId)?.name ?? '暂无可信模型信息'}</dd></div>
            <div><dt>运行</dt><dd>{chat.isRunning ? '正在运行' : '空闲'}</dd></div>
            <div><dt>上下文用量</dt><dd>{chat.contextUsage ? `${chat.contextUsage.usedTokens} / ${chat.contextUsage.contextTokens}` : '暂无可信用量'}</dd></div>
          </dl>}
        </Modal.Body>
        <Modal.Footer><Button variant="ghost" onPress={() => close(false)}>{dialog === 'new' ? '取消' : '关闭'}</Button>
          {dialog === 'new' && <StableAsyncButton pending={chat.runtimeUpdating} pendingContent="正在新建…" isDisabled={chat.isRunning || chat.runtimeUpdating} onPress={async () => {
            if (await chat.newConversation()) setDialog(null)
            else actionToast.warning('新对话未建立，原会话和草稿仍保留。')
          }}>确认新建</StableAsyncButton>}
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </>
  return { command, dialogs }
}
