import { useRef } from 'react'
import { Button } from '../../../design-system'
import { AgentWorktreeDialog } from '../../agent-workspace/AgentWorktreeDialog'
import type { OpenClawChatController } from '../openclawContracts'

export function OpenClawCommandWorktree({ chat, prompt, trusted, onTrust, onBusy, onDone }: {
  chat: OpenClawChatController
  prompt: string
  trusted: boolean
  onTrust: () => void
  onBusy: (pending: boolean) => void
  onDone: (message: string) => void
}) {
  const outcome = useRef('已取消，未创建或启动任务。')
  const capabilities = chat.workspace.capabilities()
  if (!['sessions.create', 'projects.list', 'worktrees.branches'].every((method) => capabilities[method as keyof typeof capabilities])) return <p className="type-body text-muted">当前 Gateway 不支持 Worktree 创建。</p>
  if (chat.isRunning || chat.runtimeUpdating || chat.status !== 'connected') return <p className="type-body text-muted">当前操作结束并连接就绪后，请再次输入 /worktree。</p>
  if (!trusted) return <div className="grid gap-3">
    <h3 className="type-control">确认独立 Gateway 信任域</h3>
    <p className="type-body">Worktree 创建会改变 Gateway 管理的状态，Inscope 无法回滚。仅当这是你的独立 Gateway 或独立信任域时继续。</p>
    <p className="type-meta text-muted [overflow-wrap:anywhere]">目标：{chat.gatewayUrl}</p>
    <p className="type-meta text-muted">本次确认只解锁当前连接。确认后重新输入 /worktree，不会自动创建任务。</p>
    <div className="flex flex-wrap gap-2"><Button size="sm" variant="ghost" onPress={() => onDone('已保持只读。')}>保持只读</Button><Button size="sm" onPress={() => { onTrust(); onDone('当前连接已确认。重新输入 /worktree 填写任务，创建前仍需确认。') }}>这是独立信任域</Button></div>
  </div>
  return <AgentWorktreeDialog inline open workspace={chat.workspace} initialPrompt={prompt} onCreated={(result) => { outcome.current = result && !result.runStarted ? 'Session 与 Worktree 已创建，任务未启动；可从会话列表继续。' : 'Worktree 任务已启动。' }} onPendingChange={onBusy} onOpenChange={(open) => { if (!open) onDone(outcome.current) }} />
}
