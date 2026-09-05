import { useRef, useState } from 'react'
import { StableAsyncButton } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'

export function OpenClawCommandRuntime({ chat, command, active, onBusy, onDone }: {
  chat: OpenClawChatController
  command: 'model' | 'reasoning'
  active: boolean
  onBusy: (pending: boolean) => void
  onDone: (message: string) => void
}) {
  const locked = useRef(false)
  const [pending, setPending] = useState<string | null>(null)
  const [issue, setIssue] = useState('')
  const model = chat.models.find((item) => item.id === chat.runtimeSelection.modelId)
  const options = command === 'model' ? chat.models.map((item) => ({ id: item.id, label: item.name }))
    : model?.reasoning === false || !chat.thinkingOptions.length ? [] : [{ id: '', label: '自动' }, ...chat.thinkingOptions.map((item) => ({ id: item.id, label: item.label }))]
  const selected = command === 'model' ? chat.runtimeSelection.modelId : chat.runtimeSelection.thinkingLevel ?? ''
  const unavailable = chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading || chat.status !== 'connected'
  async function apply(id: string, label: string) {
    if (locked.current || unavailable || !active) return
    locked.current = true; setPending(id); setIssue(''); onBusy(true)
    try {
      const ok = command === 'model' ? await chat.setModel(id) : await chat.setThinking(id || null)
      if (ok) onDone(`已切换${command === 'model' ? '模型' : '推理档位'}：${label}`)
      else setIssue('设置未完成，当前会话和草稿仍保留；请重试或查看输入框下方提示。')
    } catch { setIssue('设置未完成，请重试。') }
    finally { locked.current = false; setPending(null); onBusy(false) }
  }
  return <div className="grid min-w-0 gap-2">
    {!options.length && <p className="type-body text-muted">当前连接没有可选的{command === 'model' ? '模型' : '推理档位'}。</p>}
    {unavailable && <p className="type-meta text-muted">连接就绪且当前操作完成后可切换。</p>}
    <ul className="grid min-w-0 gap-2">
      {options.map((option) => <li key={option.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <span className="type-body min-w-0 [overflow-wrap:anywhere]">{option.label}{option.id === selected ? ' · 当前' : ''}</span>
        {active && <StableAsyncButton size="sm" variant="ghost" pending={pending === option.id} pendingContent="正在切换…" isDisabled={unavailable || pending !== null || option.id === selected} onPress={() => apply(option.id, option.label)}>选择 {option.label}</StableAsyncButton>}
      </li>)}
    </ul>
    {issue && <p className="type-meta text-warning">{issue}</p>}
  </div>
}
