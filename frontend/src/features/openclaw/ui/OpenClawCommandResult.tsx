import { useRef, useState } from 'react'
import { Button, StableAsyncButton } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawSkillSelection } from '../chat/openclawSkillSelection'
import { composerCommands, type ComposerCommand } from './openclawShortcuts'
import { OpenClawCommandSkills } from './OpenClawCommandSkills'
import { OpenClawCommandRuntime } from './OpenClawCommandRuntime'

export type OpenClawCommandRecord = { id: string; scope: string; afterMessageId?: string; command: ComposerCommand; question: string; summary: string; outcome?: string }
export function OpenClawCommandResult({ record, chat, active, snapshot, onSelect, onBusy, onDone }: {
  record: OpenClawCommandRecord
  chat: OpenClawChatController
  active: boolean
  snapshot: boolean
  trusted: boolean
  onSelect: (skill: OpenClawSkillSelection) => void
  onTrust: () => void
  onBusy: (pending: boolean) => void
  onDone: (message: string) => void
}) {
  const locked = useRef(false)
  const [pending, setPending] = useState(false)
  const [issue, setIssue] = useState('')
  const command = record.command
  const disabled = chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading || chat.status !== 'connected'
  async function createConversation() {
    if (locked.current || disabled || !active) return
    locked.current = true; setPending(true); setIssue(''); onBusy(true)
    try {
      if (await chat.newConversation()) onDone('已新建对话，草稿仍保留。')
      else setIssue('新对话未建立，原会话和草稿仍保留。')
    } catch { setIssue('新对话未建立，请重试。') }
    finally { locked.current = false; setPending(false); onBusy(false) }
  }
  return <section aria-label={`/${command} 命令结果`} className="col-span-full grid min-w-0 gap-3 py-4 [overflow-wrap:anywhere]">
    <h3 className="type-control">{composerCommands.find((item) => item.id === command)?.title || '功能不可用'}</h3>
    {command !== 'skills' && <p className="type-body whitespace-pre-wrap">{record.summary}</p>}
    {record.outcome ? <p className="type-body text-muted">{record.outcome}</p> : <>
      {command === 'help' && <dl className="grid gap-2">{composerCommands.map((item) => <div key={item.id}><dt className="type-control">{item.title}</dt><dd className="type-body text-muted">{item.description}</dd></div>)}</dl>}
      {command === 'skills' && <OpenClawCommandSkills chat={chat} active={active} snapshot={snapshot} onSelect={onSelect} />}
      {(command === 'model' || command === 'reasoning') && <OpenClawCommandRuntime chat={chat} command={command} active={active} onBusy={onBusy} onDone={onDone} />}
      {command === 'new' && active && <div className="flex flex-wrap gap-2"><Button size="sm" variant="ghost" isDisabled={pending} onPress={() => onDone('已取消，原会话和草稿仍保留。')}>取消</Button><StableAsyncButton size="sm" pending={pending} pendingContent="正在新建…" isDisabled={disabled} onPress={createConversation}>确认新建</StableAsyncButton></div>}
      {issue && <p className="type-meta text-warning">{issue}</p>}
      {!active && command !== 'help' && command !== 'status' && <p className="type-meta text-muted">此结果只供查看，可从快捷菜单重新选择操作。</p>}
    </>}
  </section>
}
