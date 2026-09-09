import { useRef, useState } from 'react'
import type { WorkbenchAgentContextValue } from '../../workbench-live/workbenchAgentContext'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawCommandRecord } from '../ui/OpenClawCommandResult'
import { LazyCommandResult } from '../ui/LazyCommandResult'
import type { ComposerCommand } from '../ui/openclawShortcuts'

function commandSummary(command: ComposerCommand, chat: OpenClawChatController) {
  const model = chat.models.find((item) => item.id === chat.runtimeSelection.modelId)?.name ?? '暂无可信模型信息'
  const thinking = chat.thinkingOptions.find((item) => item.id === chat.runtimeSelection.thinkingLevel)?.label ?? '自动'
  switch (command) {
    case 'status': return `当前对话状态\n连接：${chat.status === 'connected' ? 'Gateway 已连接' : 'Gateway 未连接'}\n模型：${model}\n推理档位：${thinking}\n运行：${chat.isRunning ? '正在运行' : '空闲'}\n上下文用量：${chat.contextUsage ? `${chat.contextUsage.usedTokens} / ${chat.contextUsage.contextTokens}` : '暂无可信用量'}`
    case 'help': return '快捷输入：@ 引用 Skill 或材料；/ 查看命令。操作在输入框上方面板中完成，不发送给模型。'
    case 'skills': return '可用 Skills'
    case 'model': return `当前模型：${model}`
    case 'reasoning': return `当前推理档位：${thinking}`
    case 'new': return '新建对话？建立独立的新对话，不删除原会话；未发送的问题、材料、Skill 和图片会保留。'
    case 'worktree': return '此工作区用于聊天与 Skill 调用，不提供 Worktree 任务。'
  }
}

export function useComposerCommands(chat: OpenClawChatController, value: WorkbenchAgentContextValue) {
  const [record, setRecord] = useState<OpenClawCommandRecord | null>(null)
  const [trusted, setTrusted] = useState('')
  const busy = useRef(false)
  const scope = chat.workspace.skillScope?.()
  const connection = JSON.stringify([chat.gatewayUrl, scope?.generation, chat.status])
  const context = JSON.stringify([connection, chat.sessionKey, value.draft.userId])
  const visible = record?.scope === context ? record : null
  function closeCommand() { if (!busy.current) setRecord(null) }
  function command(next: ComposerCommand, question: string) {
    if (busy.current) return false
    setRecord({ id: crypto.randomUUID(), scope: context, command: next, question, summary: commandSummary(next, chat) })
    return true
  }
  const commandPanel = visible ? <LazyCommandResult record={visible} chat={chat} active snapshot={Boolean(value.draft.sourceSnapshot)} trusted={trusted === connection}
      onBusy={(pending) => { busy.current = pending }}
      onTrust={() => setTrusted(connection)}
      onDone={() => setRecord((current) => current?.id === visible.id ? null : current)}
      onSelect={(skill) => {
        value.restoreComposer(value.draft.question, value.draft.items, value.draft.sourceSnapshot, skill)
        setRecord((current) => current?.id === visible.id ? null : current)
        document.querySelector<HTMLElement>('[data-testid="openclaw-composer-textarea"]')?.focus()
      }} /> : null
  return { command, commandPanel, closeCommand }
}
