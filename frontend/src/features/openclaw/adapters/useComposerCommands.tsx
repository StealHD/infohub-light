import { useRef, useState } from 'react'
import type { WorkbenchAgentContextValue } from '../../workbench-live/workbenchAgentContext'
import type { OpenClawChatController } from '../openclawContracts'
import { OpenClawCommandResult, type OpenClawCommandRecord } from '../ui/OpenClawCommandResult'
import type { ComposerCommand } from '../ui/openclawShortcuts'

function commandSummary(command: ComposerCommand, chat: OpenClawChatController) {
  const model = chat.models.find((item) => item.id === chat.runtimeSelection.modelId)?.name ?? '暂无可信模型信息'
  const thinking = chat.thinkingOptions.find((item) => item.id === chat.runtimeSelection.thinkingLevel)?.label ?? '自动'
  switch (command) {
    case 'status': return `当前对话状态\n连接：${chat.status === 'connected' ? 'Gateway 已连接' : 'Gateway 未连接'}\n模型：${model}\n推理档位：${thinking}\n运行：${chat.isRunning ? '正在运行' : '空闲'}\n上下文用量：${chat.contextUsage ? `${chat.contextUsage.usedTokens} / ${chat.contextUsage.contextTokens}` : '暂无可信用量'}`
    case 'help': return '快捷输入：@ 引用 Skill 或材料；/ 查看命令。命令结果显示在对话中，不发送给模型。'
    case 'skills': return '可用 Skills'
    case 'model': return `当前模型：${model}`
    case 'reasoning': return `当前推理档位：${thinking}`
    case 'new': return '新建对话？建立独立的新对话，不删除原会话；未发送的问题、材料、Skill 和图片会保留。'
    case 'worktree': return '在对话中准备独立 Worktree 任务，确认前不会创建或启动任务。'
  }
}

export function useComposerCommands(chat: OpenClawChatController, value: WorkbenchAgentContextValue) {
  const [records, setRecords] = useState<OpenClawCommandRecord[]>([])
  const [trusted, setTrusted] = useState('')
  const busy = useRef(false)
  const scope = chat.workspace.skillScope?.()
  const connection = JSON.stringify([chat.gatewayUrl, scope?.generation, chat.status])
  const context = JSON.stringify([connection, chat.sessionKey, value.draft.userId])
  const visible = records.filter((record) => record.scope === context)
  function command(next: ComposerCommand, question: string) {
    if (busy.current) return false
    setRecords((current) => [...current.slice(-19), { id: crypto.randomUUID(), scope: context, afterMessageId: chat.messages.at(-1)?.id, command: next, question, summary: commandSummary(next, chat) }])
    return true
  }
  const commandEntries = visible.map((record) => ({
    id: record.id, afterMessageId: record.afterMessageId,
    content: <OpenClawCommandResult record={record} chat={chat} active={record.id === visible.at(-1)?.id} snapshot={Boolean(value.draft.sourceSnapshot)} trusted={trusted === connection}
      onBusy={(pending) => { busy.current = pending }}
      onTrust={() => setTrusted(connection)}
      onDone={(outcome) => setRecords((current) => current.map((item) => item.id === record.id ? { ...item, outcome } : item))}
      onSelect={(skill) => {
        value.restoreComposer(value.draft.question, value.draft.items, value.draft.sourceSnapshot, skill)
        setRecords((current) => current.map((item) => item.id === record.id ? { ...item, outcome: `已选择 ${skill.name}，下一条消息会使用此 Skill。` } : item))
        document.querySelector<HTMLElement>('[data-testid="openclaw-composer-textarea"]')?.focus()
      }} />,
  }))
  return { command, commandEntries }
}
