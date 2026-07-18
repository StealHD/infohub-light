import { useEffect, useState } from 'react'

import { Button, CompactSelect, Icons, TextArea, Tooltip } from '../../design-system'
import { buildAgentHandoffPrompt, type AgentModelPreference } from './agentContext'
import type { WorkbenchAgentContextValue } from './workbenchAgentContext'

const modelOptions = [
  { id: 'auto', label: '自动 · OpenClaw 决定' },
  { id: 'fast', label: '速度优先' },
  { id: 'deep', label: '深度分析' },
]

export function HandoffComposer({ value }: { value: WorkbenchAgentContextValue }) {
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2800)
    return () => window.clearTimeout(timer)
  }, [notice])

  async function copyHandoff() {
    try {
      await navigator.clipboard.writeText(buildAgentHandoffPrompt(value.draft))
      setNotice('交接提示词已复制')
    } catch {
      setNotice('无法写入剪贴板，请手动复制')
    }
  }

  return <div className="border-t border-separator p-3">
    <div data-testid="agent-handoff-composer" className="rounded-2xl border border-separator bg-surface-secondary p-2 shadow-sm focus-within:border-border">
      <TextArea
        fullWidth
        variant="secondary"
        className="type-body"
        aria-label="交给 OpenClaw 的问题"
        value={value.draft.question}
        maxLength={1200}
        rows={3}
        placeholder="要求后续处理…"
        onChange={(event) => value.setQuestion(event.target.value)}
      />
      <div className="mt-2 flex min-w-0 items-center gap-1.5 px-1 pb-0.5">
        <Tooltip delay={300}>
          <Tooltip.Trigger aria-label="交接模式说明" className="type-label inline-flex min-h-8 shrink-0 items-center gap-1 rounded-lg px-1.5 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus">
            <Icons.Waypoints size={13} aria-hidden="true" />交接模式
          </Tooltip.Trigger>
          <Tooltip.Content>只复制交接提示词，由本地 OpenClaw 执行。</Tooltip.Content>
        </Tooltip>
        <span className="type-label shrink-0 text-muted">{value.draft.itemIds.length}/8</span>
        <CompactSelect
          ariaLabel="模型偏好"
          value={value.draft.modelPreference}
          options={modelOptions}
          onChange={(modelPreference) => value.setModelPreference(modelPreference as AgentModelPreference)}
          className="flex-1"
        />
        <span role="status" aria-label="交接状态" aria-live="polite" className="type-label min-w-0 truncate text-muted">{notice}</span>
        <Button
          size="sm"
          isIconOnly
          className="size-9 shrink-0 rounded-full active:scale-95 motion-reduce:transform-none"
          isDisabled={!value.draft.itemIds.length}
          aria-label="复制交接提示词"
          onPress={() => void copyHandoff()}
        ><Icons.ArrowUp size={16} aria-hidden="true" /></Button>
      </div>
    </div>
  </div>
}
