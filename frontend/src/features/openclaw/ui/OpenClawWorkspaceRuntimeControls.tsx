import { useRef, useState } from 'react'
import { Button, Icons, ListBox, Popover, Tooltip, TooltipTriggerButton, anchoredTooltipProps, topAnchoredTooltipProps } from '../../../design-system'
import { EffortUsageNotice } from '../../../design-system/EffortUsageNotice'
import { EffortSlider } from '../../../design-system/EffortSlider'
import { OpenClawContextUsageIndicator } from './OpenClawMessageViews'
import type { OpenClawChatController } from '../openclawContracts'

export default function OpenClawWorkspaceRuntimeControls({ chat, picker, onPickerClose }: {
  chat: OpenClawChatController; picker?: 'model' | 'reasoning' | null; onPickerClose?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'effort' | 'model'>('effort')
  const [preview, setPreview] = useState<number | null>(null)
  const [pending, setPending] = useState(false)
  const [issue, setIssue] = useState('')
  const [usageNotice, setUsageNotice] = useState({ id: 0, kind: 'fast' as 'fast' | 'ultra' })
  const latch = useRef(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const modelRef = useRef<HTMLButtonElement>(null)
  const model = chat.models.find((entry) => entry.id === chat.runtimeSelection.modelId)
  const options = (model?.reasoning === false ? [] : chat.thinkingOptions).filter((option) => !['auto', '__auto__', 'off', 'none'].includes(option.id))
  const defaultIndex = options.findIndex((entry) => entry.id === chat.runtimeSelection.defaultThinkingLevel)
  const selected = options.findIndex((entry) => entry.id === (chat.runtimeSelection.thinkingLevel ?? chat.runtimeSelection.defaultThinkingLevel))
  const selectedLabel = options[selected]?.label ?? '选择思考'
  const value = Math.max(0, Math.min(preview ?? selected, options.length - 1))
  const modelLabel = model?.name ?? (chat.runtimeLoading ? '正在读取模型…' : 'OpenClaw 当前设置')
  const disabled = pending || chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading
  const unavailable = !model ? '尚未取得当前模型信息。' : model.reasoning === false ? '此模型未提供推理档位。' : !options.length ? 'OpenClaw 未返回此模型的可选推理档位。' : ''
  const modelView = picker === 'model' || view === 'model'
  const isOpen = Boolean(picker) || open
  const fastEnabled = chat.runtimeSelection.fastMode ?? chat.runtimeSelection.defaultFastMode ?? false
  const effect = unavailable ? 'none' : fastEnabled ? 'fast' : options[preview ?? selected]?.id === 'ultra' ? 'ultra' : 'none'

  async function apply(action: () => Promise<boolean>) {
    if (latch.current || disabled) return
    latch.current = true
    setPending(true)
    setIssue('')
    try { if (!await action()) setIssue('设置未能更新，请重试。') }
    catch { setIssue('设置未能更新，请重试。') }
    finally { latch.current = false; setPending(false); setPreview(null) }
  }

  function commit(index: number) {
    const option = options[index]
    if (!option || unavailable || option.id === chat.runtimeSelection.thinkingLevel) { setPreview(null); return }
    void apply(async () => { const success = await chat.setThinking(option.id); if (success && option.id === 'ultra') setUsageNotice((notice) => ({ id: notice.id + 1, kind: 'ultra' })); return success })
  }

  return <div data-testid="openclaw-runtime-controls" className="flex min-w-0 items-center justify-end gap-1">
    <OpenClawContextUsageIndicator usage={chat.contextUsage} />
    <Popover isOpen={isOpen} onOpenChange={(next) => { setOpen(next); if (!next) { setPreview(null); setView('effort'); onPickerClose?.() } }}>
      <Button ref={triggerRef} variant="ghost" className="effort-picker-trigger type-control" aria-label={`OpenClaw 模型：${modelLabel}，思考程度：${selectedLabel}${fastEnabled ? '，Fast 已开启' : ''}`} aria-busy={pending} isDisabled={disabled}>
        {fastEnabled && <Icons.Zap className="effort-toolbar-fast" size={15} fill="currentColor" aria-hidden="true" />}<span className="effort-toolbar-model" title={modelLabel}>{modelLabel}</span><span className="effort-toolbar-level">{selectedLabel}</span><Icons.ChevronDown size={15} aria-hidden="true" />
      </Button>
      <Popover.Content placement="top end" offset={8} containerPadding={12} className="effort-picker-surface">
        <Popover.Dialog aria-label="模型与思考程度" className="p-0" aria-busy={pending}><div className="effort-picker-dialog" onKeyDownCapture={(event) => {
          if (event.key !== 'Escape') return
          event.preventDefault(); event.stopPropagation()
          setOpen(false); setView('effort'); setPreview(null); onPickerClose?.()
          requestAnimationFrame(() => triggerRef.current?.focus())
        }}>
          {modelView ? <>
            <Button isIconOnly size="sm" variant="ghost" className="effort-model-back" aria-label="返回思考程度" onPress={() => { setView('effort'); setOpen(true); onPickerClose?.(); requestAnimationFrame(() => modelRef.current?.focus()) }}><Icons.ChevronLeft size={15} aria-hidden="true" /></Button>
            <ListBox autoFocus="first" aria-label="OpenClaw 模型" className="effort-model-list" selectionMode="single" selectedKeys={chat.runtimeSelection.modelId ? [chat.runtimeSelection.modelId] : []} disabledKeys={disabled ? chat.models.map((entry) => entry.id) : []}>
              {chat.models.map((entry) => <ListBox.Item id={entry.id} key={entry.id} textValue={`${entry.provider} ${entry.name}`} onPress={() => {
                void apply(async () => { const success = await chat.setModel(entry.id); if (success) { setView('effort'); setOpen(false); onPickerClose?.(); requestAnimationFrame(() => triggerRef.current?.focus()) } return success })
              }}>
              <div className="min-w-0"><span className="type-control block [overflow-wrap:anywhere]">{entry.name}</span><span className="type-meta text-muted">{entry.provider}{entry.supportsImages ? ' · 支持图片' : ''}</span></div><ListBox.ItemIndicator />
            </ListBox.Item>)}</ListBox>
          </> : <><div className="effort-picker-heading">
            <Tooltip><TooltipTriggerButton aria-label="Fast 快速模式" aria-pressed={fastEnabled} disabled={disabled || !model} onClick={() => apply(async () => { const success = await chat.setFastMode(!fastEnabled); if (success && !fastEnabled) setUsageNotice((notice) => ({ id: notice.id + 1, kind: 'fast' })); return success })} className="effort-picker-fast"><Icons.Zap size={15} strokeWidth={1.7} aria-hidden="true" /></TooltipTriggerButton><Tooltip.Content {...topAnchoredTooltipProps} className="effort-fast-tooltip"><span className="block type-control">Fast</span><span className="block type-meta text-muted">用量更多</span></Tooltip.Content></Tooltip>
            <div className="effort-picker-caption min-w-0 text-center">
              <Button ref={modelRef} variant="ghost" className="effort-model-trigger type-body" aria-label={`选择模型：${modelLabel}`} isDisabled={disabled || !chat.models.length} onPress={() => setView('model')}>
                <span className="effort-picker-value type-control">{preview !== null ? options[value]?.label : selectedLabel}<Icons.ChevronRight size={12} aria-hidden="true" /></span>
                <span className="effort-picker-model-name type-meta">{modelLabel}</span>
              </Button>
              <EffortUsageNotice key={usageNotice.id} enabled={isOpen && usageNotice.id > 0 && (usageNotice.kind === 'fast' ? fastEnabled : chat.runtimeSelection.thinkingLevel === 'ultra')} message={usageNotice.kind === 'fast' ? '更快消耗使用额度' : 'Ultra 会消耗更多 Token'} />
            </div>
            <Tooltip><TooltipTriggerButton aria-label="恢复默认思考" disabled={disabled || Boolean(unavailable) || defaultIndex < 0 || selected === defaultIndex} onClick={() => commit(defaultIndex)} className="effort-reset-button"><Icons.RotateCcw size={15} aria-hidden="true" /></TooltipTriggerButton><Tooltip.Content {...anchoredTooltipProps}>恢复 Gateway 默认档位</Tooltip.Content></Tooltip>
          </div>
          <EffortSlider effect={effect} labels={options.map((entry) => entry.label)} valueLabel={preview === null && selected < 0 ? '未选择思考档位' : undefined} value={value} disabled={disabled || Boolean(unavailable)} onChange={setPreview} onCommit={commit} />
          {unavailable && <p className="type-meta text-muted">{unavailable}</p>}</> }
          {(issue || chat.runtimeIssue) && <p role="status" className="type-meta text-warning">{chat.runtimeIssue || issue}</p>}
          <Button variant="ghost" size="sm" className="sr-only focus:not-sr-only" onPress={() => { setOpen(false); setView('effort'); onPickerClose?.() }}>关闭模型与思考设置</Button>
        </div></Popover.Dialog>
      </Popover.Content>
    </Popover>
  </div>
}
